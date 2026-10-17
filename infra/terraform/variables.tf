variable "project_id" {
  description = "ID del proyecto GCP"
  type        = string
}

variable "region" {
  description = "Región principal"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zona del cluster GKE (zonal = sin costo de management fee en el free tier)"
  type        = string
  default     = "us-central1-a"
}

variable "cluster_name" {
  type    = string
  default = "obs-lab-gke"
}

variable "node_count" {
  description = "Nodos del node pool (escalar a 0 para pausar costos)"
  type        = number
  default     = 3
}

variable "node_machine_type" {
  description = "3 x e2-standard-2 = 6 vCPU (límite del free trial: 8 vCPU)"
  type        = string
  default     = "e2-standard-2"
}

variable "app_namespace" {
  description = "Namespace de Kubernetes donde corren los microservicios"
  type        = string
  default     = "otel-lab"
}

variable "flow_logs_sampling" {
  description = "Fracción de flujos muestreados en VPC Flow Logs (0.0 - 1.0)"
  type        = number
  default     = 0.5
}
