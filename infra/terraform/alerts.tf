# ── AIOps: alertas estáticas (línea base ruidosa) vs. dinámicas correlacionadas ──
# Todas las políticas notifican al webhook alert-enricher, que registra cada alerta
# (alert.received) → permite contar alertas por tipo y medir la reducción de ruido.

locals {
  ns = var.app_namespace

  # Error rate por servicio. El "or 0 *" garantiza una serie aun sin 5xx, de modo que
  # el baseline (avg/stddev) existe también cuando el servicio está sano.
  err = {
    for w in ["1m", "2m"] : w => <<-EOT
      (
        sum by (job) (rate(http_server_requests_total{namespace="${local.ns}",status_class="5xx"}[${w}]))
        or 0 * sum by (job) (rate(http_server_requests_total{namespace="${local.ns}"}[${w}]))
      )
      / sum by (job) (rate(http_server_requests_total{namespace="${local.ns}"}[${w}]))
    EOT
  }
  p99 = {
    for w in ["1m", "2m"] : w => <<-EOT
      histogram_quantile(0.99, sum by (job, le) (rate(http_server_request_duration_seconds_bucket{namespace="${local.ns}"}[${w}])))
    EOT
  }

  # Baseline dinámico: media + 2σ de la última hora (subconsulta con paso de 1 min)
  err_baseline_2sigma = <<-EOT
    avg_over_time((${local.err["2m"]})[1h:1m]) + 2 * stddev_over_time((${local.err["2m"]})[1h:1m])
  EOT
  p99_baseline_2sigma = <<-EOT
    avg_over_time((${local.p99["2m"]})[1h:1m]) + 2 * stddev_over_time((${local.p99["2m"]})[1h:1m])
  EOT

  runbook = <<-EOT
    **Servicio:** $${metric.label.job}

    El webhook *alert-enricher* adjunta en Cloud Logging (`jsonPayload.event="alert.enriched"`)
    el **trace_id** del request fallido/lento, el span más lento y enlaces a la traza y sus logs.

    1. Abrir la traza enriquecida y ubicar el span con mayor duración o con error.
    2. Revisar el dashboard *Golden Signals* y la topología de Cloud Service Mesh.
    3. Verificar si hay un experimento de caos activo: `kubectl get networkchaos,httpchaos -A`.
  EOT
}

# ── Canales de notificación ───────────────────────────────────────────
resource "random_password" "webhook_token" {
  length  = 32
  special = false
}

resource "google_monitoring_notification_channel" "enricher" {
  display_name = "alert-enricher (webhook Cloud Run)"
  type         = "webhook_tokenauth"
  labels = {
    url = "${google_cloud_run_v2_service.enricher.uri}/alert?token=${random_password.webhook_token.result}"
  }
}

resource "google_monitoring_notification_channel" "email" {
  display_name = "Correo del laboratorio"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

# ── Línea base: umbrales ESTÁTICOS sin correlación (configuración "ingenua") ──
resource "google_monitoring_alert_policy" "static_error_rate" {
  display_name = "[ESTÁTICA] Error rate > 1%"
  combiner     = "OR"
  user_labels  = { alert_type = "static", severity = "warning" }

  conditions {
    display_name = "error rate (1m) > 1%"
    condition_prometheus_query_language {
      query               = "(${local.err["1m"]}) > 0.01"
      duration            = "0s"
      evaluation_interval = "30s"
    }
  }
  notification_channels = [google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "static_latency" {
  display_name = "[ESTÁTICA] Latencia p99 > 200 ms"
  combiner     = "OR"
  user_labels  = { alert_type = "static", severity = "warning" }

  conditions {
    display_name = "p99 (1m) > 200 ms"
    condition_prometheus_query_language {
      query               = "(${local.p99["1m"]}) > 0.2"
      duration            = "0s"
      evaluation_interval = "30s"
    }
  }
  notification_channels = [google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

# ── AIOps: detección de anomalías con baseline dinámico (z-score ≥ 2σ) ──
resource "google_monitoring_alert_policy" "anomaly_error_rate" {
  display_name = "[AIOps] Anomalía de error rate (baseline + 2σ)"
  combiner     = "OR"
  user_labels  = { alert_type = "aiops", severity = "warning" }

  conditions {
    display_name = "error rate (2m) > max(media 1h + 2σ, 2%)"
    condition_prometheus_query_language {
      query               = "(${local.err["2m"]}) > clamp_min(${local.err_baseline_2sigma}, 0.02)"
      duration            = "60s"
      evaluation_interval = "30s"
    }
  }
  documentation {
    content   = local.runbook
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "anomaly_latency" {
  display_name = "[AIOps] Anomalía de latencia p99 (baseline + 2σ)"
  combiner     = "OR"
  user_labels  = { alert_type = "aiops", severity = "warning" }

  conditions {
    display_name = "p99 (2m) > max(media 1h + 2σ, 250 ms)"
    condition_prometheus_query_language {
      query               = "(${local.p99["2m"]}) > clamp_min(${local.p99_baseline_2sigma}, 0.25)"
      duration            = "60s"
      evaluation_interval = "30s"
    }
  }
  documentation {
    content   = local.runbook
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

# ── Regla de correlación: error_rate > baseline + 2σ  Y  latency_p99 > SLO ──
resource "google_monitoring_alert_policy" "correlated" {
  display_name = "[AIOps] CRÍTICA — Error rate anómalo + p99 sobre SLO"
  combiner     = "OR"
  severity     = "CRITICAL"
  user_labels  = { alert_type = "aiops", severity = "critical" }

  conditions {
    display_name = "error rate > media 1h + 2σ  AND  p99 > ${var.slo_latency_threshold_s * 1000} ms"
    condition_prometheus_query_language {
      query               = <<-EOT
        ((${local.err["2m"]}) > clamp_min(${local.err_baseline_2sigma}, 0.01))
        and on (job)
        ((${local.p99["2m"]}) > ${var.slo_latency_threshold_s})
      EOT
      duration            = "30s"
      evaluation_interval = "30s"
    }
  }
  documentation {
    content   = local.runbook
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

# ── SRE: consumo acelerado del error budget (service-a) ────────────────
resource "google_monitoring_alert_policy" "burn_rate" {
  display_name = "[AIOps] Burn rate alto — service-a disponibilidad"
  combiner     = "OR"
  user_labels  = { alert_type = "aiops", severity = "critical" }

  conditions {
    display_name = "burn rate (5 min) > 10x"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.availability["service-a"].id}\", \"300s\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "0s"
    }
  }
  documentation {
    content   = "Burn rate > 10x: al ritmo actual el error budget diario de service-a se agota en < 2.4 h."
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.enricher.id]
  alert_strategy {
    auto_close = "1800s"
  }
}

# ── Notificación final: alerta AIOps ENRIQUECIDA (incluye trace_id) por correo ──
resource "google_monitoring_alert_policy" "enriched_email" {
  display_name = "[AIOps] Alerta enriquecida con trace_id"
  combiner     = "OR"
  user_labels  = { alert_type = "notification" }

  conditions {
    display_name = "alert-enricher emitió una alerta enriquecida"
    condition_matched_log {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"alert-enricher\"",
        "jsonPayload.event=\"alert.enriched\"",
        "jsonPayload.policy_type=\"aiops\"",
      ])
      label_extractors = {
        policy    = "EXTRACT(jsonPayload.policy)"
        service   = "EXTRACT(jsonPayload.service)"
        trace_id  = "EXTRACT(jsonPayload.trace_id)"
        span      = "EXTRACT(jsonPayload.slowest_span)"
        trace_url = "EXTRACT(jsonPayload.trace_url)"
      }
    }
  }
  documentation {
    content   = <<-EOT
      **$${log.extracted_label.policy}** — servicio **$${log.extracted_label.service}**

      - trace_id: `$${log.extracted_label.trace_id}`
      - Span más lento: `$${log.extracted_label.span}`
      - Traza: $${log.extracted_label.trace_url}
    EOT
    mime_type = "text/markdown"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
}
