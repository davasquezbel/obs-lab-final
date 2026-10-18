# ── Módulo C: observabilidad de red y seguridad ───────────────────────
# Fuentes:
#   - VPC Flow Logs (subred de GKE, con metadatos de pod/workload)      → tráfico E-W / N-S
#   - Dataplane V2 NetworkLogging (eBPF, logName policy-action)          → conexiones denegadas
#   - Logs de service-a (event=auth.login)                               → autenticación fallida
#   - Security Command Center + Artifact Analysis (vía security-exporter) → findings y CVEs

locals {
  flows_log = "logName=\"projects/${var.project_id}/logs/compute.googleapis.com%2Fvpc_flows\""

  # Origen fuera de los namespaces autorizados hacia la aplicación (movimiento lateral)
  flows_unexpected_source = join(" AND ", [
    local.flows_log,
    "jsonPayload.dest_gke_details.pod.pod_namespace=\"${var.app_namespace}\"",
    "jsonPayload.src_gke_details.pod.pod_namespace:*",
    "NOT jsonPayload.src_gke_details.pod.pod_namespace=(\"${var.app_namespace}\" OR \"istio-gateway\")",
  ])
  netpol_denied = "logName=\"projects/${var.project_id}/logs/policy-action\" AND jsonPayload.disposition=\"deny\""
  auth_failures = join(" AND ", [
    "resource.type=\"k8s_container\"",
    "resource.labels.namespace_name=\"${var.app_namespace}\"",
    "jsonPayload.event=\"auth.login\"",
    "jsonPayload.auth_result=\"failure\"",
  ])
}

# ── Métricas basadas en logs ──────────────────────────────────────────
resource "google_logging_metric" "flows_east_west" {
  name        = "security/flows_east_west"
  description = "Flujos E-W (pod → pod) registrados por VPC Flow Logs"
  filter      = "${local.flows_log} AND jsonPayload.src_gke_details.pod.pod_namespace:* AND jsonPayload.dest_gke_details.pod.pod_namespace:*"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key = "src_workload"
    }
    labels {
      key = "dest_workload"
    }
    labels {
      key = "dest_port"
    }
  }
  label_extractors = {
    src_workload  = "EXTRACT(jsonPayload.src_gke_details.pod.workload.name)"
    dest_workload = "EXTRACT(jsonPayload.dest_gke_details.pod.workload.name)"
    dest_port     = "EXTRACT(jsonPayload.connection.dest_port)"
  }
}

resource "google_logging_metric" "flows_north_south" {
  name        = "security/flows_north_south"
  description = "Flujos N-S (un extremo fuera de la VPC) registrados por VPC Flow Logs"
  filter      = "${local.flows_log} AND (NOT jsonPayload.src_vpc.vpc_name:* OR NOT jsonPayload.dest_vpc.vpc_name:*)"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key = "direction"
    }
    labels {
      key = "workload"
    }
  }
  label_extractors = {
    # reporter=DEST → el destino está en la VPC (entrante); SRC → saliente
    direction = "EXTRACT(jsonPayload.reporter)"
    workload  = "REGEXP_EXTRACT(jsonPayload.dest_gke_details.pod.workload.name, \"(.*)\")"
  }
}

# N-S hacia el ingress gateway, con la IP pública REAL del cliente (externalTrafficPolicy=Local)
# y su geolocalización. El gateway gestionado no propaga X-Forwarded-For, así que la
# atribución de ataques (p. ej. fuerza bruta) se hace en la capa de red.
resource "google_logging_metric" "flows_gateway_ingress" {
  name        = "security/flows_gateway_ingress"
  description = "Conexiones externas al ingress gateway por IP y país de origen (VPC Flow Logs)"
  filter      = "${local.flows_log} AND jsonPayload.dest_gke_details.service.service_name=\"istio-ingressgateway\" AND NOT jsonPayload.src_vpc.vpc_name:*"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key = "src_ip"
    }
    labels {
      key = "src_country"
    }
    labels {
      key = "src_city"
    }
  }
  label_extractors = {
    src_ip      = "EXTRACT(jsonPayload.connection.src_ip)"
    src_country = "EXTRACT(jsonPayload.src_location.country)"
    src_city    = "EXTRACT(jsonPayload.src_location.city)"
  }
}

resource "google_logging_metric" "flows_unexpected_source" {
  name        = "security/flows_unexpected_source"
  description = "Flujos hacia la aplicación desde namespaces no autorizados (VPC Flow Logs)"
  filter      = local.flows_unexpected_source
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key = "src_namespace"
    }
    labels {
      key = "dest_workload"
    }
  }
  label_extractors = {
    src_namespace = "EXTRACT(jsonPayload.src_gke_details.pod.pod_namespace)"
    dest_workload = "EXTRACT(jsonPayload.dest_gke_details.pod.workload.name)"
  }
}

resource "google_logging_metric" "netpol_denied" {
  name        = "security/netpol_denied"
  description = "Conexiones denegadas por NetworkPolicy (Dataplane V2 / eBPF)"
  filter      = local.netpol_denied
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key = "src_namespace"
    }
    labels {
      key = "dest_workload"
    }
    labels {
      key = "dest_port"
    }
  }
  label_extractors = {
    src_namespace = "EXTRACT(jsonPayload.src.pod_namespace)"
    dest_workload = "EXTRACT(jsonPayload.dest.workload_name)"
    dest_port     = "EXTRACT(jsonPayload.connection.dest_port)"
  }
}

resource "google_logging_metric" "auth_failures" {
  name        = "security/auth_failures"
  description = "Intentos de login fallidos en service-a, por IP de origen"
  filter      = local.auth_failures
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key = "client_ip"
    }
  }
  label_extractors = {
    client_ip = "EXTRACT(jsonPayload.client_ip)"
  }
}

# ── Alertas de seguridad (correo) ─────────────────────────────────────
resource "google_monitoring_alert_policy" "sec_lateral_movement" {
  display_name = "[SEG] Movimiento lateral bloqueado (eBPF / NetworkPolicy)"
  combiner     = "OR"
  severity     = "CRITICAL"
  user_labels  = { alert_type = "security", severity = "critical" }

  conditions {
    display_name = "Dataplane V2 denegó una conexión hacia la aplicación"
    condition_matched_log {
      filter = local.netpol_denied
      label_extractors = {
        src_namespace = "EXTRACT(jsonPayload.src.pod_namespace)"
        src_pod       = "EXTRACT(jsonPayload.src.pod_name)"
        dest_workload = "EXTRACT(jsonPayload.dest.workload_name)"
        dest_port     = "EXTRACT(jsonPayload.connection.dest_port)"
      }
    }
  }
  documentation {
    content   = <<-EOT
      Conexión **denegada** por la microsegmentación: `$${log.extracted_label.src_namespace}/$${log.extracted_label.src_pod}`
      → `$${log.extracted_label.dest_workload}:$${log.extracted_label.dest_port}`.

      Un pod fuera de los namespaces autorizados intentó alcanzar la aplicación (posible movimiento lateral).
      1. Identificar el pod de origen y su dueño (`kubectl -n <ns> describe pod <pod>`).
      2. Revisar VPC Flow Logs y el dashboard *Golden Signals de Seguridad*.
      3. Aislar/eliminar el workload si no es legítimo.
    EOT
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id, google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "sec_unexpected_flows" {
  display_name = "[SEG] Tráfico E-W desde origen no autorizado (VPC Flow Logs)"
  combiner     = "OR"
  severity     = "WARNING"
  user_labels  = { alert_type = "security", severity = "warning" }

  conditions {
    display_name = "Flujo hacia otel-lab desde un namespace no autorizado"
    condition_matched_log {
      filter = local.flows_unexpected_source
      label_extractors = {
        src_namespace = "EXTRACT(jsonPayload.src_gke_details.pod.pod_namespace)"
        src_pod       = "EXTRACT(jsonPayload.src_gke_details.pod.pod_name)"
        dest_workload = "EXTRACT(jsonPayload.dest_gke_details.pod.workload.name)"
        dest_port     = "EXTRACT(jsonPayload.connection.dest_port)"
      }
    }
  }
  documentation {
    content   = "VPC Flow Logs registró tráfico desde `$${log.extracted_label.src_namespace}/$${log.extracted_label.src_pod}` hacia `$${log.extracted_label.dest_workload}:$${log.extracted_label.dest_port}` (fuera del patrón de comunicación esperado)."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id, google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "sec_bruteforce" {
  display_name = "[SEG] Posible fuerza bruta en /login (baseline + 3σ)"
  combiner     = "OR"
  severity     = "CRITICAL"
  user_labels  = { alert_type = "security", severity = "critical" }

  conditions {
    display_name = "logins fallidos/s > max(media 1h + 3σ, 0.5/s)"
    condition_prometheus_query_language {
      query               = <<-EOT
        sum(rate(auth_attempts_total{namespace="${var.app_namespace}",auth_result="failure"}[2m]))
        > clamp_min(
            avg_over_time(sum(rate(auth_attempts_total{namespace="${var.app_namespace}",auth_result="failure"}[2m]))[1h:1m])
            + 3 * stddev_over_time(sum(rate(auth_attempts_total{namespace="${var.app_namespace}",auth_result="failure"}[2m]))[1h:1m]),
            0.5)
      EOT
      duration            = "60s"
      evaluation_interval = "30s"
    }
  }
  documentation {
    content   = <<-EOT
      Tasa de logins fallidos muy por encima de su línea base. Revisar las IPs de origen en el
      dashboard *Golden Signals de Seguridad* (panel "Logins fallidos por IP") o en Logs Explorer:
      `jsonPayload.event="auth.login" jsonPayload.auth_result="failure"`.
    EOT
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id, google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "sec_critical_cves" {
  display_name = "[SEG] CVEs críticos en imágenes en uso"
  combiner     = "OR"
  severity     = "WARNING"
  user_labels  = { alert_type = "security", severity = "warning" }

  conditions {
    display_name = "image_vulnerabilities{severity=CRITICAL} > 0"
    condition_threshold {
      filter          = "metric.type=\"custom.googleapis.com/security/image_vulnerabilities\" AND resource.type=\"global\" AND metric.label.severity=\"CRITICAL\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period     = "600s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }
  documentation {
    content   = "Hay CVEs de severidad CRÍTICA en imágenes desplegadas. Ver Artifact Registry → Vulnerabilidades y reconstruir con una imagen base parchada."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id, google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "86400s"
  }
}
