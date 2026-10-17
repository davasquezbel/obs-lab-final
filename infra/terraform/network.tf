# ── VPC dedicada al laboratorio ─────────────────────────────────────
resource "google_compute_network" "vpc" {
  name                    = "obs-lab-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

# Subred de GKE con VPC Flow Logs habilitados (Módulo C)
resource "google_compute_subnetwork" "gke" {
  name                     = "obs-lab-gke-subnet"
  network                  = google_compute_network.vpc.id
  region                   = var.region
  ip_cidr_range            = "10.10.0.0/20"
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/16"
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = var.flow_logs_sampling
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# ── Salida a Internet para nodos privados (tráfico N-S observable) ──
resource "google_compute_router" "router" {
  name    = "obs-lab-router"
  network = google_compute_network.vpc.id
  region  = var.region
}

resource "google_compute_router_nat" "nat" {
  name                               = "obs-lab-nat"
  router                             = google_compute_router.router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ALL"
  }
}
