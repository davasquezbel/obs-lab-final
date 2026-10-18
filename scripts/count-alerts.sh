#!/usr/bin/env bash
# Cuenta las alertas REALES que Cloud Monitoring entregó al webhook alert-enricher
# en una ventana, agrupadas por política, y lista las alertas enriquecidas (trace_id).
# Uso: scripts/count-alerts.sh <inicio ISO8601> <fin ISO8601>
set -euo pipefail
START=$1; END=$2
BASE="resource.type=\"cloud_run_revision\" resource.labels.service_name=\"alert-enricher\" timestamp>=\"$START\" timestamp<=\"$END\""

echo "══ Alertas abiertas recibidas por el webhook ($START → $END) ══"
gcloud logging read "$BASE jsonPayload.event=\"alert.received\" jsonPayload.state=\"open\"" \
  --limit=1000 --format="value(jsonPayload.policy_type,jsonPayload.policy,jsonPayload.service)" \
  | sort | uniq -c | sort -k2,2 -k1,1nr \
  | awk '{n=$1; $1=""; printf "  %4d %s\n", n, $0}'

echo; echo "Totales por tipo:"
gcloud logging read "$BASE jsonPayload.event=\"alert.received\" jsonPayload.state=\"open\"" \
  --limit=1000 --format="value(jsonPayload.policy_type)" | sort | uniq -c | awk '{printf "  %-7s %d\n", $2, $1}'

echo; echo "══ Alertas AIOps enriquecidas (con trace_id) ══"
gcloud logging read "$BASE jsonPayload.event=\"alert.enriched\" jsonPayload.policy_type=\"aiops\"" --limit=50 \
  --format="table(timestamp.date('%H:%M:%S'),jsonPayload.policy,jsonPayload.service,jsonPayload.notification_delay_s,jsonPayload.trace_id,jsonPayload.slowest_span,jsonPayload.slowest_span_ms)"
