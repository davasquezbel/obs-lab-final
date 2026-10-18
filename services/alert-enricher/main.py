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
    """Span más lento y spans con error de la traza (Cloud Trace API v1).

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

    def dur_ms(s):
        start = datetime.fromisoformat(s["startTime"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(s["endTime"].replace("Z", "+00:00"))
        return (end - start).total_seconds() * 1000

    # Se descartan los spans de cliente HTTP genéricos ("GET", "POST"): su duración
    # ya está contenida en el span de servidor del servicio llamado
    named = [s for s in spans if " " in s["name"] or "." in s["name"]]
    child_ids = {s.get("parentSpanId") for s in named}
    # El span con nombre más profundo y lento indica dónde se gastó el tiempo
    leaves = [s for s in named if s["spanId"] not in child_ids] or named or spans
    slowest = max(leaves, key=dur_ms) if leaves else None
    errors = [s["name"] for s in spans
              if s.get("labels", {}).get("/http/status_code", s.get("labels", {}).get("http.status_code", "")).startswith("5")]
    return {
        "spans": len(spans),
        "slowest_span": slowest["name"] if slowest else None,
        "slowest_span_ms": round(dur_ms(slowest), 1) if slowest else None,
        "error_spans": errors[:5],
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
               or resource_labels.get("job") or resource_labels.get("service_name"))
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

    # Ventana de búsqueda: desde 2 min antes del inicio del incidente
    t0 = time.perf_counter()
    entry = find_evidence_log(service, started_at - timedelta(minutes=2))
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
        f"span más lento={summary.get('slowest_span')} ({summary.get('slowest_span_ms')} ms)",
        event="alert.enriched", **enriched)
    return {"status": "enriched", "trace_id": trace_id}
