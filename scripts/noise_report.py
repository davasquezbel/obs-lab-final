#!/usr/bin/env python3
"""
Reporte de ruido y MTTD a partir de las alertas REALES recibidas por alert-enricher.

Compara tres motores de alerta sobre la misma ventana:
  static    → [ESTÁTICA] Cloud Monitoring (umbral fijo, sin correlación)
  aiops     → [AIOps]   Cloud Monitoring (baseline 2σ, correlación, burn rate)
  aiops-rt  → [AIOps-RT] detector en tiempo real (misma lógica, evaluación cada 15 s)

Clasificación de cada alerta abierta:
  - Verdadero positivo: abre durante el incidente real o hasta GRACE después de su fin.
  - Ruido: abre fuera del incidente (blips transitorios que no requieren acción).
MTTD = apertura de la alerta − primer request fallido/lento real del incidente (Cloud Logging).

Uso: python3 scripts/noise_report.py --events results/noise-test-*.events.csv --end <ISO>
"""
import argparse
import csv
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone

GRACE = timedelta(minutes=3)


def parse(ts):
    # Cloud Logging entrega nanosegundos; fromisoformat (Python < 3.11) acepta máx. 6 decimales
    ts = re.sub(r"(\.\d{6})\d+", r"\1", ts.replace("Z", "+00:00"))
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def gcloud_logs(flt, limit=2000, order="asc"):
    out = subprocess.check_output(
        ["gcloud", "logging", "read", flt, f"--limit={limit}", f"--order={order}", "--format=json"], text=True)
    return json.loads(out or "[]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--end", required=True)
    a = ap.parse_args()

    events = list(csv.DictReader(open(a.events)))
    start = parse(events[0]["inicio"])
    end = parse(a.end) + timedelta(minutes=3)
    inc = next(e for e in events if e["tipo"] == "incident")
    inc_s, inc_e = parse(inc["inicio"]), parse(inc["fin"])

    # t0 real del incidente: primer request fallido o lento observado en service-a
    first = gcloud_logs(
        f'resource.type="k8s_container" resource.labels.namespace_name="otel-lab" '
        f'jsonPayload.service="service-a" jsonPayload.message="request completed" '
        f'(jsonPayload.status_class="5xx" OR jsonPayload.latency_ms>300) '
        f'timestamp>="{inc_s.isoformat()}"', limit=1)
    t0 = parse(first[0]["timestamp"]) if first else inc_s

    alerts = gcloud_logs(
        f'resource.type="cloud_run_revision" resource.labels.service_name="alert-enricher" '
        f'jsonPayload.event="alert.received" jsonPayload.state="open" '
        f'timestamp>="{start.isoformat()}" timestamp<="{end.isoformat()}"')

    rows, agg = [], defaultdict(lambda: {"total": 0, "ruido": 0, "tp": 0, "mttd": [], "pages": 0, "pages_noise": 0})
    for al in alerts:
        p = al["jsonPayload"]
        opened = parse(p["received_at"])
        tp = inc_s <= opened <= inc_e + GRACE
        engine = p.get("policy_type", "?")
        sev = p.get("severity_label", "")
        k = agg[engine]
        k["total"] += 1
        k["tp" if tp else "ruido"] += 1
        # "Página" = alerta que despierta a alguien: en el sistema estático todas lo son;
        # en AIOps solo las críticas (correlación y burn rate); las warning van a ticket.
        page = engine == "static" or sev == "critical"
        k["pages"] += page
        k["pages_noise"] += page and not tp
        mttd = round((opened - t0).total_seconds()) if tp else None
        if tp:
            k["mttd"].append(mttd)
        blip = next((e["descripcion"] for e in events if e["tipo"] == "blip"
                     and parse(e["inicio"]) - timedelta(seconds=30) <= opened <= parse(e["fin"]) + timedelta(minutes=4)), "")
        rows.append((opened.strftime("%H:%M:%S"), engine, sev, p.get("policy", ""), p.get("service") or "",
                     "VERDADERO POSITIVO" if tp else "ruido", mttd if mttd is not None else "", blip))

    print(f"Incidente real: {inc_s:%H:%M:%S} → {inc_e:%H:%M:%S} | t0 (primer request afectado): {t0:%H:%M:%S}\n")
    print(f"{'abre':<9}{'motor':<10}{'sev':<9}{'política':<56}{'servicio':<13}{'clase':<20}{'MTTD':<6}blip asociado")
    for r in sorted(rows):
        print(f"{r[0]:<9}{r[1]:<10}{r[2]:<9}{r[3][:54]:<56}{r[4]:<13}{r[5]:<20}{str(r[6]):<6}{r[7]}")

    print("\nResumen por motor")
    print(f"{'motor':<10}{'alertas':>8}{'ruido':>7}{'VP':>5}{'precisión':>11}{'páginas':>9}{'pág. ruido':>11}{'MTTD mín':>10}{'MTTD med':>10}")
    for engine in ("static", "aiops", "aiops-rt"):
        k = agg.get(engine)
        if not k:
            continue
        prec = k["tp"] / k["total"] if k["total"] else 0
        m = sorted(k["mttd"])
        med = m[len(m) // 2] if m else "-"
        print(f"{engine:<10}{k['total']:>8}{k['ruido']:>7}{k['tp']:>5}{prec:>10.0%}{k['pages']:>9}"
              f"{k['pages_noise']:>11}{(m[0] if m else '-'):>10}{med:>10}")

    s, rt = agg.get("static"), agg.get("aiops-rt")
    if s and rt and s["ruido"]:
        print(f"\nReducción de alertas ruidosas (estática → AIOps-RT): {1 - rt['ruido'] / s['ruido']:.0%}"
              f"  ({s['ruido']} → {rt['ruido']})")
    if s and rt and s["pages_noise"]:
        print(f"Reducción de páginas ruidosas (estática → AIOps-RT): {1 - rt['pages_noise'] / s['pages_noise']:.0%}"
              f"  ({s['pages_noise']} → {rt['pages_noise']})")


if __name__ == "__main__":
    main()
