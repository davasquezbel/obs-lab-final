#!/usr/bin/env bash
# Inyección de fallas en proceso (common/faults.py) en TODOS los pods de un servicio.
# Uso: scripts/app-fault.sh <servicio> <error_rate 0-1> [latency_ms] [latency_rate 0-1] [duración_s]
#   scripts/app-fault.sh data-service 0.10 0 0 300     → 10 % de errores 500 durante 5 min
#   scripts/app-fault.sh data-service 0                → limpiar
# Se ejecuta con kubectl exec (requiere RBAC sobre el namespace) y el token del contenedor.
set -euo pipefail
NS=otel-lab
SVC=$1; ERR=$2; LAT=${3:-0}; LATR=${4:-0}; DUR=${5:-60}
case "$SVC" in data-service) PORT=8002;; service-b) PORT=8001;; service-a) PORT=8000;; esac
# Solo pods activos (excluye los que están terminando durante un rollout)
PODS=$(kubectl -n $NS get pods -l app="$SVC" -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.deletionTimestamp}{"|"}{.metadata.name}{"\n"}{end}' | awk -F'|' '$1=="" {print $2}')
for pod in $PODS; do
  kubectl -n $NS exec "$pod" -c "$SVC" -- python -c "
import os, json, urllib.request
req = urllib.request.Request('http://127.0.0.1:$PORT/chaos/fault', method='POST',
    data=json.dumps({'error_rate': $ERR, 'latency_ms': $LAT, 'latency_rate': $LATR, 'duration_s': $DUR}).encode(),
    headers={'Content-Type': 'application/json', 'x-chaos-token': os.environ['CHAOS_TOKEN']})
print(urllib.request.urlopen(req, timeout=5).read().decode())" >/dev/null
done
echo "$(date -u +%FT%TZ) app-fault $SVC error_rate=$ERR latency=${LAT}ms@$LATR duración=${DUR}s"
