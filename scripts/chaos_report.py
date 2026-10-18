#!/usr/bin/env python3
"""
Análisis de los experimentos de caos (Módulo D): MTTD, SLO, error budget y accionabilidad.

Para cada experimento del archivo de eventos (scripts/chaos-run.sh):
  - Impacto real en el punto de entrada (service-a), a partir de los logs de requests:
      disponibilidad (sin 5xx) y latencia (≤ 300 ms) durante la falla vs. línea base.
  - ¿Se degradó el SLO?  Disponibilidad 99.5 %  |  Latencia: 99 % de requests ≤ 300 ms.
  - Error budget: consumo del experimento como % del budget DIARIO en régimen normal,
    burn rate durante la falla y tiempo hasta agotar el budget si la falla persistiera.
  - MTTD: inicio de la falla → primera alerta de cada motor (recibida por alert-enricher).
  - Accionabilidad: la alerta trae trace_id, span más lento y runbook.

Uso: python3 scripts/chaos_report.py --events results/chaos-*.events.csv
"""
import argparse
import csv
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone

SLO_AVAILABILITY = 0.995
SLO_LATENCY_GOAL = 0.99
SLO_LATENCY_MS = 300
TAIL = timedelta(seconds=60)          # requests en vuelo al terminar la falla
ALERT_WINDOW = timedelta(minutes=8)   # alertas tardías (Cloud Monitoring) se siguen atribuyendo
BASELINE = timedelta(minutes=5)


def parse(ts):
    ts = re.sub(r"(\.\d{6})\d+", r"\1", ts.replace("Z", "+00:00"))
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def logs(flt, limit=20000):
    out = subprocess.check_output(["gcloud", "logging", "read", flt, f"--limit={limit}",
                                   "--order=asc", "--format=json"], text=True)
    return json.loads(out or "[]")


def requests_between(t0, t1):
    entries = logs('resource.type="k8s_container" resource.labels.namespace_name="otel-lab" '
                   'jsonPayload.service="service-a" jsonPayload.message="request completed" '
                   f'timestamp>="{t0.isoformat()}" timestamp<="{t1.isoformat()}"')
    rows = []
    for e in entries:
        p = e["jsonPayload"]
        rows.append((parse(e["timestamp"]), p.get("status_class"), float(p.get("latency_ms", 0))))
    return rows


def sli(rows):
    n = len(rows)
    errors = sum(1 for _, s, _ in rows if s == "5xx")
    slow = sum(1 for _, _, l in rows if l > SLO_LATENCY_MS)
    lat = sorted(l for *_, l in rows)
    p99 = lat[int(0.99 * (n - 1))] if n else 0
    return {"n": n, "errors": errors, "slow": slow, "p99_ms": p99,
            "availability": 1 - errors / n if n else 1, "latency_ok": 1 - slow / n if n else 1}


def fmt_pct(x):
    return f"{100 * x:.2f} %"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    a = ap.parse_args()

    events = list(csv.DictReader(open(a.events)))
    for i, ev in enumerate(events):
        s, e = parse(ev["inicio"]), parse(ev["fin"])
        dur = (e - s).total_seconds()
        # Las alertas se atribuyen hasta 8 min después del fin, sin cruzar al siguiente experimento
        alert_end = e + ALERT_WINDOW
        if i + 1 < len(events):
            alert_end = min(alert_end, parse(events[i + 1]["inicio"]))
        # Línea base: 5 min inmediatamente anteriores (ya recuperados del experimento previo)
        base = sli(requests_between(s - BASELINE, s))
        rows = requests_between(s, e + TAIL)
        during = sli(rows)
        rps = base["n"] / BASELINE.total_seconds() if base["n"] else 5
        daily = rps * 86400

        first_bad = next((t for t, st, l in rows if st == "5xx" or l > SLO_LATENCY_MS), None)

        print("=" * 100)
        print(f"{ev['experimento'].upper()} — {ev['descripcion']}")
        print(f"Ventana de falla: {s:%H:%M:%S} → {e:%H:%M:%S} UTC ({dur:.0f} s)"
              f" | primer request afectado: {first_bad:%H:%M:%S} UTC" if first_bad else "")
        print("-" * 100)
        print(f"{'':<34}{'línea base (5 min previos)':>30}{'durante la falla':>22}")
        print(f"{'requests (service-a)':<34}{base['n']:>30}{during['n']:>22}")
        print(f"{'errores 5xx':<34}{base['errors']:>30}{during['errors']:>22}")
        print(f"{'requests > 300 ms':<34}{base['slow']:>30}{during['slow']:>22}")
        print(f"{'p99 latencia (ms)':<34}{base['p99_ms']:>30.0f}{during['p99_ms']:>22.0f}")
        print(f"{'SLI disponibilidad':<34}{fmt_pct(base['availability']):>30}{fmt_pct(during['availability']):>22}")
        print(f"{'SLI latencia (≤ 300 ms)':<34}{fmt_pct(base['latency_ok']):>30}{fmt_pct(during['latency_ok']):>22}")

        # ¿Se degradó el SLO?
        av_deg = during["availability"] < SLO_AVAILABILITY
        lat_deg = during["latency_ok"] < SLO_LATENCY_GOAL
        print("\n¿Se degradó el SLO durante la falla?")
        print(f"  Disponibilidad (objetivo {fmt_pct(SLO_AVAILABILITY)}): {'SÍ' if av_deg else 'NO'} — {fmt_pct(during['availability'])}")
        print(f"  Latencia (objetivo {fmt_pct(SLO_LATENCY_GOAL)} ≤ 300 ms): {'SÍ' if lat_deg else 'NO'} — {fmt_pct(during['latency_ok'])}")

        # Error budget
        av_budget = (1 - SLO_AVAILABILITY) * daily
        lat_budget = (1 - SLO_LATENCY_GOAL) * daily
        av_burn = (1 - during["availability"]) / (1 - SLO_AVAILABILITY)
        lat_burn = (1 - during["latency_ok"]) / (1 - SLO_LATENCY_GOAL)
        print(f"\n¿Se consumió error budget? (régimen: {rps:.2f} req/s → {daily:,.0f} requests/día)")
        print(f"  Disponibilidad: {during['errors']} errores de {av_budget:,.0f} permitidos/día → "
              f"{100 * during['errors'] / av_budget:.1f} % del budget diario | burn rate {av_burn:.1f}x"
              + (f" | agotaría el budget diario en {24 * 60 / av_burn:.0f} min" if av_burn > 1 else ""))
        print(f"  Latencia:       {during['slow']} lentos de {lat_budget:,.0f} permitidos/día → "
              f"{100 * during['slow'] / lat_budget:.1f} % del budget diario | burn rate {lat_burn:.1f}x"
              + (f" | agotaría el budget diario en {24 * 60 / lat_burn:.0f} min" if lat_burn > 1 else ""))

        # MTTD por motor y política
        alerts = logs('resource.type="cloud_run_revision" resource.labels.service_name="alert-enricher" '
                      'jsonPayload.event="alert.received" jsonPayload.state="open" '
                      f'timestamp>="{s.isoformat()}" timestamp<="{alert_end.isoformat()}"', 500)
        print("\nMTTD — primera alerta por política (desde el inicio de la falla)")
        seen = {}
        for al in alerts:
            p = al["jsonPayload"]
            key = (p.get("policy_type"), p.get("policy"))
            if key not in seen:
                seen[key] = (parse(p["received_at"]), p.get("service") or "-")
        for (engine, policy), (t, svc) in sorted(seen.items(), key=lambda kv: kv[1][0]):
            mttd = (t - s).total_seconds()
            flag = "✅" if mttd <= 120 else "❌"
            print(f"  {flag} {mttd:>5.0f} s  {engine:<9} {policy[:60]:<60} {svc}")
        if not seen:
            print("  (sin alertas)")

        # Accionabilidad: alerta enriquecida
        enriched = logs('resource.type="cloud_run_revision" resource.labels.service_name="alert-enricher" '
                        'jsonPayload.event="alert.enriched" jsonPayload.trace_id:* '
                        f'timestamp>="{s.isoformat()}" timestamp<="{alert_end.isoformat()}"', 50)
        print("\n¿La alerta fue accionable? (primera alerta AIOps enriquecida)")
        if enriched:
            p = enriched[0]["jsonPayload"]
            print(f"  {p.get('policy')} | servicio {p.get('service')}")
            print(f"  trace_id: {p.get('trace_id')} | evidencia: {p.get('evidence_kind')} "
                  f"HTTP {p.get('evidence_status')} en {p.get('evidence_route')} ({p.get('evidence_latency_ms')} ms)")
            print(f"  DIAGNÓSTICO: {p.get('diagnosis') or p.get('slowest_span')}")
            print(f"  red: {p.get('network_hotspot')} ({p.get('network_ms')} ms) | "
                  f"operación más costosa: {p.get('service_hotspot')} ({p.get('service_self_ms')} ms) | "
                  f"spans con error: {p.get('error_spans')}")
            print(f"  traza: {p.get('trace_url')}")
        else:
            print("  (no hubo alerta enriquecida con trace_id)")
        print()


if __name__ == "__main__":
    main()
