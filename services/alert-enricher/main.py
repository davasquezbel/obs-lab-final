"""
alert-enricher: webhook de Cloud Monitoring que enriquece cada alerta con evidencia.

Flujo:
  1. Cloud Monitoring envía el incidente (JSON schema 1.2) a POST /alert?token=...
  2. Se identifica el servicio afectado (label `job` de la serie que disparó la alerta).
  3. Se busca en Cloud Logging el request fallido (5xx) o más lento del servicio
     dentro de la ventana del incidente → se obtiene su trace_id.
  4. Se consulta la traza en Cloud Trace para identificar el span más lento / con error.
  5. Se emite un log estructurado `alert.enriched` con trace_id y enlaces directos.
     Una alerta basada en logs lo convierte en notificación por correo (con el trace_id).

Todas las notificaciones recibidas quedan registradas (`alert.received`), lo que
permite contar alertas por tipo de política (estática vs. AIOps) para medir ruido.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import FastAPI, HTTPException, Request

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "obs-lab-final")
NAMESPACE = os.getenv("APP_NAMESPACE", "otel-lab")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
SLOW_MS = float(os.getenv("SLOW_REQUEST_MS", "300"))
# Ventana hacia atrás para buscar el request fallido/lento. Debe cubrir la latencia
# de detección: una alerta puede abrirse minutos después de que terminó el impacto.
LOOKBACK_MIN = int(os.getenv("EVIDENCE_LOOKBACK_MIN", "10"))

app = FastAPI(title="alert-enricher")
_credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])


def log(severity: str, message: str, **fields) -> None:
    """Log estructurado → Cloud Logging (jsonPayload) vía stdout de Cloud Run."""
    print(json.dumps({"severity": severity, "message": message, **fields}, default=str), file=sys.stdout, flush=True)


def _token() -> str:
    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


def _ts(value) -> datetime:
    """started_at / ended_at vienen en epoch seconds."""
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def find_evidence_log(service: str | None, since: datetime) -> dict | None:
    """Request fallido más reciente del servicio; si no hay, el más lento (> SLOW_MS)."""
    base = (f'resource.type="k8s_container" resource.labels.namespace_name="{NAMESPACE}" '
            f'timestamp>="{since.isoformat()}" trace:*')
    if service:
        base += f' jsonPayload.service="{service}"'
    candidates = [
        ("error", base + ' jsonPayload.status_class="5xx"'),
        ("slow", base + f' jsonPayload.message="request completed" jsonPayload.latency_ms>{SLOW_MS}'),
    ]
    for kind, flt in candidates:
        resp = httpx.post(
            "https://logging.googleapis.com/v2/entries:list",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"resourceNames": [f"projects/{PROJECT_ID}"], "filter": flt,
                  "orderBy": "timestamp desc", "pageSize": 1},
            timeout=15,
        )
        resp.raise_for_status()
        entries = resp.json().get("entries", [])
        if entries:
            entry = entries[0]
            entry["_kind"] = kind
            return entry
    return None


def trace_summary(trace_id: str) -> dict:
    """Diagnóstico de la traza (Cloud Trace API v1): dónde se gastó el tiempo y dónde nació el error.

    Cloud Trace indexa las trazas con algunos segundos de retraso; si la traza
    todavía no está disponible se reintenta hasta ~30 s.
    """
    spans = []
    for _ in range(6):
        resp = httpx.get(
            f"https://cloudtrace.googleapis.com/v1/projects/{PROJECT_ID}/traces/{trace_id}",
            headers={"Authorization": f"Bearer {_token()}"}, timeout=15,
        )
        if resp.status_code == 200:
            spans = resp.json().get("spans", [])
            if spans:
                break
        time.sleep(5)
    if not spans:
        return {"spans": 0}

    def ts(value):
        # Cloud Trace entrega nanosegundos; se truncan a microsegundos
        value = value.replace("Z", "+00:00")
        if "." in value:
            head, frac = value.split(".", 1)
            digits = "".join(ch for ch in frac if ch.isdigit())
            value = f"{head}.{digits[:6]}{frac[len(digits):]}"
        return datetime.fromisoformat(value)

    def dur_ms(s):
        return (ts(s["endTime"]) - ts(s["startTime"])).total_seconds() * 1000

    def svc(s):
        return s.get("labels", {}).get("service.name", "?")

    def status(s):
        labels = s.get("labels", {})
        return labels.get("/http/status_code", labels.get("http.status_code", ""))

    by_id = {s["spanId"]: s for s in spans}
    children = {}
    for s in spans:
        children.setdefault(s.get("parentSpanId"), []).append(s)

    # 1) Tiempo de RED por salto: span cliente − span servidor que lo atiende
    hops = []
    for client in (s for s in spans if s.get("kind") == "RPC_CLIENT"):
        for server in children.get(client["spanId"], []):
            if server.get("kind") == "RPC_SERVER":
                hops.append((dur_ms(client) - dur_ms(server), f"{svc(client)} → {svc(server)}", server["name"]))
    net = max(hops, default=None)

    # 2) Tiempo PROPIO de cada operación (duración − hijos directos)
    self_times = [(dur_ms(s) - sum(dur_ms(c) for c in children.get(s["spanId"], [])), s)
                  for s in spans if s.get("kind") != "RPC_CLIENT" or " " in s["name"]]
    own = max(self_times, key=lambda x: x[0], default=None)

    # 3) Origen del error: el span más profundo con 5xx (sin hijos con 5xx)
    err = [s for s in spans if status(s).startswith("5")]
    err_ids = {s["spanId"] for s in err}
    origin = next((s for s in err if not any(c["spanId"] in err_ids for c in children.get(s["spanId"], []))), None)

    if origin is not None:
        diagnosis = f"Origen del error: {origin['name']} en {svc(origin)} (HTTP {status(origin)})"
    elif net and own and net[0] > own[0]:
        diagnosis = f"Latencia en la RED: {net[1]} ({net[0]:.0f} ms fuera de los servicios)"
    elif own:
        diagnosis = f"Latencia dentro de {svc(own[1])}: {own[1]['name']} ({own[0]:.0f} ms propios)"
    else:
        diagnosis = None

    return {
        "spans": len(spans),
        "diagnosis": diagnosis,
        "network_hotspot": net[1] if net else None,
        "network_ms": round(net[0], 1) if net else None,
        "service_hotspot": f"{own[1]['name']} ({svc(own[1])})" if own else None,
        "service_self_ms": round(own[0], 1) if own else None,
        "error_origin": f"{origin['name']} ({svc(origin)})" if origin is not None else None,
        "error_spans": [f"{s['name']} ({svc(s)})" for s in err][:6],
        # compatibilidad con la alerta por correo (label slowest_span)
        "slowest_span": diagnosis,
        "slowest_span_ms": round(net[0], 1) if net and diagnosis and "RED" in diagnosis else (round(own[0], 1) if own else None),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/alert")
async def alert(request: Request, token: str = ""):
    if not WEBHOOK_TOKEN or token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")
    received_at = datetime.now(timezone.utc)
    body = await request.json()
    inc = body.get("incident", {})

    policy = inc.get("policy_name", "")
    user_labels = inc.get("policy_user_labels") or {}
    policy_type = user_labels.get("alert_type") or ("static" if "ESTÁTICA" in policy.upper() else "aiops")
    metric_labels = (inc.get("metric") or {}).get("labels") or {}
    resource_labels = (inc.get("resource") or {}).get("labels") or {}
    service = (metric_labels.get("job") or metric_labels.get("destination_service_name")
               or resource_labels.get("job") or user_labels.get("service"))
    started_at = _ts(inc.get("started_at"))

    common = {
        "incident_id": inc.get("incident_id"),
        "policy": policy,
        "policy_type": policy_type,
        "severity_label": user_labels.get("severity", inc.get("severity", "")),
        "condition": inc.get("condition_name"),
        "state": inc.get("state"),
        "service": service,
        "started_at": started_at.isoformat(),
        "received_at": received_at.isoformat(),
        "notification_delay_s": round((received_at - started_at).total_seconds(), 1),
        "incident_url": inc.get("url"),
    }
    log("INFO", f"Alerta recibida: {policy} [{inc.get('state')}] servicio={service}",
        event="alert.received", **common)

    if inc.get("state") != "open":
        return {"status": "recorded"}

    t0 = time.perf_counter()
    entry = find_evidence_log(service, started_at - timedelta(minutes=LOOKBACK_MIN))
    if not entry:
        log("WARNING", f"Sin evidencia de traza para {policy}", event="alert.enriched",
            trace_id=None, **common)
        return {"status": "enriched", "trace_id": None}

    trace_id = entry.get("trace", "").split("/")[-1]
    payload = entry.get("jsonPayload", {})
    summary = trace_summary(trace_id)
    enriched = {
        **common,
        "trace_id": trace_id,
        "evidence_kind": entry["_kind"],          # error | slow
        "evidence_route": payload.get("http_route"),
        "evidence_status": payload.get("http_status_code"),
        "evidence_latency_ms": payload.get("latency_ms"),
        "evidence_service": payload.get("service"),
        "trace_url": f"https://console.cloud.google.com/traces/list?project={PROJECT_ID}&tid={trace_id}",
        "logs_url": ("https://console.cloud.google.com/logs/query;query="
                     f"trace%3D%22projects%2F{PROJECT_ID}%2Ftraces%2F{trace_id}%22?project={PROJECT_ID}"),
        "enrichment_ms": round((time.perf_counter() - t0) * 1000, 1),
        **summary,
    }
    log("ALERT",
        f"Alerta enriquecida: {policy} | servicio={service} | trace_id={trace_id} | "
        f"diagnóstico={summary.get('diagnosis')}",
        event="alert.enriched", **enriched)
    return {"status": "enriched", "trace_id": trace_id}
