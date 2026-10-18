# ── alert-enricher: webhook en Cloud Run que agrega trace_id a cada alerta ──
resource "google_service_account" "enricher" {
  account_id   = "alert-enricher"
  display_name = "alert-enricher - obs-lab"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "enricher" {
  for_each = toset([
    "roles/logging.viewer",  # buscar el request fallido
    "roles/cloudtrace.user", # leer la traza
    "roles/logging.logWriter",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.enricher.email}"
}

resource "google_cloud_run_v2_service" "enricher" {
  name                = "alert-enricher"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.enricher.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/obs-lab/alert-enricher:${var.enricher_image_tag}"
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "APP_NAMESPACE"
        value = var.app_namespace
      }
      env {
        name  = "SLOW_REQUEST_MS"
        value = tostring(var.slo_latency_threshold_s * 1000)
      }
      env {
        name  = "WEBHOOK_TOKEN"
        value = random_password.webhook_token.result
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# Cloud Monitoring invoca el webhook sin identidad de Google: acceso público
# protegido con un token aleatorio en la URL (webhook_tokenauth).
resource "google_cloud_run_v2_service_iam_member" "enricher_public" {
  name     = google_cloud_run_v2_service.enricher.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "enricher_url" {
  value = google_cloud_run_v2_service.enricher.uri
}

output "enricher_webhook_url" {
  description = "URL del webhook con token (la usa aiops-detector)"
  value       = "${google_cloud_run_v2_service.enricher.uri}/alert?token=${random_password.webhook_token.result}"
  sensitive   = true
}
