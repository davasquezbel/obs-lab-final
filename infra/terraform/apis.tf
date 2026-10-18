locals {
  services = [
    "compute.googleapis.com",
    "container.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "iam.googleapis.com",
    "secretmanager.googleapis.com",
    "run.googleapis.com",
    "securitycenter.googleapis.com",
    "containersecurity.googleapis.com",
    "containeranalysis.googleapis.com",
    "containerscanning.googleapis.com",
    "gkehub.googleapis.com",
    "mesh.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}
