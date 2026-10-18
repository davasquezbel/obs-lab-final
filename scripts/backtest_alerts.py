#!/usr/bin/env python3
"""
Backtest de reglas de alerta sobre métricas reales (Managed Service for Prometheus).

Re-evalúa, cada 30 s y con la misma semántica que Cloud Monitoring (duración `for`),
las reglas estáticas y las reglas AIOps definidas en infra/terraform/alerts.tf, y
cuenta los episodios de alerta (una alerta = flanco de subida por servicio).
Clasifica cada episodio como verdadero positivo (se solapa con el incidente real)
o ruido, y calcula la reducción de alertas ruidosas.

Uso:
  python3 scripts/backtest_alerts.py --start 2026-10-18T01:00:00Z --end 2026-10-18T01:40:00Z \
      --incident-start 2026-10-18T01:28:00Z --incident-end 2026-10-18T01:33:00Z [--csv out.csv]
"""
import argparse
import csv
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PROJECT = "obs-lab-final"
NS = "otel-lab"
STEP_S = 30
# Margen alrededor del incidente: propagación del mesh (~2 min) + ventanas de rate
INCIDENT_MARGIN = timedelta(minutes=4)


def err(w):
    return (f'((sum by (job) (rate(http_server_requests_total{{namespace="{NS}",status_class="5xx"}}[{w}])) '
            f'or 0 * sum by (job) (rate(http_server_requests_total{{namespace="{NS}"}}[{w}]))) '
            f'/ sum by (job) (rate(http_server_requests_total{{namespace="{NS}"}}[{w}])))')


def p99(w):
    return (f'histogram_quantile(0.99, sum by (job, le) '
            f'(rate(http_server_request_duration_seconds_bucket{{namespace="{NS}"}}[{w}])))')


def baseline(expr):
    return f'(avg_over_time({expr}[1h:1m]) + 2 * stddev_over_time({expr}[1h:1m]))'


# (nombre, tipo, PromQL idéntica a la política, duración "for" en segundos)
RULES = [
    ("[ESTÁTICA] Error rate > 1%", "static", f"{err('1m')} > 0.01", 0),
    ("[ESTÁTICA] Latencia p99 > 200 ms", "static", f"{p99('1m')} > 0.2", 0),
    ("[AIOps] Anomalía error rate (2σ)", "aiops",
     f"{err('2m')} > clamp_min({baseline(err('2m'))}, 0.02)", 60),
    ("[AIOps] Anomalía latencia p99 (2σ)", "aiops",
     f"{p99('2m')} > clamp_min({baseline(p99('2m'))}, 0.25)", 60),
    ("[AIOps] CRÍTICA correlacionada", "aiops",
     f"({err('2m')} > clamp_min({baseline(err('2m'))}, 0.01)) and on (job) ({p99('2m')} > 0.3)", 30),
]


def token():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()


def query_range(q, start, end, tok):
    url = (f"https://monitoring.googleapis.com/v1/projects/{PROJECT}/location/global/prometheus/api/v1/query_range?"
           + urllib.parse.urlencode({"query": q, "start": start.timestamp(), "end": end.timestamp(), "step": STEP_S}))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    if data.get("status") != "success":
        raise RuntimeError(data)
    return data["data"]["result"]


def episodes(series, for_s):
    """Episodios de alerta: tramos continuos (sin huecos > STEP) que duran ≥ for_s."""
    times = sorted(int(float(t)) for t, _ in series["values"])
    eps, run = [], []
    for t in times:
        if run and t - run[-1] > STEP_S:
            eps.append(run)
            run = []
        run.append(t)
    if run:
        eps.append(run)
    # La alerta se abre cuando la condición se mantiene durante `for`
    return [(r[0] + for_s, r[-1]) for r in eps if r[-1] - r[0] >= for_s]


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--incident-start", required=True)
    ap.add_argument("--incident-end", required=True)
    ap.add_argument("--csv")
    a = ap.parse_args()
    start, end = parse(a.start), parse(a.end)
    inc_s, inc_e = parse(a.incident_start) - timedelta(minutes=1), parse(a.incident_end) + INCIDENT_MARGIN

    tok = token()
    rows = []
    for name, kind, q, for_s in RULES:
        for s in query_range(q, start, end, tok):
            job = s["metric"].get("job", "?")
            for t_open, t_close in episodes(s, for_s):
                opened = datetime.fromtimestamp(t_open, tz=timezone.utc)
                closed = datetime.fromtimestamp(t_close, tz=timezone.utc)
                tp = opened <= inc_e and closed >= inc_s
                rows.append({"regla": name, "tipo": kind, "servicio": job,
                             "abre": opened.strftime("%H:%M:%S"), "cierra": closed.strftime("%H:%M:%S"),
                             "clasificacion": "verdadero positivo" if tp else "RUIDO",
                             "mttd_s": round((opened - parse(a.incident_start)).total_seconds()) if tp else ""})

    rows.sort(key=lambda r: (r["tipo"], r["abre"]))
    print(f"\nVentana {a.start} → {a.end} | incidente real {a.incident_start} → {a.incident_end}\n")
    print(f"{'tipo':<7} {'regla':<36} {'servicio':<13} {'abre':<9} {'cierra':<9} {'clasificación':<19} MTTD(s)")
    for r in rows:
        print(f"{r['tipo']:<7} {r['regla']:<36} {r['servicio']:<13} {r['abre']:<9} {r['cierra']:<9} "
              f"{r['clasificacion']:<19} {r['mttd_s']}")

    def stats(kind):
        sel = [r for r in rows if r["tipo"] == kind]
        noise = sum(r["clasificacion"] == "RUIDO" for r in sel)
        return len(sel), noise, len(sel) - noise

    st, sn, stp = stats("static")
    at, an, atp = stats("aiops")
    print("\nResumen")
    print(f"  Estáticas: {st} alertas | {sn} ruido | {stp} verdaderos positivos | precisión {stp / st:.0%}" if st else "  Estáticas: 0 alertas")
    print(f"  AIOps:     {at} alertas | {an} ruido | {atp} verdaderos positivos | precisión {atp / at:.0%}" if at else "  AIOps: 0 alertas")
    if sn:
        print(f"  Reducción de alertas ruidosas: {1 - an / sn:.0%}  ({sn} → {an})")
    if st:
        print(f"  Reducción total de alertas:    {1 - at / st:.0%}  ({st} → {at})")

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["regla"])
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV: {a.csv}")


if __name__ == "__main__":
    sys.exit(main())
