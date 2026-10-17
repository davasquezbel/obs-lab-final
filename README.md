# obs-lab-final — Sistema observable de nivel producción en GCP

Laboratorio integrador de la materia **Observabilidad en Ambientes Productivos**
(Maestría en Arquitectura de Software). Integra los tres pilares con OpenTelemetry, AIOps,
observabilidad de red y seguridad, SRE (SLO / error budget) y Chaos Engineering sobre GKE.

> Basado en los repositorios guía [`mafeopa/oTelLabs`](https://github.com/mafeopa/oTelLabs) y
> [`mafeopa/chaos_k8s`](https://github.com/mafeopa/chaos_k8s). Alcance: **solo GCP**.

## Arquitectura

```
k6 ─► Istio ingress ─► service-a ─► service-b ─► data-service ─(Auth Proxy)─► Cloud SQL PostgreSQL
              (sidecars Envoy: telemetría L7)
OTel SDK ─► OTel Collector ─► Cloud Trace · Managed Prometheus · Cloud Logging
VPC Flow Logs · Cloud NAT logs · Security Command Center ─► Dashboard de seguridad
Cloud Monitoring (SLOs + alertas dinámicas) ─► webhook (enriquece con trace_id)
Chaos Mesh ─► experimentos controlados en namespace sandbox
```

## Estructura

| Carpeta | Contenido |
|---|---|
| `infra/terraform/` | IaC: APIs, VPC + Flow Logs, Cloud NAT, GKE (Dataplane V2, Workload Identity, Managed Prometheus), Cloud SQL, Artifact Registry, IAM |
| `services/` | `service-a`, `service-b`, `data-service` (Python/FastAPI + OTel SDK) |
| `k8s/` | Manifiestos de despliegue (namespace, collector, servicios, mesh) |
| `observability/` | Alertas, SLOs, dashboards de Cloud Monitoring |
| `chaos/` | Experimentos Chaos Mesh |
| `scripts/` | Automatización (build, deploy, tráfico, medición de MTTD) |
| `docs/` | Reporte, evidencias y material de referencia |

## Uso rápido

```bash
cd infra/terraform
terraform init
terraform apply            # ~15-20 min
$(terraform output -raw get_credentials_cmd)
```

Pausar costos sin destruir: `terraform apply -var node_count=0`.
Destruir todo: `terraform destroy`.
