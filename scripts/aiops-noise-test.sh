#!/usr/bin/env bash
# Prueba de ruido de alertas (Módulo B) — v2 con fallas instantáneas.
#
# Simula ~33 min de operación:
#   - 7 "blips" transitorios de UNA sola señal (latencia o errores, 30–60 s): ruido típico
#     de producción que se autorresuelve y no requiere acción.
#   - 1 incidente real sostenido (errores + latencia, 5 min) que sí requiere acción.
# Mecanismos: Chaos Mesh NetworkChaos (latencia, kernel) y falla en proceso (errores HTTP).
# Al final: scripts/noise_report.py compara alertas estáticas, AIOps gestionadas y AIOps-RT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/results}"
mkdir -p "$OUT"
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG="$OUT/noise-test-$TS.log"
EVENTS="$OUT/noise-test-$TS.events.csv"
GAP_S=${GAP_S:-150}
INCIDENT_S=${INCIDENT_S:-300}

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
event() { echo "$1,$2,$3,$4" >> "$EVENTS"; }   # tipo,inicio,fin,descripción

net_delay() {  # net_delay <servicio> <latencia_ms> <duración_s> <nombre>
  kubectl apply -f - >/dev/null <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: $4, namespace: otel-lab, labels: {experiment: noise-test}}
spec:
  action: delay
  mode: all
  selector: {namespaces: [otel-lab], labelSelectors: {app: $1}}
  delay: {latency: "${2}ms", jitter: "0ms", correlation: "100"}
  direction: to
  duration: "${3}s"
EOF
}

blip_latency() {  # <servicio> <ms> <duración_s> <n>
  local s; s=$(date -u +%FT%TZ)
  say "BLIP latencia: +${2} ms en $1 durante ${3}s"
  net_delay "$1" "$2" "$3" "blip-$4"
  sleep "$3"; kubectl -n otel-lab delete networkchaos "blip-$4" --ignore-not-found >/dev/null
  event blip "$s" "$(date -u +%FT%TZ)" "latencia +${2}ms $1 ${3}s"
  sleep "$GAP_S"
}

blip_errors() {  # <servicio> <error_rate> <duración_s>
  local s; s=$(date -u +%FT%TZ)
  say "BLIP errores: ${2} en $1 durante ${3}s"
  "$ROOT/scripts/app-fault.sh" "$1" "$2" 0 0 "$3" >>"$LOG"
  sleep "$3"
  event blip "$s" "$(date -u +%FT%TZ)" "errores ${2} $1 ${3}s"
  sleep "$GAP_S"
}

cleanup() {
  kubectl -n otel-lab delete networkchaos -l experiment=noise-test --ignore-not-found >/dev/null 2>&1 || true
  "$ROOT/scripts/app-fault.sh" data-service 0 >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "tipo,inicio,fin,descripcion" > "$EVENTS"
START=$(date -u +%FT%TZ)
say "PRUEBA v2 inicio"
blip_latency service-b    150 45 1
blip_errors  data-service 0.05 45
blip_latency data-service 100 45 2
blip_errors  data-service 0.08 30
blip_latency service-b    200 45 3
blip_errors  data-service 0.04 60
blip_latency service-b    250 40 4

INC_START=$(date -u +%FT%TZ)
say "INCIDENTE REAL: 15% errores + 200 ms de red en data-service durante ${INCIDENT_S}s"
"$ROOT/scripts/app-fault.sh" data-service 0.15 0 0 "$INCIDENT_S" >>"$LOG"
net_delay data-service 200 "$INCIDENT_S" incident-delay
sleep "$INCIDENT_S"
kubectl -n otel-lab delete networkchaos incident-delay --ignore-not-found >/dev/null
INC_END=$(date -u +%FT%TZ)
event incident "$INC_START" "$INC_END" "errores 15% + 200ms data-service"
say "INCIDENTE REAL fin"
sleep 300
END=$(date -u +%FT%TZ)
say "PRUEBA v2 fin"

cat <<EOF | tee -a "$LOG"

Ventana:    $START → $END
Incidente:  $INC_START → $INC_END
Eventos:    $EVENTS

Análisis:
  python3 scripts/noise_report.py --events $EVENTS --end $END
  python3 scripts/backtest_alerts.py --start $START --end $END --incident-start $INC_START --incident-end $INC_END
EOF
