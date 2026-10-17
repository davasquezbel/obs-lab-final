#!/usr/bin/env bash
# Verifica los 3 pilares para una petición real: misma traza en Cloud Trace,
# métricas RED en Managed Prometheus y logs correlacionados en Cloud Logging.
# Uso: scripts/verify-pillars.sh [trace_id]   (sin argumento genera una petición nueva)
set -euo pipefail
PROJECT=obs-lab-final
NS=otel-lab

TRACE_ID="${1:-}"
if [[ -z "$TRACE_ID" ]]; then
  TRACE_ID=$(kubectl -n $NS exec deploy/loadgen -- \
    wget -qO- http://service-a:8000/order/7 | python3 -c 'import sys,json; print(json.load(sys.stdin)["trace_id"])')
  echo "Petición generada → trace_id=$TRACE_ID (esperando 60 s a que se exporte la telemetría)"
  sleep 60
fi
TOKEN=$(gcloud auth print-access-token)

echo; echo "══ PILAR 1 · TRAZA en Cloud Trace ══"
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://cloudtrace.googleapis.com/v1/projects/$PROJECT/traces/$TRACE_ID" | python3 -c '
import sys, json
spans = json.load(sys.stdin).get("spans", [])
keys = ("db.system.name", "db.collection.name", "db.query.text", "http.route")
for s in sorted(spans, key=lambda s: s["startTime"]):
    labels = s.get("labels", {})
    extra = {k: v for k, v in labels.items() if k in keys}
    print("  %-45s %s" % (s["name"], extra))
print(f"  total spans: {len(spans)}")'

echo; echo "══ PILAR 2 · MÉTRICAS en Managed Service for Prometheus ══"
promql() {
  echo "  PromQL: $1"
  curl -s -H "Authorization: Bearer $TOKEN" \
    "https://monitoring.googleapis.com/v1/projects/$PROJECT/location/global/prometheus/api/v1/query" \
    --data-urlencode "query=$1" | python3 -c '
import sys, json
for r in json.load(sys.stdin).get("data", {}).get("result", []):
    m = r["metric"]
    print("    %-14s %-4s %.4f" % (m.get("job", ""), m.get("status_class", ""), float(r["value"][1])))'
}
promql 'sum by (job, status_class) (rate(http_server_requests_total{namespace="otel-lab"}[5m]))'
promql 'histogram_quantile(0.99, sum by (job, le) (rate(http_server_request_duration_seconds_bucket{namespace="otel-lab"}[5m])))'
promql 'histogram_quantile(0.99, sum by (job, le) (rate(db_client_operation_duration_seconds_bucket[5m])))'

echo; echo "══ PILAR 3 · LOGS en Cloud Logging (mismo trace) ══"
gcloud logging read "trace=\"projects/$PROJECT/traces/$TRACE_ID\"" --project $PROJECT \
  --freshness=1h --limit=20 \
  --format="table(timestamp,resource.labels.container_name,severity,jsonPayload.message,jsonPayload.http_route)"
