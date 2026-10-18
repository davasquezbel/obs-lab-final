#!/usr/bin/env bash
# Verifica Cloud Service Mesh: estado del control plane, sidecars, entrada N-S,
# mTLS STRICT y métricas L7 (Envoy) en Cloud Monitoring.
set -uo pipefail
PROJECT=obs-lab-final
NS=otel-lab

echo "══ Control plane gestionado ══"
gcloud container fleet mesh describe --project $PROJECT --format=json | python3 -c '
import sys, json
for m, v in json.load(sys.stdin).get("membershipStates", {}).items():
    sm = v.get("servicemesh", {})
    print("  membresía:", m.split("/")[-1])
    print("  implementación:", sm.get("controlPlaneManagement", {}).get("implementation"))
    print("  control plane:", sm.get("controlPlaneManagement", {}).get("state"))
    print("  data plane:", sm.get("dataPlaneManagement", {}).get("state"))'

echo; echo "══ Pods con sidecar Envoy ══"
kubectl -n $NS get pods -o 'custom-columns=POD:.metadata.name,READY:.status.containerStatuses[*].ready,CONTENEDORES:.spec.containers[*].name'

echo; echo "══ Entrada N-S por el ingress gateway ══"
IP=$(kubectl -n istio-gateway get svc istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "  Gateway: http://$IP"
curl -s -m 10 -o /dev/null -w "  GET  /order/12 → %{http_code}\n" "http://$IP/order/12"
curl -s -m 10 -o /dev/null -w "  POST /login (clave errada) → %{http_code}\n" -X POST "http://$IP/login" \
  -H 'Content-Type: application/json' -d '{"username":"demo","password":"incorrecta"}'

echo; echo "══ mTLS STRICT: petición en texto plano desde un pod sin sidecar ══"
if kubectl run mtls-probe -n default --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- \
     -s -m 5 -o /dev/null http://service-a.$NS:8000/order/1 >/dev/null 2>&1; then
  echo "  ✗ La petición fue aceptada (mTLS no se está aplicando)"
else
  echo "  ✓ Conexión rechazada: solo se acepta tráfico mTLS entre workloads del mesh"
fi

echo; echo "══ Métricas L7 de Envoy en Cloud Monitoring (PromQL) ══"
TOKEN=$(gcloud auth print-access-token)
promql() {
  echo "  PromQL: $1"
  curl -s -H "Authorization: Bearer $TOKEN" \
    "https://monitoring.googleapis.com/v1/projects/$PROJECT/location/global/prometheus/api/v1/query" \
    --data-urlencode "query=$1" | python3 -c '
import sys, json
for r in json.load(sys.stdin).get("data", {}).get("result", []):
    m = r["metric"]
    labels = " ".join("%s=%s" % (k, v) for k, v in sorted(m.items()))
    print("    %-60s %.3f" % (labels, float(r["value"][1])))'
}
promql 'sum by (destination_service_name, response_code) (rate(istio_io:service_server_request_count{monitored_resource="k8s_container",destination_service_namespace="otel-lab"}[5m]))'
promql 'histogram_quantile(0.99, sum by (destination_service_name, le) (rate(istio_io:service_server_response_latencies_bucket{monitored_resource="k8s_container",destination_service_namespace="otel-lab"}[5m])))'
