"""
security-exporter: publica señales de seguridad como métricas de Cloud Monitoring.

Se ejecuta como CronJob (cada 5 min) y escribe series en custom.googleapis.com/security/*:
  - scc_active_findings{severity, category}  ← Security Command Center (findings ACTIVE, no muteados)
  - image_vulnerabilities{severity, image}     ← Artifact Analysis (CVEs de las imágenes en uso)
  - image_fixable_vulnerabilities{severity, image}

Así los CVEs y los findings de SCC quedan en el mismo backend que el resto de la
telemetría y pueden graficarse en el dashboard "Golden Signals de Seguridad" y alertarse.
"""

import json
import os
import sys
import time
from collections import Counter

import google.auth
import google.auth.transport.requests
import httpx

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "obs-lab-final")
# Imágenes en uso por el sistema (prefijo de Artifact Registry)
IMAGE_PREFIX = os.getenv("IMAGE_PREFIX", f"https://us-central1-docker.pkg.dev/{PROJECT}/obs-lab/")
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])


def log(severity, message, **fields):
    print(json.dumps({"severity": severity, "message": message, **fields}, default=str), flush=True)


def headers():
    if not _creds.valid:
        _creds.refresh(google.auth.transport.requests.Request())
    return {"Authorization": f"Bearer {_creds.token}"}


def paged(client, url, params, key):
    while True:
        r = client.get(url, params=params, headers=headers())
        r.raise_for_status()
        body = r.json()
        yield from body.get(key, [])
        if not body.get("nextPageToken"):
            return
        params = {**params, "pageToken": body["nextPageToken"]}


def scc_findings(client) -> Counter:
    counts = Counter()
    url = f"https://securitycenter.googleapis.com/v1/projects/{PROJECT}/sources/-/findings"
    try:
        for item in paged(client, url, {"filter": 'state="ACTIVE" AND NOT mute="MUTED"', "pageSize": 1000},
                          "listFindingsResults"):
            f = item["finding"]
            counts[(f.get("severity", "SEVERITY_UNSPECIFIED"), f.get("category", "UNKNOWN"))] += 1
    except httpx.HTTPStatusError as e:
        log("WARNING", "SCC no disponible (¿no activado?)", status=e.response.status_code,
            body=e.response.text[:300])
    return counts


def image_cves(client) -> tuple[Counter, Counter]:
    """CVEs del digest MÁS RECIENTE de cada imagen (la versión desplegada), sin duplicados."""
    url = f"https://containeranalysis.googleapis.com/v1/projects/{PROJECT}/occurrences"
    by_digest: dict[tuple[str, str], list[dict]] = {}
    latest: dict[str, tuple[str, str]] = {}          # imagen -> (createTime, digest)
    for o in paged(client, url, {"filter": 'kind="VULNERABILITY"', "pageSize": 1000}, "occurrences"):
        uri = o.get("resourceUri", "")
        if not uri.startswith(IMAGE_PREFIX) or "@" not in uri:
            continue
        image, digest = uri[len(IMAGE_PREFIX):].split("@", 1)
        by_digest.setdefault((image, digest), []).append(o)
        created = o.get("createTime", "")
        if image not in latest or created > latest[image][0]:
            latest[image] = (created, digest)

    total, fixable = Counter(), Counter()
    for image, (_, digest) in latest.items():
        seen = set()
        for o in by_digest[(image, digest)]:
            v = o.get("vulnerability", {})
            cve = o.get("noteName", "").split("/")[-1]
            if cve in seen:
                continue
            seen.add(cve)
            sev = v.get("effectiveSeverity") or v.get("severity") or "SEVERITY_UNSPECIFIED"
            total[(sev, image)] += 1
            if v.get("fixAvailable"):
                fixable[(sev, image)] += 1
    return total, fixable


def write_series(client, metric, counts: Counter, label_names):
    now = {"endTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    series = [{
        "metric": {"type": f"custom.googleapis.com/security/{metric}",
                   "labels": dict(zip(label_names, key))},
        "resource": {"type": "global", "labels": {"project_id": PROJECT}},
        "metricKind": "GAUGE", "valueType": "INT64",
        "points": [{"interval": now, "value": {"int64Value": str(n)}}],
    } for key, n in counts.items()]
    # Serie "total" para que el panel muestre 0 explícito cuando no hay hallazgos
    series.append({
        "metric": {"type": f"custom.googleapis.com/security/{metric}",
                   "labels": {k: "TOTAL" for k in label_names}},
        "resource": {"type": "global", "labels": {"project_id": PROJECT}},
        "metricKind": "GAUGE", "valueType": "INT64",
        "points": [{"interval": now, "value": {"int64Value": str(sum(counts.values()))}}],
    })
    for i in range(0, len(series), 200):
        r = client.post(f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries",
                        json={"timeSeries": series[i:i + 200]}, headers=headers())
        if r.status_code >= 300:
            log("ERROR", "Error escribiendo métricas", metric=metric, body=r.text[:500])


def main():
    with httpx.Client(timeout=60) as client:
        findings = scc_findings(client)
        cves, fixable = image_cves(client)
        write_series(client, "scc_active_findings", findings, ["severity", "category"])
        write_series(client, "image_vulnerabilities", cves, ["severity", "image"])
        write_series(client, "image_fixable_vulnerabilities", fixable, ["severity", "image"])
        by_sev = Counter()
        for (sev, _), n in cves.items():
            by_sev[sev] += n
        log("INFO", "Señales de seguridad publicadas", event="security.export",
            scc_findings=sum(findings.values()),
            scc_by_severity=dict(Counter({s: n for (s, _), n in findings.items()})),
            cves_total=sum(cves.values()), cves_by_severity=dict(by_sev),
            cves_fixable=sum(fixable.values()))


if __name__ == "__main__":
    sys.exit(main())
