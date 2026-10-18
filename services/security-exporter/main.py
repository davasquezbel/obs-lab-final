"""
security-exporter: publica señales de seguridad como métricas de Cloud Monitoring.

Se ejecuta como CronJob (cada 5 min) y escribe series en custom.googleapis.com/security/*:
  - posture_findings{severity, category}      ← chequeos de postura propios (estilo Security Health
                                                 Analytics): SCC exige una organización y la cuenta
                                                 del laboratorio no tiene una
  - scc_active_findings{severity, category}  ← Security Command Center (si estuviera activado)
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
CLUSTER = os.getenv("GKE_CLUSTER", "projects/obs-lab-final/locations/us-central1-a/clusters/obs-lab-gke")
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


def _get(client, url):
    r = client.get(url, headers=headers())
    r.raise_for_status()
    return r.json()


def posture_findings(client) -> list[dict]:
    """Chequeos de configuración insegura equivalentes a detectores de Security Health Analytics."""
    findings = []

    def add(category, severity, resource, detail):
        findings.append({"category": category, "severity": severity, "resource": resource, "detail": detail})

    checks = []

    def cloud_sql():
        for inst in _get(client, f"https://sqladmin.googleapis.com/v1/projects/{PROJECT}/instances").get("items", []):
            st, name = inst.get("settings", {}), inst["name"]
            ip = st.get("ipConfiguration", {})
            nets = [n.get("value") for n in ip.get("authorizedNetworks", [])]
            if ip.get("ipv4Enabled"):
                if "0.0.0.0/0" in nets:
                    add("PUBLIC_SQL_INSTANCE", "CRITICAL", name, "IP pública abierta a 0.0.0.0/0")
                else:
                    add("SQL_PUBLIC_IP_ENABLED", "MEDIUM", name,
                        "IP pública habilitada (sin redes autorizadas; acceso solo vía Auth Proxy)")
            if ip.get("sslMode") not in ("ENCRYPTED_ONLY", "TRUSTED_CLIENT_CERTIFICATE_REQUIRED") and not ip.get("requireSsl"):
                add("SSL_NOT_ENFORCED", "HIGH", name, "Conexiones sin TLS permitidas")
            if not st.get("backupConfiguration", {}).get("enabled"):
                add("SQL_NO_AUTOMATED_BACKUP", "MEDIUM", name, "Backups automáticos deshabilitados")
    checks.append(cloud_sql)

    def firewalls():
        for fw in _get(client, f"https://compute.googleapis.com/compute/v1/projects/{PROJECT}/global/firewalls").get("items", []):
            if fw.get("disabled") or fw.get("direction") != "INGRESS" or "0.0.0.0/0" not in fw.get("sourceRanges", []):
                continue
            for rule in fw.get("allowed", []):
                ports = rule.get("ports", [])
                if not ports or any(p in ("22", "3389") for p in ports):
                    add("OPEN_FIREWALL", "HIGH", fw["name"], f"Ingreso desde Internet a {rule.get('IPProtocol')} {ports or 'todos'}")
                else:
                    add("OPEN_FIREWALL_TO_SERVICE", "LOW", fw["name"], f"Ingreso desde Internet a puertos {ports}")
    checks.append(firewalls)

    def forwarding_rules():
        agg = _get(client, f"https://compute.googleapis.com/compute/v1/projects/{PROJECT}/aggregated/forwardingRules")
        for scope in agg.get("items", {}).values():
            for fr in scope.get("forwardingRules", []):
                if fr.get("loadBalancingScheme") == "EXTERNAL" and fr.get("portRange", "").startswith("80"):
                    add("NON_TLS_PUBLIC_ENDPOINT", "MEDIUM", fr["name"],
                        f"Endpoint público HTTP sin TLS en {fr.get('IPAddress')}:80")
    checks.append(forwarding_rules)

    def gke():
        c = _get(client, f"https://container.googleapis.com/v1/{CLUSTER}")
        name = c["name"]
        if not c.get("privateClusterConfig", {}).get("enablePrivateEndpoint") \
                and not c.get("masterAuthorizedNetworksConfig", {}).get("enabled"):
            add("PUBLIC_GKE_CONTROL_PLANE", "HIGH", name, "Control plane accesible desde cualquier IP")
        if c.get("legacyAbac", {}).get("enabled"):
            add("LEGACY_AUTHORIZATION_ENABLED", "HIGH", name, "ABAC heredado habilitado")
        if c.get("binaryAuthorization", {}).get("evaluationMode") in (None, "DISABLED", "EVALUATION_MODE_UNSPECIFIED"):
            add("BINARY_AUTHORIZATION_DISABLED", "LOW", name, "Binary Authorization deshabilitada")
        if not c.get("shieldedNodes", {}).get("enabled"):
            add("SHIELDED_NODES_DISABLED", "MEDIUM", name, "Nodos sin Shielded VM")
    checks.append(gke)

    def iam():
        r = client.post(f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:getIamPolicy",
                        json={}, headers=headers())
        r.raise_for_status()
        for b in r.json().get("bindings", []):
            for m in b.get("members", []):
                if m.endswith("-compute@developer.gserviceaccount.com") and b["role"] == "roles/editor":
                    add("DEFAULT_SA_EDITOR", "MEDIUM", m, "Cuenta de servicio por defecto con rol Editor")
                if m in ("allUsers", "allAuthenticatedUsers"):
                    add("PUBLIC_IAM_BINDING", "CRITICAL", b["role"], f"{m} tiene {b['role']} en el proyecto")
    checks.append(iam)

    def cloud_run():
        url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/us-central1/services"
        for svc in _get(client, url).get("services", []):
            r = client.post(f"https://run.googleapis.com/v2/{svc['name']}:getIamPolicy", json={}, headers=headers())
            if r.status_code == 200 and any("allUsers" in b.get("members", []) for b in r.json().get("bindings", [])):
                add("PUBLIC_CLOUD_RUN_SERVICE", "LOW", svc["name"].split("/")[-1],
                    "Invocación sin autenticación (mitigado con token en la URL)")
    checks.append(cloud_run)

    for check in checks:
        try:
            check()
        except httpx.HTTPError as e:
            log("WARNING", "Chequeo de postura no disponible", check=check.__name__, error=str(e)[:200])
    return findings


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
        posture = posture_findings(client)
        for f in posture:
            log("WARNING" if f["severity"] in ("LOW", "MEDIUM") else "ERROR",
                f"Hallazgo de postura: {f['category']} ({f['severity']}) en {f['resource']}",
                event="security.finding", finding_severity=f["severity"], category=f["category"],
                resource=f["resource"], detail=f["detail"])
        write_series(client, "posture_findings", Counter((f["severity"], f["category"]) for f in posture),
                     ["severity", "category"])
        cves, fixable = image_cves(client)
        write_series(client, "scc_active_findings", findings, ["severity", "category"])
        write_series(client, "image_vulnerabilities", cves, ["severity", "image"])
        write_series(client, "image_fixable_vulnerabilities", fixable, ["severity", "image"])
        by_sev = Counter()
        for (sev, _), n in cves.items():
            by_sev[sev] += n
        log("INFO", "Señales de seguridad publicadas", event="security.export",
            scc_findings=sum(findings.values()),
            posture_findings=len(posture),
            posture_by_severity=dict(Counter(f["severity"] for f in posture)),
            scc_by_severity=dict(Counter({s: n for (s, _), n in findings.items()})),
            cves_total=sum(cves.values()), cves_by_severity=dict(by_sev),
            cves_fixable=sum(fixable.values()))


if __name__ == "__main__":
    sys.exit(main())
