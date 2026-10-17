output "get_credentials_cmd" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.gke.name} --zone ${var.zone} --project ${var.project_id}"
}

output "image_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "cloudsql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "db_user" {
  value = google_sql_user.app.name
}

output "db_password" {
  value     = random_password.db.result
  sensitive = true
}

output "workload_service_accounts" {
  value = { for k, sa in google_service_account.workload : k => sa.email }
}
