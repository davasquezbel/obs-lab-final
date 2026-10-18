#!/usr/bin/env bash
# Activa Cloud Service Mesh sobre la aplicación ya desplegada (scripts/deploy.sh).
# Requisito: terraform apply con mesh.tf y el control plane gestionado en estado ACTIVE.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NS=otel-lab

echo "▶ Estado del mesh gestionado"
gcloud container fleet mesh describe --format="yaml(membershipStates)"

echo "▶ Inyección automática de sidecars en $NS"
kubectl label namespace $NS istio-injection=enabled --overwrite

echo "▶ Ingress gateway (N-S) y políticas de tráfico / mTLS"
kubectl apply -f "$ROOT/k8s/41-ingress-gateway.yaml"
kubectl -n istio-gateway rollout status deploy/istio-ingressgateway --timeout=300s
kubectl apply -f "$ROOT/k8s/40-mesh.yaml"

echo "▶ Re-despliegue para inyectar Envoy en cada pod"
kubectl apply -f "$ROOT/k8s/10-otel-collector.yaml" -f "$ROOT/k8s/20-services.yaml" -f "$ROOT/k8s/30-loadgen.yaml"
kubectl -n $NS rollout restart deploy
for d in otel-collector data-service service-b service-a loadgen; do
  kubectl -n $NS rollout status deploy/$d --timeout=300s
done

kubectl -n $NS get pods -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[*].ready,INIT/SIDECARS:.spec.initContainers[*].name,CONTAINERS:.spec.containers[*].name'
kubectl -n istio-gateway get svc istio-ingressgateway
