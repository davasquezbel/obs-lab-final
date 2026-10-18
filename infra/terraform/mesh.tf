# ── Cloud Service Mesh gestionado (Módulo A: observabilidad de red L7) ──
# Control plane y data plane (sidecars Envoy) administrados por Google.
# Telemetría L7 nativa: métricas istio.io/service/* en Cloud Monitoring y topología.
resource "google_gke_hub_feature" "mesh" {
  name       = "servicemesh"
  location   = "global"
  depends_on = [google_project_service.apis]
}

resource "google_gke_hub_feature_membership" "mesh" {
  feature  = google_gke_hub_feature.mesh.name
  location = "global"
  # El registro vía bloque fleet{} crea la membresía con el nombre del cluster en su región
  membership          = google_container_cluster.gke.name
  membership_location = var.region

  mesh {
    management = "MANAGEMENT_AUTOMATIC"
  }

  depends_on = [google_container_cluster.gke]
}
