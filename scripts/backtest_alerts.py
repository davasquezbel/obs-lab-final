#!/usr/bin/env python3
"""
Backtest de reglas de alerta sobre métricas reales (Managed Service for Prometheus).

Re-evalúa cada STEP_S segundos, con la misma semántica de las políticas (ventanas,
umbrales y duración `for`), tres motores de alerta sobre EXACTAMENTE los mismos datos:

  static    → umbrales fijos sin correlación (infra/terraform/alerts.tf)
  aiops     → baseline 2σ + correlación, ventanas de 2 min (Cloud Monitoring)
  aiops-rt  → baseline 2σ + correlación, ventanas de 1 min (services/aiops-detector)

Verdad de referencia (ground truth) a partir del IMPACTO OBSERVADO en el punto de entrada
(service-a), no del plan de la prueba:
  - Evento ACCIONABLE: errores > 5 %  Y  p99 > 300 ms a la vez (degradación multiseñal).
  - Todo lo demás (picos de una sola señal que se autorresuelven) es ruido para paginación.

Una alerta es verdadero positivo si abre dentro de [inicio − 60 s, fin + 120 s] de un
evento accionable. "Página" = alerta que despierta a alguien: en el sistema estático todas;
en AIOps solo las CRÍTICAS (las warning van a ticket/dashboard).

Uso:
  python3 scripts/backtest_alerts.py --start 2026-10-18T02:30:00Z --end 2026-10-18T03:03:00Z [--csv out.csv]
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
STEP_S = 15
MATCH_BEFORE = timedelta(seconds=60)
MATCH_AFTER = timedelta(seconds=120)


def err(w):
    return (f'((sum by (job) (rate(http_server_requests_total{{namespace="{NS}",status_class="5xx"}}[{w}])) '
            f'or 0 * sum by (job) (rate(http_server_requests_total{{namespace="{NS}"}}[{w}]))) '
            f'/ sum by (job) (rate(http_server_requests_total{{namespace="{NS}"}}[{w}])))')


def p99(w):
    return (f'histogram_quantile(0.99, sum by (job, le) '
            f'(rate(http_server_request_duration_seconds_bucket{{namespace="{NS}"}}[{w}])))')


def baseline(expr):
    return f'(avg_over_time({expr}[1h:1m]) + 2 * stddev_over_time({expr}[1h:1m]))'


# (nombre, motor, severidad, PromQL idéntica a la política/detector, duración "for" en s)
RULES = [
    ("[ESTÁTICA] Error rate > 1%", "static", "page", f"{err('1m')} > 0.01", 0),
    ("[ESTÁTICA] Latencia p99 > 200 ms", "static", "page", f"{p99('1m')} > 0.2", 0),
    ("[AIOps] Anomalía error rate (2σ)", "aiops", "warning",
     f"{err('2m')} > clamp_min({baseline(err('2m'))}, 0.02)", 60),
    ("[AIOps] Anomalía latencia p99 (2σ)", "aiops", "warning",
     f"{p99('2m')} > clamp_min({baseline(p99('2m'))}, 0.25)", 60),
    ("[AIOps] CRÍTICA correlacionada", "aiops", "critical",
     f"({err('2m')} > clamp_min({baseline(err('2m'))}, 0.01)) and on (job) ({p99('2m')} > 0.3)", 30),
    ("[AIOps-RT] Anomalía error rate (2σ)", "aiops-rt", "warning",
     f"{err('1m')} > clamp_min({baseline(err('1m'))}, 0.02)", 45),
    ("[AIOps-RT] Anomalía latencia p99 (2σ)", "aiops-rt", "warning",
     f"{p99('1m')} > clamp_min({baseline(p99('1m'))}, 0.25)", 45),
    ("[AIOps-RT] CRÍTICA correlacionada", "aiops-rt", "critical",
     f"({err('1m')} > clamp_min({baseline(err('1m'))}, 0.01)) and on (job) ({p99('1m')} > 0.3)", 45),
]

# Impacto observado en el punto de entrada (ventanas de 30 s para no depender de ninguna regla)
IMPACT = (f'({err("30s")} > 0.05) and on (job) ({p99("30s")} > 0.3)').replace(
    'namespace="otel-lab"', 'namespace="otel-lab",job="service-a"')


def token():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()


def query_range(q, start, end, tok):
    url = (f"https://monitoring.googleapis.com/v1/projects/{PROJECT}/location/global/prometheus/api/v1/query_range?"
           + urllib.parse.urlencode({"query": q, "start": start.timestamp(), "end": end.timestamp(), "step": STEP_S}))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.load(r)
    if data.get("status") != "success":
        raise RuntimeError(data)
    return data["data"]["result"]


def runs(series, min_len_s=0, gap_s=STEP_S):
    """Tramos continuos de la serie (sin huecos > gap_s) con duración ≥ min_len_s."""
    times = sorted(int(float(t)) for t, _ in series["values"])
    out, run = [], []
    for t in times:
        if run and t - run[-1] > gap_s:
            out.append(run)
            run = []
        run.append(t)
    if run:
        out.append(run)
    return [(r[0], r[-1]) for r in out if r[-1] - r[0] >= min_len_s]


def ts(t):
    return datetime.fromtimestamp(t, tz=timezone.utc)


def parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--csv")
    a = ap.parse_args()
    start, end = parse(a.start), parse(a.end)
    tok = token()

    # 1. Verdad de referencia: eventos accionables (multiseñal) observados en service-a
    events = []
    for s in query_range(IMPACT, start, end, tok):
        for t0, t1 in runs(s, gap_s=45):
            events.append((ts(t0), ts(t1)))
    events.sort()
    print(f"Ventana {a.start} → {a.end}\n\nEventos ACCIONABLES observados en service-a (errores > 5 % y p99 > 300 ms):")
    for i, (e0, e1) in enumerate(events, 1):
        print(f"  E{i}: {e0:%H:%M:%S} → {e1:%H:%M:%S}  ({(e1 - e0).total_seconds() + STEP_S:.0f} s)")

    # 2. Episodios de alerta por regla y servicio
    rows = []
    for name, engine, sev, q, for_s in RULES:
        for s in query_range(q, start, end, tok):
            job = s["metric"].get("job", "?")
            for t0, t1 in runs(s, min_len_s=for_s):
                opened = ts(t0 + for_s)
                match = next((i for i, (e0, e1) in enumerate(events, 1)
                              if e0 - MATCH_BEFORE <= opened <= e1 + MATCH_AFTER), None)
                rows.append({
                    "motor": engine, "severidad": sev, "regla": name, "servicio": job,
                    "abre": opened.strftime("%H:%M:%S"),
                    "clase": f"VP (E{match})" if match else "ruido",
                    "deteccion_s": round((opened - events[match - 1][0]).total_seconds()) if match else "",
                })
    rows.sort(key=lambda r: (r["motor"], r["abre"]))

    print(f"\n{'motor':<9}{'sev':<9}{'regla':<38}{'servicio':<13}{'abre':<9}{'clase':<10}detección(s)")
    for r in rows:
        print(f"{r['motor']:<9}{r['severidad']:<9}{r['regla']:<38}{r['servicio']:<13}{r['abre']:<9}"
              f"{r['clase']:<10}{r['deteccion_s']}")

    # 3. Resumen por motor
    print(f"\n{'motor':<10}{'alertas':>8}{'ruido':>7}{'VP':>5}{'precisión':>11}{'páginas':>9}{'pág.ruido':>10}"
          f"{'eventos detectados (página)':>30}{'detección mín/med (s)':>24}")
    summary = {}
    for engine in ("static", "aiops", "aiops-rt"):
        sel = [r for r in rows if r["motor"] == engine]
        pages = [r for r in sel if r["severidad"] in ("page", "critical")]
        noise = sum(r["clase"] == "ruido" for r in sel)
        pnoise = sum(r["clase"] == "ruido" for r in pages)
        detected = {r["clase"] for r in pages if r["clase"] != "ruido"}
        det = sorted(r["deteccion_s"] for r in pages if r["deteccion_s"] != "")
        # Detección por evento = primera página que lo cubre
        first = {}
        for r in pages:
            if r["clase"] != "ruido":
                first[r["clase"]] = min(first.get(r["clase"], 10 ** 6), r["deteccion_s"])
        fd = sorted(first.values())
        summary[engine] = (len(sel), noise, len(pages), pnoise)
        prec = (len(sel) - noise) / len(sel) if sel else 0
        print(f"{engine:<10}{len(sel):>8}{noise:>7}{len(sel) - noise:>5}{prec:>10.0%}{len(pages):>9}{pnoise:>10}"
              f"{f'{len(detected)}/{len(events)}':>30}"
              f"{(f'{fd[0]} / {fd[len(fd) // 2]}' if fd else '-'):>24}")

    s, ai, rt = summary["static"], summary["aiops"], summary["aiops-rt"]
    print("\nReducción vs. estático")
    for label, k in (("AIOps (Cloud Monitoring)", ai), ("AIOps-RT (detector)", rt)):
        print(f"  {label:<26} alertas ruidosas {s[1]} → {k[1]} ({1 - k[1] / s[1]:.0%})"
              f" | páginas ruidosas {s[3]} → {k[3]} ({1 - k[3] / s[3]:.0%})" if s[1] and s[3] else "")

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV: {a.csv}")


if __name__ == "__main__":
    sys.exit(main())
