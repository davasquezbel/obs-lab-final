# Experimentos de caos (Módulo D)

Se ejecutan en el proyecto sandbox `obs-lab-final` (nunca en recursos compartidos) con
`scripts/chaos-run.sh`, que aplica cada falla, espera su recuperación y registra la línea
de tiempo para `scripts/chaos_report.py`.

| # | Falla | Mecanismo | Duración | Rollback |
|---|---|---|---|---|
| 1 | +200 ms de latencia de red en **service-b** | Chaos Mesh `NetworkChaos` (tc en el kernel) — `experiment-1-network-latency.yaml` | 5 min | TTL del CRD |
| 2 | **10 % de errores HTTP 500** en **data-service** | Falla en proceso (`services/common/faults.py`) vía `scripts/app-fault.sh` | 5 min | TTL en memoria |

## ¿Por qué el experimento 2 no usa HTTPChaos?
`HTTPChaos` de Chaos Mesh intercepta el tráfico HTTP del puerto del contenedor. Con Cloud
Service Mesh y **mTLS STRICT**, ese tráfico llega cifrado y redirigido por Envoy, por lo que
HTTPChaos queda "inyectado" pero no produce ningún error (verificado en el laboratorio).
Desactivar mTLS para el experimento degradaría la seguridad, así que el error se inyecta
en el propio proceso con un endpoint protegido por token y con duración acotada, lo que
mantiene el mismo modelo de Chaos Mesh: blast radius acotado y rollback automático.

Los manifiestos originales del repositorio guía (`mafeopa/chaos_k8s`) se conservan en
`docs/referencia-chaos_k8s/chaos-mesh/` como referencia.
