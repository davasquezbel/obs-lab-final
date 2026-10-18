#!/usr/bin/env bash
# Demostración en vivo (video del laboratorio). Cada sección se detiene hasta presionar Enter,
# para narrar mientras se muestra la consola de GCP en paralelo.
#
#   1. Petición real por el ingress gateway → trace_id
#   2. Los 3 pilares de esa petición (traza, métricas, logs)
#   3. Service mesh: mTLS y métricas L7
#   4. Caos: +200 ms en service-b (Chaos Mesh) → detección AIOps < 2 min con trace_id
#   5. Caos: 10 % de errores en data-service → alerta crítica correlacionada
#   6. Seguridad: movimiento lateral bloqueado por eBPF
#
# Duración aprox.: 12–15 min. Variables: CHAOS_SECONDS (default 150).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NS=otel-lab
CHAOS_SECONDS=${CHAOS_SECONDS:-150}
GW=$(kubectl -n istio-gateway get svc istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

bold() { printf "\n\033[1;36m══ %s ══\033[0m\n" "$*"; }
pause() { printf "\n\033[2m[Enter para continuar]\033[0m"; read -r _; }
alerts_since() {
  gcloud logging read "resource.labels.service_name=\"alert-enricher\" jsonPayload.event=\"alert.received\" jsonPayload.state=\"open\" timestamp>=\"$1\"" \
    --limit=20 --order=asc --format="table(jsonPayload.received_at.date('%H:%M:%S'):label=RECIBIDA,jsonPayload.policy_type:label=MOTOR,jsonPayload.policy:label=POLITICA,jsonPayload.service:label=SERVICIO)"
}
wait_alert() {   # wait_alert <desde ISO> <patrón de política> <timeout s>
  local since=$1 pattern=$2 limit=$3 t0; t0=$(date +%s)
  while [ $(( $(date +%s) - t0 )) -lt "$limit" ]; do
    if gcloud logging read "resource.labels.service_name=\"alert-enricher\" jsonPayload.event=\"alert.received\" jsonPayload.state=\"open\" jsonPayload.policy:\"$pattern\" timestamp>=\"$since\"" --limit=1 --format="value(timestamp)" | grep -q .; then
      echo "→ Alerta \"$pattern\" recibida a los $(( $(date +%s) - $(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$since" +%s) )) s del inicio de la falla"
      return 0
    fi
    printf "."; sleep 10
  done
  echo " (timeout)"
}

bold "0. Estado del sistema"
kubectl -n $NS get pods -o 'custom-columns=POD:.metadata.name,LISTOS:.status.containerStatuses[*].ready,CONTENEDORES:.spec.containers[*].name'
pause

bold "1. Petición real a través del ingress gateway (N-S)"
RESP=$(curl -s "http://$GW/order/42")
echo "$RESP" | python3 -m json.tool
TRACE=$(echo "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["trace_id"])')
echo "trace_id = $TRACE"
echo "Cloud Trace: https://console.cloud.google.com/traces/list?project=obs-lab-final&tid=$TRACE"
pause

bold "2. Los 3 pilares de esa misma petición (esperando 60 s a que se exporte)"
sleep 60
"$ROOT/scripts/verify-pillars.sh" "$TRACE"
pause

bold "3. Service mesh: mTLS STRICT y telemetría L7"
"$ROOT/scripts/verify-mesh.sh"
pause

bold "4. CAOS 1 — +200 ms de latencia de red en service-b (Chaos Mesh, ${CHAOS_SECONDS}s)"
sed "s/duration: \"300s\"/duration: \"${CHAOS_SECONDS}s\"/" "$ROOT/chaos/experiment-1-network-latency.yaml" | kubectl apply -f -
S1=$(date -u +%FT%TZ); echo "Inicio: $S1"
for _ in 1 2 3; do curl -s -o /dev/null -w "  GET /order → %{http_code} en %{time_total}s\n" "http://$GW/order/7"; sleep 2; done
echo "Esperando la detección (objetivo MTTD < 120 s)"
wait_alert "$S1" "AIOps-RT" 180
alerts_since "$S1"
kubectl -n $NS delete networkchaos exp1-latency-service-b --ignore-not-found >/dev/null
echo "Falla retirada (rollback)."
pause

bold "5. CAOS 2 — 10 % de errores en data-service (${CHAOS_SECONDS}s)"
S2=$(date -u +%FT%TZ); echo "Inicio: $S2"
"$ROOT/scripts/app-fault.sh" data-service 0.10 0 0 "$CHAOS_SECONDS"
echo "Esperando la detección (objetivo MTTD < 120 s)"
wait_alert "$S2" "error rate" 180
alerts_since "$S2"
echo
echo "Alerta enriquecida (trace_id del request fallido):"
gcloud logging read "resource.labels.service_name=\"alert-enricher\" jsonPayload.event=\"alert.enriched\" jsonPayload.trace_id:* timestamp>=\"$S2\"" --limit=1 \
  --format="value(jsonPayload.policy,jsonPayload.trace_id,jsonPayload.evidence_status,jsonPayload.slowest_span,jsonPayload.trace_url)"
"$ROOT/scripts/app-fault.sh" data-service 0 >/dev/null
pause

bold "6. Seguridad — movimiento lateral bloqueado por eBPF (Dataplane V2)"
DS=$(kubectl -n $NS get pod -l app=data-service -o jsonpath='{.items[0].status.podIP}')
kubectl run demo-attacker -n default --rm -i --restart=Never --image=busybox:1.36 -- \
  sh -c "for p in 8002 5432 22; do nc -z -w 2 $DS \$p && echo \"puerto \$p ABIERTO\" || echo \"puerto \$p BLOQUEADO\"; done" 2>/dev/null | grep -E "puerto"
sleep 20
gcloud logging read 'logName="projects/obs-lab-final/logs/policy-action" jsonPayload.src.pod_name="demo-attacker"' --freshness=5m --limit=5 \
  --format="table(timestamp.date('%H:%M:%S'),jsonPayload.disposition,jsonPayload.src.pod_namespace,jsonPayload.dest.workload_name,jsonPayload.connection.dest_port)"
bold "Fin de la demostración"
