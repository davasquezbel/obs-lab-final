#!/usr/bin/env bash
# Inyección de fallas L7 con Cloud Service Mesh (VirtualService.fault).
# Uso:
#   scripts/fault.sh delay <servicio> <porcentaje> <ms>
#   scripts/fault.sh abort <servicio> <porcentaje> [http_status]
#   scripts/fault.sh clear <servicio>
# Restaura siempre la ruta original (timeout + reintentos) definida en k8s/40-mesh.yaml.
set -euo pipefail
NS=otel-lab
action=$1; svc=$2

route='"route":[{"destination":{"host":"'"$svc"'"}}],"timeout":"3s","retries":{"attempts":2,"perTryTimeout":"1500ms","retryOn":"connect-failure,refused-stream,reset"}'

case "$action" in
  delay)
    fault='"fault":{"delay":{"percentage":{"value":'"$3"'},"fixedDelay":"'"$4"'ms"}},' ;;
  abort)
    fault='"fault":{"abort":{"percentage":{"value":'"$3"'},"httpStatus":'"${4:-503}"'}},' ;;
  clear)
    fault='' ;;
  *) echo "acción desconocida: $action" >&2; exit 1 ;;
esac

kubectl -n $NS patch virtualservice "$svc" --type merge -p '{"spec":{"http":[{'"$fault$route"'}]}}' >/dev/null
echo "$(date -u +%FT%TZ) fault $action $svc ${3:-} ${4:-}"
