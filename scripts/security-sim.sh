#!/usr/bin/env bash
# Simulación controlada de ataques (Módulo C). Solo contra recursos propios del laboratorio.
#
#  1. Fuerza bruta N-S: POST /login con credenciales inválidas desde este equipo, por Internet,
#     a través del ingress gateway (atribución por IP en VPC Flow Logs).
#  2. Movimiento lateral E-W: pod no autorizado (namespace default, sin mesh) en un nodo distinto
#     escanea puertos de data-service y service-b → NetworkPolicy lo bloquea (log eBPF) y
#     VPC Flow Logs registra los intentos entre nodos.
set -euo pipefail
NS=otel-lab
GW=$(kubectl -n istio-gateway get svc istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
BF_SECONDS=${BF_SECONDS:-150}
BF_RPS=${BF_RPS:-6}

MODE=${1:-all}   # all | bruteforce | scan
say() { echo "$(date -u +%FT%TZ) $*"; }

# ── 1. Fuerza bruta ───────────────────────────────────────────────────
if [ "$MODE" != scan ]; then
say "ATAQUE 1 inicio: fuerza bruta contra http://$GW/login (${BF_RPS} req/s durante ${BF_SECONDS}s)"
end=$(( $(date +%s) + BF_SECONDS )); n=0
while [ "$(date +%s)" -lt "$end" ]; do
  for _ in $(seq 1 "$BF_RPS"); do
    curl -s -m 3 -o /dev/null -X POST "http://$GW/login" \
      -H 'Content-Type: application/json' \
      -d "{\"username\":\"admin$((RANDOM % 50))\",\"password\":\"Pass$RANDOM\"}" &
    n=$((n + 1))
  done
  wait
  sleep 1
done
say "ATAQUE 1 fin: $n intentos enviados"
[ "$MODE" = all ] && sleep 30
fi
[ "$MODE" = bruteforce ] && exit 0

# ── 2. Movimiento lateral / escaneo de puertos ───────────────────────
DS_POD=$(kubectl -n $NS get pod -l app=data-service -o jsonpath='{.items[0].metadata.name}')
DS_NODE=$(kubectl -n $NS get pod "$DS_POD" -o jsonpath='{.spec.nodeName}')
OTHER_NODE=$(kubectl get nodes -o name | sed 's#node/##' | grep -v "$DS_NODE" | head -1)
TARGETS=$(kubectl -n $NS get pod -l 'app in (data-service,service-b)' -o jsonpath='{range .items[*]}{.status.podIP}{" "}{end}')
PORTS="22 80 443 3306 5432 6379 8000 8001 8002 8080 9090 15000 15020"
say "ATAQUE 2 inicio: escaneo desde default/port-scanner (nodo $OTHER_NODE) → $TARGETS puertos [$PORTS]"
kubectl run port-scanner -n default --rm -i --restart=Never --image=busybox:1.36 \
  --labels=app=port-scanner --overrides="{\"spec\":{\"nodeName\":\"$OTHER_NODE\"}}" -- \
  sh -c "for ip in $TARGETS; do for p in $PORTS; do nc -z -w 1 \$ip \$p && echo \"\$ip:\$p ABIERTO\"; done; done; echo escaneo terminado" \
  2>/dev/null | grep -v "^If you don't see" || true
say "ATAQUE 2 fin"
