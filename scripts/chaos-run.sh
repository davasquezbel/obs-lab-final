#!/usr/bin/env bash
# Ejecuta los 2 experimentos de caos del Módulo D y registra la línea de tiempo.
#   Exp. 1: +200 ms de latencia de red en service-b (Chaos Mesh NetworkChaos, 5 min)
#   Exp. 2: 10 % de errores 500 en data-service (falla en proceso, 5 min)
# Después: python3 scripts/chaos_report.py --events <archivo .csv que imprime al final>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/results}"
mkdir -p "$OUT"
TS=$(date -u +%Y%m%dT%H%M%SZ)
EVENTS="$OUT/chaos-$TS.events.csv"
LOG="$OUT/chaos-$TS.log"
DURATION=${DURATION:-300}
RECOVERY=${RECOVERY:-360}
NS=otel-lab

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
cleanup() {
  kubectl -n $NS delete networkchaos -l experiment=chaos-exp-1 --ignore-not-found >/dev/null 2>&1 || true
  "$ROOT/scripts/app-fault.sh" data-service 0 >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "experimento,inicio,fin,descripcion" > "$EVENTS"

say "STEADY STATE: verificando que no haya caos activo ni errores"
kubectl -n $NS get networkchaos 2>/dev/null | tee -a "$LOG" || true
kubectl -n $NS get pods -o wide | tee -a "$LOG"

# ── Experimento 1 ─────────────────────────────────────────────────────
S1=$(date -u +%FT%TZ)
say "EXP 1 inicio: NetworkChaos +200 ms en service-b (${DURATION}s)"
kubectl apply -f "$ROOT/chaos/experiment-1-network-latency.yaml" | tee -a "$LOG"
sleep 20
kubectl -n $NS get networkchaos exp1-latency-service-b -o jsonpath='{.status.conditions}' | tee -a "$LOG"; echo | tee -a "$LOG"
sleep $((DURATION - 20))
E1=$(date -u +%FT%TZ)
kubectl -n $NS delete -f "$ROOT/chaos/experiment-1-network-latency.yaml" --ignore-not-found | tee -a "$LOG"
say "EXP 1 fin"
echo "exp1,$S1,$E1,+200ms red service-b (NetworkChaos)" >> "$EVENTS"
sleep "$RECOVERY"

# ── Experimento 2 ─────────────────────────────────────────────────────
S2=$(date -u +%FT%TZ)
say "EXP 2 inicio: 10% de errores 500 en data-service (${DURATION}s)"
"$ROOT/scripts/app-fault.sh" data-service 0.10 0 0 "$DURATION" | tee -a "$LOG"
sleep "$DURATION"
E2=$(date -u +%FT%TZ)
say "EXP 2 fin (rollback automático por TTL)"
echo "exp2,$S2,$E2,10% errores data-service (falla en proceso)" >> "$EVENTS"
sleep "$RECOVERY"
say "FIN de los experimentos"

cat <<EOF | tee -a "$LOG"

Eventos: $EVENTS
Análisis: python3 scripts/chaos_report.py --events $EVENTS
EOF
