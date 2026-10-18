"""
aiops-detector: motor de detección de anomalías en tiempo real.

Motivación: las políticas PromQL de Cloud Monitoring agregan ~2–3 min de latencia
de evaluación (MTTD real 158–277 s), por encima del objetivo de 120 s. Este detector
consulta Managed Service for Prometheus cada EVAL_INTERVAL_S (datos con 3–7 s de
antigüedad) y aplica la misma lógica AIOps:

  - Anomalía de error rate:  err(1m)  > max(μ₁ₕ + 2σ₁ₕ, 2 %)       (warning)
  - Anomalía de latencia:    p99(1m)  > max(μ₁ₕ + 2σ₁ₕ, 250 ms)    (warning)
  - Correlación (CRÍTICA):   err(1m)  > max(μ₁ₕ + 2σ₁ₕ, 1 %)  AND  p99(1m) > SLO (300 ms)

Una alerta abre cuando la condición se mantiene FOR_S segundos (filtra blips) y se
resuelve tras RESOLVE_S segundos sin cumplirse. Las alertas se entregan al webhook
alert-enricher con el mismo esquema de incidente de Cloud Monitoring, de modo que
reciben el mismo enriquecimiento (trace_id, span más lento, correo).
"""

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field

import google.auth
import google.auth.transport.requests
import httpx

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "obs-lab-final")
NS = os.getenv("APP_NAMESPACE", "otel-lab")
ENRICHER_URL = os.getenv("ENRICHER_URL", "")          # https://.../alert?token=...
EVAL_INTERVAL_S = int(os.getenv("EVAL_INTERVAL_S", "15"))
FOR_S = int(os.getenv("FOR_S", "45"))
RESOLVE_S = int(os.getenv("RESOLVE_S", "60"))
SLO_LATENCY_S = float(os.getenv("SLO_LATENCY_S", "0.3"))
WINDOW = os.getenv("RATE_WINDOW", "1m")

PROM_URL = f"https://monitoring.googleapis.com/v1/projects/{PROJECT}/location/global/prometheus/api/v1/query"
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/monitoring.read"])

ERR = (f'((sum by (job) (rate(http_server_requests_total{{namespace="{NS}",status_class="5xx"}}[{WINDOW}])) '
       f'or 0 * sum by (job) (rate(http_server_requests_total{{namespace="{NS}"}}[{WINDOW}]))) '
       f'/ sum by (job) (rate(http_server_requests_total{{namespace="{NS}"}}[{WINDOW}])))')
P99 = (f'histogram_quantile(0.99, sum by (job, le) '
       f'(rate(http_server_request_duration_seconds_bucket{{namespace="{NS}"}}[{WINDOW}])))')

QUERIES = {
    "err": ERR,
    "err_mu": f"avg_over_time({ERR}[1h:1m])",
    "err_sigma": f"stddev_over_time({ERR}[1h:1m])",
    "p99": P99,
    "p99_mu": f"avg_over_time({P99}[1h:1m])",
    "p99_sigma": f"stddev_over_time({P99}[1h:1m])",
}

RULES = {
    "error_anomaly": ("[AIOps-RT] Anomalía de error rate (baseline + 2σ)", "warning"),
    "latency_anomaly": ("[AIOps-RT] Anomalía de latencia p99 (baseline + 2σ)", "warning"),
    "correlated": ("[AIOps-RT] CRÍTICA — Error rate anómalo + p99 sobre SLO", "critical"),
}


def log(severity, message, **fields):
    print(json.dumps({"severity": severity, "message": message, **fields}, default=str), flush=True)


def token():
    if not _creds.valid:
        _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def query(client, q) -> dict[str, float]:
    r = client.get(PROM_URL, params={"query": q}, headers={"Authorization": f"Bearer {token()}"})
    r.raise_for_status()
    out = {}
    for s in r.json()["data"]["result"]:
        v = float(s["value"][1])
        if v == v:  # descarta NaN (sin tráfico en la ventana)
            out[s["metric"].get("job", "?")] = v
    return out


def evaluate(m: dict[str, dict[str, float]]) -> dict[tuple[str, str], tuple[bool, dict]]:
    """Condición de cada regla por servicio, con los valores usados (para trazabilidad)."""
    result = {}
    for job in m["err"].keys() | m["p99"].keys():
        err, p99 = m["err"].get(job), m["p99"].get(job)
        err_thr = m["err_mu"].get(job, 0) + 2 * m["err_sigma"].get(job, 0)
        p99_thr = m["p99_mu"].get(job, 0) + 2 * m["p99_sigma"].get(job, 0)
        sig_e = m["err_sigma"].get(job, 0)
        sig_p = m["p99_sigma"].get(job, 0)
        values = {
            "err": err, "err_threshold_2sigma": err_thr,
            "err_zscore": (err - m["err_mu"].get(job, 0)) / sig_e if err is not None and sig_e > 0 else None,
            "p99_s": p99, "p99_threshold_2sigma": p99_thr,
            "p99_zscore": (p99 - m["p99_mu"].get(job, 0)) / sig_p if p99 is not None and sig_p > 0 else None,
        }
        err_anom = err is not None and err > max(err_thr, 0.02)
        lat_anom = p99 is not None and p99 > max(p99_thr, 0.25)
        corr = (err is not None and err > max(err_thr, 0.01)
                and p99 is not None and p99 > SLO_LATENCY_S)
        result[("error_anomaly", job)] = (err_anom, values)
        result[("latency_anomaly", job)] = (lat_anom, values)
        result[("correlated", job)] = (corr, values)
    return result


@dataclass
class AlertState:
    true_since: float | None = None
    false_since: float | None = None
    firing: bool = False
    incident_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    opened_at: float | None = None


def notify(client, rule, job, st: AlertState, state: str, values: dict):
    name, severity = RULES[rule]
    incident = {"incident": {
        "incident_id": st.incident_id,
        "policy_name": name,
        "policy_user_labels": {"alert_type": "aiops-rt", "severity": severity, "engine": "aiops-detector"},
        "condition_name": rule,
        "state": state,
        "started_at": int(st.true_since or time.time()),
        "metric": {"labels": {"job": job}},
        "summary": json.dumps(values),
    }}
    log("ALERT" if state == "open" else "INFO",
        f"{name} [{state}] servicio={job}", event=f"detector.{state}", rule=rule, service=job,
        severity_label=severity, incident_id=st.incident_id,
        condition_true_since=st.true_since, **values)
    if ENRICHER_URL:
        try:
            client.post(ENRICHER_URL, json=incident, timeout=10)
        except httpx.HTTPError as e:
            log("ERROR", "No se pudo notificar al enriquecedor", error=str(e))


def main():
    log("INFO", "aiops-detector iniciado", eval_interval_s=EVAL_INTERVAL_S, for_s=FOR_S,
        resolve_s=RESOLVE_S, window=WINDOW, slo_latency_s=SLO_LATENCY_S)
    states: dict[tuple[str, str], AlertState] = {}
    last_heartbeat = 0.0
    with httpx.Client(timeout=30) as client:
        while True:
            t0 = time.time()
            try:
                metrics = {k: query(client, q) for k, q in QUERIES.items()}
                results = evaluate(metrics)
                for key, (cond, values) in results.items():
                    st = states.setdefault(key, AlertState())
                    if cond:
                        st.false_since = None
                        st.true_since = st.true_since or t0
                        if not st.firing and t0 - st.true_since >= FOR_S:
                            st.firing, st.opened_at = True, t0
                            notify(client, *key, st, "open", values)
                    else:
                        st.true_since = None
                        if st.firing:
                            st.false_since = st.false_since or t0
                            if t0 - st.false_since >= RESOLVE_S:
                                notify(client, *key, st, "closed", values)
                                states[key] = AlertState()
                if t0 - last_heartbeat >= 60:
                    last_heartbeat = t0
                    log("INFO", "detector heartbeat", event="detector.heartbeat",
                        eval_ms=round((time.time() - t0) * 1000),
                        services={job: {k: (round(v, 4) if isinstance(v, float) else v)
                                        for k, v in vals.items()}
                                  for (rule, job), (_, vals) in results.items() if rule == "correlated"})
            except Exception as e:  # el detector nunca debe morir por un error transitorio
                log("ERROR", "Error en el ciclo de evaluación", error=repr(e))
            time.sleep(max(1.0, EVAL_INTERVAL_S - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
