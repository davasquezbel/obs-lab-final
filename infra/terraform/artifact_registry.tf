resource "google_artifact_registry_repository" "images" {
  repository_id = "obs-lab"
  location      = var.region
  format        = "DOCKER"
  description   = "Imágenes de los microservicios del laboratorio"
  depends_on    = [google_project_service.apis]
}
