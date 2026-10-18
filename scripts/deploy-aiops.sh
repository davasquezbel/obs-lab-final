#!/usr/bin/env bash
# Despliega el detector AIOps en tiempo real. Requiere terraform apply (alerts.tf, enricher.tf, iam.tf).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF="$ROOT/infra/terraform"
NS=otel-lab

URL="$(terraform -chdir="$TF" output -raw enricher_webhook_url)"
kubectl -n $NS create secret generic aiops-detector \
  --from-literal=ENRICHER_URL="$URL" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$ROOT/k8s/50-aiops-detector.yaml"
kubectl -n $NS rollout status deploy/aiops-detector --timeout=300s
kubectl -n $NS logs deploy/aiops-detector -c aiops-detector --tail=3
