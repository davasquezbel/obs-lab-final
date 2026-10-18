# Módulo E — Autoevaluación de madurez y roadmap

## Escala de madurez (1–5)

| Nivel | Nombre | Descripción |
|---|---|---|
| 1 | Inicial | Reactivo, sin estándares; la detección depende de usuarios o revisiones manuales. |
| 2 | Gestionado | Capacidades básicas implementadas, configuración manual, cobertura parcial. |
| 3 | Definido | Estandarizado y versionado (IaC), cobertura completa del sistema, procesos documentados. |
| 4 | Cuantificado | Se mide la efectividad con datos (MTTD, precisión de alertas, consumo de budget) y se mejora con base en ellos. |
| 5 | Optimizado | Automatizado y predictivo: remediación automática, mejora continua y validación permanente. |

## Autoevaluación — Observability Foundation Blueprint (8 dominios)

| # | Dominio | Nivel | Evidencia principal | Brecha para el siguiente nivel |
|---|---|---|---|---|
| 1 | **Telemetría: 3 pilares** | **4** | Trazas, métricas RED y logs JSON correlacionados por `trace_id` en los 3 servicios; spans de BD; Query Insights enlazado a trazas (sqlcommenter); verificación automatizada (`verify-pillars.sh`). | Exemplars métricas→trazas; logs vía OTLP; correlación de perfiles (Cloud Profiler). |
| 2 | **Instrumentación OpenTelemetry** | **3** | OTel SDK (manual + auto FastAPI/httpx), DB Semantic Conventions estables, Collector como gateway (memory_limiter, filter, resourcedetection, batch), Resource común. | Auto-instrumentación con OTel Operator, `k8sattributes`, tail sampling, OTLP para logs, telemetría del propio Collector como SLO. |
| 3 | **SRE: SLOs y error budget** | **3** | 5 SLOs request-based (disponibilidad 99.5 %, latencia 99 % < 300 ms), alerta de burn rate, análisis de consumo de budget por experimento, runbooks en las políticas. | Alertas multi-ventana/multi-burn-rate, política de error budget formal (congelamiento de despliegues), postmortems, SLO de latencia en data-service. |
| 4 | **AIOps** | **4** | Baseline dinámico (μ + 2σ), regla de correlación error+latencia, enriquecimiento con `trace_id` y span más lento, detector en tiempo real; **evidencia cuantitativa**: −87 % alertas ruidosas, 0 páginas falsas, MTTD 86 s vs. 308 s de Cloud Monitoring. | Baselines con estacionalidad, deduplicación/agrupación de incidentes, RCA basado en topología del mesh, remediación automática. |
| 5 | **Observabilidad de red** | **3** | VPC Flow Logs con metadatos de pod/workload (E-W/N-S), Cloud NAT logs, Dataplane V2 (eBPF) con logging de denegaciones, métricas L7 de Envoy, topología del mesh, atribución por IP/ciudad/ASN. | Intranode visibility, Network Intelligence Center (latencia/pérdida), observabilidad de egress con política de salida, Flow Analyzer en dashboards. |
| 6 | **Observabilidad de seguridad** | **2** | Microsegmentación + alertas de movimiento lateral (56 s), fuerza bruta (μ + 3σ), CVEs de Artifact Analysis, postura de GKE, chequeos propios estilo Security Health Analytics, dashboard Golden Signals de Seguridad. | SCC no disponible (requiere organización); hallazgos HIGH sin remediar (red default abierta, control plane público, HTTP sin TLS); sin WAF ni detección de amenazas. |
| 7 | **DataOps de observabilidad** | **2** | Pipeline OTel con filtrado de health checks y protección de memoria; métricas basadas en logs como código (Terraform). | Sin política de retención/muestreo, sin export a BigQuery para análisis histórico, sin tablero de costo de telemetría ni SLO del propio pipeline (spans/métricas descartadas). |
| 8 | **Resiliencia: Chaos Engineering** | **3** | 2 experimentos automatizados con hipótesis, blast radius y rollback (Chaos Mesh + falla en proceso), MTTD medido, hallazgo de una falla en cascada real (+100 ms → ~90 % de errores). | Experimentos programados (Schedule/Workflow) y en CI, verificación automática de estado estable, GameDays, corrección de la cascada y re-ejecución como prueba de regresión. |

**Promedio: 3.0 / 5** — nivel *Definido*, con AIOps y Telemetría ya en *Cuantificado*.

```
Telemetría 3 pilares   ████████████████░░░░  4
OpenTelemetry          ████████████░░░░░░░░  3
SRE (SLO / budget)     ████████████░░░░░░░░  3
AIOps                  ████████████████░░░░  4
Red                    ████████████░░░░░░░░  3
Seguridad              ████████░░░░░░░░░░░░  2
DataOps                ████████░░░░░░░░░░░░  2
Resiliencia / Caos     ████████████░░░░░░░░  3
```

## Roadmap de mejora a 3 meses (objetivo: promedio 3.9)

Prioridad: primero cerrar riesgos (seguridad y la falla en cascada descubierta), luego
gobierno de datos y automatización.

### Mes 1 — Cerrar riesgos

| Iniciativa | Dominio | Acciones | KPI / criterio de éxito |
|---|---|---|---|
| **Remediar la postura de seguridad** | Seguridad 2→3 | Eliminar la red `default`; control plane privado o *master authorized networks*; TLS en el gateway (certificado gestionado) y Cloud Armor con rate limiting en `/login`; Cloud SQL con IP privada y backups; actualizar starlette/pip e imagen base distroless. | 0 hallazgos HIGH abiertos; CVEs HIGH con fix = 0; fuerza bruta bloqueada en el borde. |
| **Corregir la falla en cascada** | Resiliencia 3→4 | Deadlines propagados y timeouts en el servidor; pool de conexiones y threadpool dimensionados (*bulkhead*); circuit breaking en DestinationRule; reintentos con presupuesto. | Con +100 ms de red en data-service: error rate < 1 % (hoy ~90 % en service-a). |

### Mes 2 — Gobierno y automatización

| Iniciativa | Dominio | Acciones | KPI |
|---|---|---|---|
| **DataOps de telemetría** | DataOps 2→3 | Tail sampling (100 % errores y lentos, 10 % del resto); exclusiones y retención por tipo de log; sink a BigQuery; dashboard de costo y volumen de telemetría; SLO del pipeline (exportaciones fallidas). | Costo de telemetría/request medido y −30 %; 0 pérdidas de spans de error. |
| **SRE operativo** | SRE 3→4 | Alertas multi-ventana (1 h/5 min y 6 h/30 min); política de error budget escrita y aplicada en el pipeline de despliegue; plantilla de postmortem; SLO de latencia en data-service. | 100 % de incidentes con postmortem; despliegues bloqueados con budget < 0. |
| **Instrumentación OTel 2.0** | OTel 3→4 | OTel Operator (auto-instrumentación), `k8sattributes`, exemplars, logs por OTLP. | 100 % de servicios nuevos instrumentados sin cambios de código. |

### Mes 3 — Validación continua y AIOps avanzado

| Iniciativa | Dominio | Acciones | KPI |
|---|---|---|---|
| **Caos continuo** | Resiliencia 4 | Chaos Mesh Schedule semanal + experimentos en CI con verificación automática de estado estable; GameDay trimestral. | MTTD < 60 s sostenido; 100 % de experimentos con hipótesis validada. |
| **AIOps 2.0** | AIOps 4→5 | Baselines estacionales, agrupación de alertas por incidente, RCA con la topología del mesh, remediación automática (rollback ante alerta crítica correlacionada). | Precisión de alertas > 95 %; MTTR −50 %. |
| **Red** | Red 3→4 | Intranode visibility, Network Intelligence Center, política de egress con alertas de destinos nuevos. | 100 % del tráfico E-W visible; alertas de egress anómalo. |

**Madurez esperada a 3 meses:** Telemetría 4 · OTel 4 · SRE 4 · AIOps 5 · Red 4 · Seguridad 3 · DataOps 3 · Resiliencia 4 → **promedio 3.9**.
