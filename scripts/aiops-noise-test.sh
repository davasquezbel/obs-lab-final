#!/usr/bin/env bash
# Prueba de ruido de alertas (Módulo B).
# Simula ~35 min de operación: 5 "blips" transitorios típicos de producción (ruido)
# y luego 1 incidente real sostenido. Al final compara alertas estáticas vs. AIOps.
#
# Nota: Cloud Service Mesh (Traffic Director) tarda ~2 min en propagar cada cambio
# de VirtualService; el inicio real de cada falla se mide en las métricas.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/results}"
mkdir -p "$OUT"
LOG="$OUT/noise-test-$(date -u +%Y%m%dT%H%M%SZ).log"
BLIP_S=${BLIP_S:-45}        # duración de cada blip
GAP_S=${GAP_S:-240}         # separación entre blips
INCIDENT_S=${INCIDENT_S:-300}

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
fault() { "$ROOT/scripts/fault.sh" "$@" | tee -a "$LOG"; }

blip() {   # blip <descripción> <args de fault.sh...>
  local desc=$1; shift
  say "BLIP inicio: $desc"
  fault "$@"
  sleep "$BLIP_S"
  fault clear "$2"
  say "BLIP fin: $desc"
  sleep "$GAP_S"
}

trap 'fault clear service-b >/dev/null; fault clear data-service >/dev/null' EXIT

START=$(date -u +%FT%TZ)
say "PRUEBA inicio (ventana de ruido)"
blip "latencia 300 ms en 30% de service-b"       delay service-b 30 300
blip "errores 503 en 5% de data-service"         abort data-service 5 503
blip "latencia 400 ms en 20% de data-service"    delay data-service 20 400
blip "errores 503 en 4% de service-b"            abort service-b 4 503
blip "latencia 250 ms en 50% de service-b"       delay service-b 50 250

say "INCIDENTE REAL inicio: 15% errores + 400 ms en 60% de data-service (sostenido ${INCIDENT_S}s)"
INC_START=$(date -u +%FT%TZ)
kubectl -n otel-lab patch virtualservice data-service --type merge -p '{"spec":{"http":[{"fault":{"abort":{"percentage":{"value":15},"httpStatus":503},"delay":{"percentage":{"value":60},"fixedDelay":"400ms"}},"route":[{"destination":{"host":"data-service"}}],"timeout":"3s","retries":{"attempts":2,"perTryTimeout":"1500ms","retryOn":"connect-failure,refused-stream,reset"}}]}}' >/dev/null
sleep "$INCIDENT_S"
fault clear data-service
INC_END=$(date -u +%FT%TZ)
say "INCIDENTE REAL fin"
sleep 300
END=$(date -u +%FT%TZ)
say "PRUEBA fin"

cat <<EOF | tee -a "$LOG"

Ventana total:      $START → $END
Incidente real:     $INC_START → $INC_END  (+ ~2 min de propagación del mesh)

Siguiente paso:
  python3 scripts/backtest_alerts.py --start $START --end $END --incident-start $INC_START --incident-end $INC_END
  scripts/count-alerts.sh $START $END
EOF
