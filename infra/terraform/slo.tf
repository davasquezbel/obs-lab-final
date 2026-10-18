# ── SRE: servicios y SLOs en Cloud Monitoring (Módulo B / D) ──────────
# SLIs request-based sobre las métricas RED de la aplicación (OTel → Managed Prometheus).
# Ventana de 1 día: suficientemente corta para que un experimento de caos
# consuma una fracción visible del error budget durante el laboratorio.
locals {
  slo_services = ["service-a", "service-b", "data-service"]

  requests_filter = join(" AND ", [
    "metric.type=\"prometheus.googleapis.com/http_server_requests_total/counter\"",
    "resource.type=\"prometheus_target\"",
    "resource.label.\"namespace\"=\"${var.app_namespace}\"",
  ])
  latency_filter = join(" AND ", [
    "metric.type=\"prometheus.googleapis.com/http_server_request_duration_seconds/histogram\"",
    "resource.type=\"prometheus_target\"",
    "resource.label.\"namespace\"=\"${var.app_namespace}\"",
  ])
}

resource "google_monitoring_custom_service" "svc" {
  for_each     = toset(local.slo_services)
  service_id   = "obs-lab-${each.key}"
  display_name = "obs-lab / ${each.key}"
  depends_on   = [google_project_service.apis]
}

# Disponibilidad: 99.5 % de requests sin 5xx
resource "google_monitoring_slo" "availability" {
  for_each            = toset(local.slo_services)
  service             = google_monitoring_custom_service.svc[each.key].service_id
  slo_id              = "availability-99-5"
  display_name        = "${each.key} — Disponibilidad 99.5% (1 día)"
  goal                = 0.995
  rolling_period_days = 1

  request_based_sli {
    good_total_ratio {
      total_service_filter = "${local.requests_filter} AND resource.label.\"job\"=\"${each.key}\""
      bad_service_filter   = "${local.requests_filter} AND resource.label.\"job\"=\"${each.key}\" AND metric.label.\"status_class\"=\"5xx\""
    }
  }
}

# Latencia: 99 % de requests por debajo del umbral (300 ms)
resource "google_monitoring_slo" "latency" {
  for_each            = toset(["service-a", "service-b"])
  service             = google_monitoring_custom_service.svc[each.key].service_id
  slo_id              = "latency-p99-300ms"
  display_name        = "${each.key} — 99% < ${var.slo_latency_threshold_s * 1000} ms (1 día)"
  goal                = 0.99
  rolling_period_days = 1

  request_based_sli {
    distribution_cut {
      distribution_filter = "${local.latency_filter} AND resource.label.\"job\"=\"${each.key}\""
      range {
        max = var.slo_latency_threshold_s
      }
    }
  }
}
