# ── Cuenta de servicio de los nodos GKE (mínimo privilegio) ─────────
resource "google_service_account" "gke_nodes" {
  account_id   = "gke-nodes"
  display_name = "GKE nodes - obs-lab"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "gke_nodes" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/monitoring.viewer",
    "roles/stackdriver.resourceMetadata.writer",
    "roles/artifactregistry.reader",
    "roles/autoscaling.metricsWriter",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

# ── Identidades de workloads (Workload Identity) ────────────────────
locals {
  workload_identities = {
    # KSA name => roles
    "otel-collector" = [
      "roles/cloudtrace.agent",
      "roles/monitoring.metricWriter",
      "roles/logging.logWriter",
    ]
    # Detector AIOps en tiempo real: consulta Managed Prometheus
    "aiops-detector" = [
      "roles/monitoring.viewer",
    ]
    # Exportador de señales de seguridad (SCC + CVEs → Cloud Monitoring)
    "security-exporter" = [
      "roles/securitycenter.findingsViewer",
      "roles/containeranalysis.occurrences.viewer",
      "roles/monitoring.metricWriter",
      # Lectura de configuración para los chequeos de postura
      "roles/iam.securityReviewer",
      "roles/cloudsql.viewer",
      "roles/compute.networkViewer",
      "roles/container.clusterViewer",
      "roles/run.viewer",
    ]
    # El Auth Proxy (sidecar) exporta sus propias trazas y métricas
    "data-service" = [
      "roles/cloudsql.client",
      "roles/cloudtrace.agent",
      "roles/monitoring.metricWriter",
    ]
  }
}

resource "google_service_account" "workload" {
  for_each     = local.workload_identities
  account_id   = each.key
  display_name = "Workload ${each.key} - obs-lab"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "workload" {
  for_each = merge([
    for sa, roles in local.workload_identities : {
      for role in roles : "${sa}|${role}" => { sa = sa, role = role }
    }
  ]...)
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload[each.value.sa].email}"
}

# KSA <namespace>/<name> puede actuar como la GSA del mismo nombre
resource "google_service_account_iam_member" "workload_identity" {
  for_each           = local.workload_identities
  service_account_id = google_service_account.workload[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.app_namespace}/${each.key}]"
  depends_on         = [google_container_cluster.gke]
}
