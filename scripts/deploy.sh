#!/usr/bin/env bash
# Despliega la aplicación observable en GKE.
# Requisitos: terraform apply ejecutado en infra/terraform y kubectl apuntando al cluster.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF="$ROOT/infra/terraform"
NS=otel-lab

echo "▶ Credenciales del cluster"
eval "$(terraform -chdir="$TF" output -raw get_credentials_cmd)"

echo "▶ Namespace, KSAs y configuración"
kubectl apply -f "$ROOT/k8s/00-namespace.yaml"

echo "▶ Secrets (no se versionan)"
DB_PASSWORD="$(terraform -chdir="$TF" output -raw db_password)"
kubectl -n $NS create secret generic db-credentials \
  --from-literal=DB_PASSWORD="$DB_PASSWORD" --dry-run=client -o yaml | kubectl apply -f -

# Usuario de prueba de la app (solo sandbox). Se genera una vez y se reutiliza.
if ! kubectl -n $NS get secret auth-users >/dev/null 2>&1; then
  LOGIN_PASS="$(openssl rand -hex 12)"
  kubectl -n $NS create secret generic auth-users \
    --from-literal=AUTH_USERS="demo:$LOGIN_PASS" \
    --from-literal=LOGIN_USER=demo \
    --from-literal=LOGIN_PASS="$LOGIN_PASS"
fi

echo "▶ OTel Collector, servicios y generador de tráfico"
kubectl apply -f "$ROOT/k8s/10-otel-collector.yaml"
kubectl apply -f "$ROOT/k8s/20-services.yaml"
kubectl apply -f "$ROOT/k8s/30-loadgen.yaml"

kubectl -n $NS rollout status deploy/otel-collector --timeout=180s
for d in data-service service-b service-a loadgen; do
  kubectl -n $NS rollout status deploy/$d --timeout=300s
done
kubectl -n $NS get pods -o wide
