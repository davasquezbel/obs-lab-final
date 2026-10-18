#!/usr/bin/env python3
"""
Gráfica SVG de un experimento de caos: p99 y error rate de service-a (Managed Prometheus),
con las ventanas de falla sombreadas y la llegada de las alertas de cada motor.

Uso: python3 scripts/chaos_chart.py --events results/chaos-*.events.csv --out chaos.svg
"""
import argparse
import csv
import json
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PROJECT = "obs-lab-final"
STEP = 15
W, H = 1600, 760
L, R, T, B = 110, 120, 90, 150


def parse(ts):
    ts = re.sub(r"(\.\d{6})\d+", r"\1", ts.replace("Z", "+00:00"))
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def token():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()


def series(q, start, end, tok):
    url = (f"https://monitoring.googleapis.com/v1/projects/{PROJECT}/location/global/prometheus/api/v1/query_range?"
           + urllib.parse.urlencode({"query": q, "start": start.timestamp(), "end": end.timestamp(), "step": STEP}))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})) as r:
        res = json.load(r)["data"]["result"]
    return [(float(t), float(v)) for t, v in res[0]["values"]] if res else []


def alerts(start, end):
    out = subprocess.check_output([
        "gcloud", "logging", "read",
        'resource.type="cloud_run_revision" resource.labels.service_name="alert-enricher" '
        'jsonPayload.event="alert.received" jsonPayload.state="open" '
        f'timestamp>="{start.isoformat()}" timestamp<="{end.isoformat()}"',
        "--limit=200", "--order=asc", "--format=json"], text=True)
    first = {}
    for e in json.loads(out or "[]"):
        p = e["jsonPayload"]
        first.setdefault((p.get("policy_type"), p.get("policy")), parse(p["received_at"]))
    return first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    evs = list(csv.DictReader(open(a.events)))
    start = parse(evs[0]["inicio"]) - timedelta(minutes=3)
    end = parse(evs[-1]["fin"]) + timedelta(minutes=5)
    tok = token()
    ns = 'namespace="otel-lab",job="service-a"'
    p99 = series(f'histogram_quantile(0.99, sum by (le) (rate(http_server_request_duration_seconds_bucket{{{ns}}}[1m]))) * 1000', start, end, tok)
    err = series(f'100 * (sum(rate(http_server_requests_total{{{ns},status_class="5xx"}}[1m])) or vector(0)) / sum(rate(http_server_requests_total{{{ns}}}[1m]))', start, end, tok)
    al = alerts(start, end)

    t0, t1 = start.timestamp(), end.timestamp()
    pw, ph = W - L - R, H - T - B
    x = lambda t: L + (t - t0) / (t1 - t0) * pw
    p99max = max(800, max((v for _, v in p99), default=0) * 1.1)
    errmax = max(20, max((v for _, v in err), default=0) * 1.15)
    yl = lambda v: T + ph - v / p99max * ph
    yr = lambda v: T + ph - v / errmax * ph

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="Helvetica, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="{W/2}" y="40" text-anchor="middle" font-size="26" font-weight="bold" fill="#1A237E">'
         'Experimentos de caos — impacto en service-a y detección</text>']
    colors = {"exp1": "#FFE0B2", "exp2": "#FFCDD2"}
    for ev in evs:
        a0, a1 = x(parse(ev["inicio"]).timestamp()), x(parse(ev["fin"]).timestamp())
        s.append(f'<rect x="{a0:.1f}" y="{T}" width="{a1 - a0:.1f}" height="{ph}" fill="{colors.get(ev["experimento"], "#eee")}" opacity="0.8"/>')
        s.append(f'<text x="{(a0 + a1) / 2:.1f}" y="{T + 24}" text-anchor="middle" font-size="17" font-weight="bold" fill="#5D4037">'
                 f'{ev["experimento"].upper()}: {ev["descripcion"].split("(")[0].strip()}</text>')
    # Ejes y rejilla
    for i in range(5):
        v = p99max * i / 4
        y = yl(v)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" stroke="#ECEFF1"/>')
        s.append(f'<text x="{L - 10}" y="{y + 5:.1f}" text-anchor="end" font-size="14" fill="#1565C0">{v:.0f}</text>')
        s.append(f'<text x="{W - R + 10}" y="{yr(errmax * i / 4) + 5:.1f}" font-size="14" fill="#C62828">{errmax * i / 4:.0f} %</text>')
    slo = yl(300)
    s.append(f'<line x1="{L}" y1="{slo:.1f}" x2="{W - R}" y2="{slo:.1f}" stroke="#1565C0" stroke-dasharray="8 6" stroke-width="2"/>')
    s.append(f'<text x="{L + 8}" y="{slo - 8:.1f}" font-size="14" fill="#1565C0">SLO latencia 300 ms</text>')
    s.append(f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="none" stroke="#90A4AE"/>')
    s.append(f'<text x="30" y="{T + ph / 2}" font-size="15" fill="#1565C0" transform="rotate(-90 30 {T + ph / 2})" text-anchor="middle">p99 service-a (ms)</text>')
    s.append(f'<text x="{W - 30}" y="{T + ph / 2}" font-size="15" fill="#C62828" transform="rotate(90 {W - 30} {T + ph / 2})" text-anchor="middle">error rate service-a (%)</text>')
    t = t0 - t0 % 120 + 120
    while t < t1:
        s.append(f'<text x="{x(t):.1f}" y="{T + ph + 22}" text-anchor="middle" font-size="13" fill="#455A64">'
                 f'{datetime.fromtimestamp(t, tz=timezone.utc):%H:%M}</text>')
        t += 120
    s.append(f'<text x="{L + pw / 2}" y="{T + ph + 44}" text-anchor="middle" font-size="14" fill="#455A64">hora UTC (2026-10-18)</text>')
    # Series
    for pts, f, col in ((p99, yl, "#1565C0"), (err, yr, "#C62828")):
        if pts:
            d = " ".join(f"{x(tt):.1f},{f(v):.1f}" for tt, v in pts)
            s.append(f'<polyline points="{d}" fill="none" stroke="{col}" stroke-width="3"/>')
    # Alertas: primera de cada motor por experimento
    style = {"aiops-rt": ("#6A1B9A", "AIOps-RT"), "static": ("#455A64", "Estática"), "aiops": ("#EF6C00", "AIOps CM")}
    marks = {}
    for (engine, policy), when in al.items():
        if engine not in style:
            continue
        ev = next((e for e in evs if parse(e["inicio"]) <= when <= parse(e["fin"]) + timedelta(minutes=6)), None)
        if ev and (ev["experimento"], engine) not in marks:
            marks[(ev["experimento"], engine)] = (when, ev)
    row = {"aiops-rt": 0, "static": 1, "aiops": 2}
    for (exp, engine), (when, ev) in marks.items():
        col, label = style[engine]
        xx = x(when.timestamp())
        mttd = (when - parse(ev["inicio"])).total_seconds()
        yy = T + 50 + row[engine] * 26
        s.append(f'<line x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{T + ph}" stroke="{col}" stroke-width="2" stroke-dasharray="4 4"/>')
        s.append(f'<rect x="{xx + 4:.1f}" y="{yy - 15}" width="150" height="21" rx="4" fill="#fff" stroke="{col}"/>')
        s.append(f'<text x="{xx + 10:.1f}" y="{yy}" font-size="13" fill="{col}" font-weight="bold">{label}: {mttd:.0f} s</text>')
    # Leyenda
    ly = H - 45
    items = [("#1565C0", "p99 latencia service-a"), ("#C62828", "error rate service-a"),
             ("#6A1B9A", "1ª alerta AIOps-RT"), ("#455A64", "1ª alerta estática"), ("#EF6C00", "1ª alerta AIOps (Cloud Monitoring)")]
    lx = L
    for col, txt in items:
        s.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{col}" stroke-width="4"/>')
        s.append(f'<text x="{lx + 42}" y="{ly + 5}" font-size="15" fill="#263238">{txt}</text>')
        lx += 70 + len(txt) * 8
    s.append("</svg>")
    open(a.out, "w").write("\n".join(s))
    print(f"SVG: {a.out} | puntos p99={len(p99)} err={len(err)} | alertas marcadas={len(marks)}")


if __name__ == "__main__":
    main()
