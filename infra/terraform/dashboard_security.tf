# ── Dashboard "Golden Signals de Seguridad" (Módulo C) ────────────────
# Fila 1: identidad / acceso      Fila 2: red E-W y N-S
# Fila 3: microsegmentación y mTLS Fila 4: vulnerabilidades y postura
locals {
  ns_filter = "namespace=\"${var.app_namespace}\""

  sec_tiles = [
    # ─── Fila 1: autenticación ───
    {
      xPos = 0, yPos = 0, width = 16, height = 16,
      widget = {
        title = "Logins fallidos vs. exitosos (req/s)"
        xyChart = {
          dataSets = [{
            plotType        = "LINE"
            timeSeriesQuery = { prometheusQuery = "sum by (auth_result) (rate(auth_attempts_total{${local.ns_filter}}[2m]))" }
          }]
          yAxis = { label = "req/s", scale = "LINEAR" }
        }
      }
    },
    {
      xPos = 16, yPos = 0, width = 16, height = 16,
      widget = {
        title = "% de logins fallidos"
        xyChart = {
          dataSets = [{
            plotType        = "LINE"
            timeSeriesQuery = { prometheusQuery = "100 * sum(rate(auth_attempts_total{${local.ns_filter},auth_result=\"failure\"}[2m])) / sum(rate(auth_attempts_total{${local.ns_filter}}[2m]))" }
          }]
          thresholds = [{ value = 50, label = "fuerza bruta probable" }]
          yAxis      = { label = "%", scale = "LINEAR" }
        }
      }
    },
    {
      xPos = 32, yPos = 0, width = 16, height = 16,
      widget = {
        title = "Conexiones externas al gateway por IP de origen (top 5, VPC Flow Logs)"
        xyChart = {
          dataSets = [{
            plotType = "STACKED_BAR"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"logging.googleapis.com/user/security/flows_gateway_ingress\""
                aggregation = {
                  alignmentPeriod    = "60s"
                  perSeriesAligner   = "ALIGN_SUM"
                  crossSeriesReducer = "REDUCE_SUM"
                  groupByFields      = ["metric.label.src_ip", "metric.label.src_city"]
                }
                pickTimeSeriesFilter = { rankingMethod = "METHOD_SUM", numTimeSeries = 5, direction = "TOP" }
              }
            }
          }]
          yAxis = { label = "flujos/min", scale = "LINEAR" }
        }
      }
    },
    # ─── Fila 2: tráfico de red ───
    {
      xPos = 0, yPos = 16, width = 24, height = 16,
      widget = {
        title = "Tráfico E-W entre workloads (flujos/min, VPC Flow Logs)"
        xyChart = {
          dataSets = [{
            plotType = "STACKED_AREA"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"logging.googleapis.com/user/security/flows_east_west\""
                aggregation = {
                  alignmentPeriod    = "60s"
                  perSeriesAligner   = "ALIGN_SUM"
                  crossSeriesReducer = "REDUCE_SUM"
                  groupByFields      = ["metric.label.src_workload", "metric.label.dest_workload"]
                }
              }
            }
          }]
          yAxis = { label = "flujos/min", scale = "LINEAR" }
        }
      }
    },
    {
      xPos = 24, yPos = 16, width = 24, height = 16,
      widget = {
        title = "Tráfico N-S por dirección (flujos/min, VPC Flow Logs)"
        xyChart = {
          dataSets = [{
            plotType = "STACKED_AREA"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"logging.googleapis.com/user/security/flows_north_south\""
                aggregation = {
                  alignmentPeriod    = "60s"
                  perSeriesAligner   = "ALIGN_SUM"
                  crossSeriesReducer = "REDUCE_SUM"
                  groupByFields      = ["metric.label.direction"]
                }
              }
            }
          }]
          yAxis = { label = "flujos/min", scale = "LINEAR" }
        }
      }
    },
    # ─── Fila 3: microsegmentación y cifrado ───
    {
      xPos = 0, yPos = 32, width = 16, height = 16,
      widget = {
        title = "Conexiones denegadas por NetworkPolicy (eBPF)"
        xyChart = {
          dataSets = [{
            plotType = "STACKED_BAR"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"logging.googleapis.com/user/security/netpol_denied\""
                aggregation = {
                  alignmentPeriod    = "60s"
                  perSeriesAligner   = "ALIGN_SUM"
                  crossSeriesReducer = "REDUCE_SUM"
                  groupByFields      = ["metric.label.src_namespace", "metric.label.dest_workload"]
                }
              }
            }
          }]
          yAxis = { label = "conexiones/min", scale = "LINEAR" }
        }
      }
    },
    {
      xPos = 16, yPos = 32, width = 16, height = 16,
      widget = {
        title = "Flujos desde namespaces no autorizados (VPC Flow Logs)"
        xyChart = {
          dataSets = [{
            plotType = "STACKED_BAR"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"logging.googleapis.com/user/security/flows_unexpected_source\""
                aggregation = {
                  alignmentPeriod    = "60s"
                  perSeriesAligner   = "ALIGN_SUM"
                  crossSeriesReducer = "REDUCE_SUM"
                  groupByFields      = ["metric.label.src_namespace"]
                }
              }
            }
          }]
          yAxis = { label = "flujos/min", scale = "LINEAR" }
        }
      }
    },
    {
      xPos = 32, yPos = 32, width = 16, height = 16,
      widget = {
        title = "% de tráfico E-W cifrado con mTLS (Cloud Service Mesh)"
        xyChart = {
          dataSets = [{
            plotType        = "LINE"
            timeSeriesQuery = { prometheusQuery = "100 * sum(rate(istio_io:service_server_request_count{monitored_resource=\"k8s_container\",destination_service_namespace=\"${var.app_namespace}\",service_authentication_policy=\"MUTUAL_TLS\"}[5m])) / sum(rate(istio_io:service_server_request_count{monitored_resource=\"k8s_container\",destination_service_namespace=\"${var.app_namespace}\"}[5m]))" }
          }]
          thresholds = [{ value = 99, label = "tráfico sin mTLS" }]
          yAxis      = { label = "%", scale = "LINEAR" }
        }
      }
    },
    # ─── Fila 4: vulnerabilidades y postura ───
    {
      xPos = 0, yPos = 48, width = 16, height = 16,
      widget = {
        title = "CVEs activos en imágenes desplegadas, por severidad"
        xyChart = {
          dataSets = [{
            plotType = "STACKED_BAR"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"custom.googleapis.com/security/image_vulnerabilities\" AND metric.label.severity!=\"TOTAL\""
                aggregation = {
                  alignmentPeriod    = "600s"
                  perSeriesAligner   = "ALIGN_MAX"
                  crossSeriesReducer = "REDUCE_SUM"
                  groupByFields      = ["metric.label.severity"]
                }
              }
            }
          }]
          yAxis = { label = "CVEs", scale = "LINEAR" }
        }
      }
    },
    {
      xPos = 16, yPos = 48, width = 8, height = 16,
      widget = {
        title = "CVEs HIGH + CRITICAL"
        scorecard = {
          timeSeriesQuery = {
            timeSeriesFilter = {
              filter = "metric.type=\"custom.googleapis.com/security/image_vulnerabilities\" AND metric.label.severity=one_of(\"HIGH\",\"CRITICAL\")"
              aggregation = {
                alignmentPeriod    = "600s"
                perSeriesAligner   = "ALIGN_MAX"
                crossSeriesReducer = "REDUCE_SUM"
              }
            }
          }
          thresholds = [{ value = 0, color = "RED", direction = "ABOVE" }]
        }
      }
    },
    {
      xPos = 24, yPos = 48, width = 8, height = 16,
      widget = {
        title = "CVEs con corrección disponible"
        scorecard = {
          timeSeriesQuery = {
            timeSeriesFilter = {
              filter = "metric.type=\"custom.googleapis.com/security/image_fixable_vulnerabilities\" AND metric.label.severity=\"TOTAL\""
              aggregation = {
                alignmentPeriod    = "600s"
                perSeriesAligner   = "ALIGN_MAX"
                crossSeriesReducer = "REDUCE_SUM"
              }
            }
          }
        }
      }
    },
    {
      xPos = 32, yPos = 48, width = 16, height = 16,
      widget = {
        title = "Hallazgos de postura (estilo Security Health Analytics), por severidad"
        xyChart = {
          dataSets = [{
            plotType = "STACKED_BAR"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"custom.googleapis.com/security/posture_findings\" AND metric.label.severity!=\"TOTAL\""
                aggregation = {
                  alignmentPeriod    = "600s"
                  perSeriesAligner   = "ALIGN_MAX"
                  crossSeriesReducer = "REDUCE_SUM"
                  groupByFields      = ["metric.label.severity"]
                }
              }
            }
          }]
          yAxis = { label = "findings", scale = "LINEAR" }
        }
      }
    },
  ]
}

resource "google_monitoring_dashboard" "security" {
  dashboard_json = jsonencode({
    displayName  = "Golden Signals de Seguridad — obs-lab"
    mosaicLayout = { columns = 48, tiles = local.sec_tiles }
  })
  depends_on = [
    google_logging_metric.auth_failures,
    google_logging_metric.flows_east_west,
    google_logging_metric.flows_north_south,
    google_logging_metric.netpol_denied,
    google_logging_metric.flows_unexpected_source,
    google_logging_metric.flows_gateway_ingress,
  ]
}

output "security_dashboard_url" {
  value = "https://console.cloud.google.com/monitoring/dashboards/builder/${element(split("/", google_monitoring_dashboard.security.id), 3)}?project=${var.project_id}"
}
