# Cloud SQL PostgreSQL para data-service (Módulo A)
resource "google_sql_database_instance" "postgres" {
  name                = "obs-lab-pg"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = false

  settings {
    edition           = "ENTERPRISE" # requerido para usar tier shared-core
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_size         = 10
    disk_type         = "PD_SSD"

    # Sin redes autorizadas: el acceso es solo vía Cloud SQL Auth Proxy + IAM
    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    # Observabilidad de la BD: Query Insights
    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = true
    }

    database_flags {
      name  = "log_min_duration_statement"
      value = "200"
    }

    backup_configuration {
      enabled = false
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "appdb" {
  name     = "appdb"
  instance = google_sql_database_instance.postgres.name
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "google_sql_user" "app" {
  name     = "app"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db.result
}
