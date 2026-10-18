// Generador del reporte ejecutivo final (Word) — Laboratorio Final de Observabilidad
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType,
  AlignmentType, HeadingLevel, BorderStyle, ShadingType, LevelFormat, PageBreak, Footer,
  Header, PageNumber, TableOfContents, VerticalAlign, ExternalHyperlink,
} = require("docx");

const IMG = path.join(__dirname, "img");
const OUT = process.argv[2] || path.join(__dirname, "Reporte_Final_Observabilidad.docx");
const V = JSON.parse(fs.readFileSync(path.join(__dirname, "validation.json"), "utf8"));

// ── Estilo ────────────────────────────────────────────────────────────
const FONT = "Calibri";
const C = { navy: "1A237E", blue: "1565C0", grey: "546E7A", head: "E3F2FD", alt: "F7F9FC", green: "2E7D32", red: "C62828" };
const PAGE_W = 12240, MARGIN = 1080;               // Carta, márgenes 0.75"
const CONTENT_W = PAGE_W - 2 * MARGIN;             // 10080 DXA = 7"

// Texto con **negritas** en línea
function runs(text, base = {}) {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map(t =>
    t.startsWith("**") ? new TextRun({ ...base, text: t.slice(2, -2), bold: true }) : new TextRun({ ...base, text: t }));
}
const p = (text, o = {}) => new Paragraph({ spacing: { after: 100, line: 264 }, alignment: o.align || AlignmentType.JUSTIFIED, ...o.para, children: runs(text, o.run) });
const h1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, children: [new TextRun(t)] });
const h2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, children: [new TextRun(t)] });
const bullet = (text, level = 0) => new Paragraph({ numbering: { reference: "bullets", level }, spacing: { after: 40, line: 252 }, children: runs(text) });
const caption = t => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 40, after: 160 }, children: [new TextRun({ text: t, italics: true, size: 17, color: C.grey })] });

function image(file, widthIn, captionText) {
  const buf = fs.readFileSync(path.join(IMG, file));
  const [w, h] = dims(buf);
  const wpx = widthIn * 96, hpx = wpx * h / w;
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, keepLines: true, spacing: { before: 80, after: 20 },
      children: [new ImageRun({ type: file.endsWith(".png") ? "png" : "jpg", data: buf, transformation: { width: wpx, height: hpx },
        altText: { title: captionText, description: captionText, name: file } })] }),
    caption(captionText),
  ];
}
function dims(buf) {   // PNG / JPEG
  if (buf[0] === 0x89) return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
  let i = 2;
  while (i < buf.length) {
    const marker = buf[i + 1], len = buf.readUInt16BE(i + 2);
    if (marker >= 0xC0 && marker <= 0xC2) return [buf.readUInt16BE(i + 7), buf.readUInt16BE(i + 5)];
    i += 2 + len;
  }
  throw new Error("dimensiones no encontradas");
}

const border = { style: BorderStyle.SINGLE, size: 4, color: "B0BEC5" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(headers, rows, widthsPct, o = {}) {
  const widths = widthsPct.map(x => Math.round(CONTENT_W * x / 100));
  widths[widths.length - 1] += CONTENT_W - widths.reduce((a, b) => a + b, 0);
  const cell = (text, i, header, shade) => new TableCell({
    borders, width: { size: widths[i], type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
    shading: { fill: header ? C.head : (shade ? C.alt : "FFFFFF"), type: ShadingType.CLEAR, color: "auto" },
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new Paragraph({ spacing: { after: 0, line: 240 }, alignment: (o.center || []).includes(i) ? AlignmentType.CENTER : AlignmentType.LEFT,
      children: runs(String(text), { size: o.size || 17, bold: header, color: header ? C.navy : undefined }) })],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: headers.map((t, i) => cell(t, i, true)) }),
      ...rows.map((r, ri) => new TableRow({ children: r.map((t, i) => cell(t, i, false, ri % 2 === 1)) }))],
  });
}
const space = (n = 80) => new Paragraph({ spacing: { after: n }, children: [] });

// ── Contenido ─────────────────────────────────────────────────────────
const cover = [
  new Paragraph({ spacing: { before: 1800, after: 200 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: "UNIVERSIDAD DE LA SABANA", bold: true, size: 26, color: C.grey })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 }, children: [new TextRun({ text: "Maestría en Arquitectura de Software · Observabilidad en Ambientes Productivos", size: 24, color: C.grey })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: "Laboratorio Final Integrador", size: 30, color: C.blue })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 }, children: [new TextRun({ text: "Sistema observable de nivel producción en Google Cloud", bold: true, size: 48, color: C.navy })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 1400 }, children: [new TextRun({ text: "Tres pilares con OpenTelemetry · AIOps · Observabilidad de red y seguridad · SRE · Chaos Engineering", size: 24, italics: true, color: C.grey })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "Reporte ejecutivo final", bold: true, size: 26 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "Estudiante: David Vasquez", size: 24 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "Docente: ______________________", size: 24 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "Octubre de 2026", size: 24 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new ExternalHyperlink({ link: "https://github.com/davasquezbel/obs-lab-final", children: [new TextRun({ text: "github.com/davasquezbel/obs-lab-final (tag v1.0)", style: "Hyperlink", size: 22 })] })] }),
  new Paragraph({ children: [new PageBreak()] }),
];

const resumen = [
  h1("1. Resumen ejecutivo"),
  p("Se construyó y operó durante el laboratorio un sistema de tres microservicios (service-a, service-b y data-service) sobre **GKE** con base de datos gestionada **Cloud SQL**, instrumentado de punta a punta con **OpenTelemetry** y conectado a **Google Cloud Observability**. Sobre esa base se agregaron un **service mesh L7** (Cloud Service Mesh con mTLS), detección de anomalías y correlación **AIOps** con alertas enriquecidas con trace_id, observabilidad de **red y seguridad** (VPC Flow Logs, eBPF, CVEs y postura) y **Chaos Engineering** para validar la detección en menos de 2 minutos. Toda la infraestructura está definida con **Terraform** y publicada en GitHub."),
  p("**Alcance:** la actividad plantea GCP y AWS; por decisión del estudiante se implementó **solo en GCP**. La sección 8 documenta la equivalencia de cada componente en AWS."),
  table(["Criterio de la rúbrica", "Resultado obtenido"], [
    ["Arquitectura observable completa", "3 microservicios con OTel (3 pilares correlacionados por trace_id), spans de BD con DB Semantic Conventions, Cloud Service Mesh con **100 % del tráfico E-W en mTLS** y métricas L7."],
    ["AIOps: detección y correlación", "Baseline μ + 2σ y regla **error_rate > baseline + 2σ AND p99 > SLO**; **−87 % alertas ruidosas** y **0 páginas falsas** frente a umbrales estáticos; alertas con trace_id y diagnóstico."],
    ["Observabilidad de red y seguridad", "Flow Logs E-W/N-S, microsegmentación con logging eBPF (movimiento lateral detectado en **56 s**), fuerza bruta (μ + 3σ), CVEs y postura como métricas; dashboard **Golden Signals de Seguridad**."],
    ["Chaos Engineering y MTTD", "2 experimentos (+200 ms en service-b; 10 % de errores en data-service): **MTTD 69 s y 77 s**; SLO degradado y consumo de **29.7 %** y **11.9 %** del error budget diario."],
    ["Madurez y roadmap", "Autoevaluación en 8 dominios: **3.0 / 5**; roadmap a 3 meses con objetivo **3.9**."],
  ], [30, 70]),
  space(),
];

const arquitectura = [
  h1("2. Arquitectura"),
  ...image("arquitectura.png", 6.9, "Figura 1. Arquitectura desplegada en el proyecto obs-lab-final (us-central1)."),
  table(["Capa", "Componentes", "Decisión clave"], [
    ["Cómputo y red", "GKE Standard zonal (3 × e2-standard-2), nodos privados, Dataplane V2 (eBPF), VPC dedicada, Cloud NAT", "Nodos sin IP pública; tráfico de salida observable vía NAT y Flow Logs"],
    ["Datos", "Cloud SQL PostgreSQL 16 (Query Insights) vía Cloud SQL Auth Proxy", "Sin redes autorizadas: acceso solo por proxy + IAM (Workload Identity)"],
    ["Aplicación", "service-a (orquestador, /login), service-b (inventario), data-service (capa de datos)", "Solo data-service accede a la BD: un único punto de instrumentación de datos"],
    ["Telemetría", "OTel SDK → OTel Collector → Cloud Trace y Managed Prometheus; logs JSON → Cloud Logging", "Logs con campos especiales de Cloud Logging para enlace automático log ↔ traza"],
    ["Malla", "Cloud Service Mesh gestionado (Traffic Director), ingress gateway, mTLS STRICT", "Reintentos solo ante fallas de transporte, para no ocultar errores de aplicación"],
    ["Operación", "SLOs, 11 alertas, alert-enricher (Cloud Run), aiops-detector, Chaos Mesh, security-exporter", "Todo como código (Terraform + manifiestos) y reproducible con scripts"],
  ], [16, 46, 38]),
  space(),
];

const moduloA = [
  h1("3. Módulo A — Arquitectura observable completa"),
  h2("3.1 Tres pilares correlacionados"),
  bullet("**Trazas:** propagación W3C entre los tres servicios; cada consulta genera un span CLIENT con atributos estables de **OTel DB Semantic Conventions** (db.system.name, db.namespace, db.operation.name, db.collection.name, db.query.text) y legacy."),
  bullet("**Métricas:** RED por servicio (http_server_requests, http_server_request_duration con buckets alineados al SLO de 300 ms), métricas de BD y de negocio, en Managed Service for Prometheus."),
  bullet("**Logs:** JSON estructurado con trace_id y span_id; Cloud Logging los enlaza con la traza. **sqlcommenter** envía el traceparent a Cloud SQL, por lo que **Query Insights** muestra cada consulta con su traza."),
  ...image("E2-02_trace_cascada.jpg", 6.9, "Figura 2. Una petición real: service-a → data-service (SELECT appdb.orders) → service-b → data-service (SELECT appdb.inventory)."),
  ...image("E2-03_span_db_semconv.jpg", 5.6, "Figura 3. Span SELECT appdb.orders con atributos de OTel DB Semantic Conventions (estables y legacy)."),
  h2("3.2 Service mesh L7"),
  p("Cloud Service Mesh inyecta Envoy en todos los workloads: **mTLS STRICT** (una conexión en texto plano desde un pod fuera del mesh es rechazada), identidad SPIFFE por servicio, métricas L7 (tasa, códigos de respuesta y latencia por servicio) y topología del mesh. El dashboard de seguridad confirma que el **100 %** del tráfico E-W de la aplicación viaja con mTLS."),
  ...image("E3-06_mesh_mtls.jpg", 6.9, "Figura 4. Conexiones de service-a con candado mTLS e identidad SPIFFE del ingress gateway."),
  p("**Incidencias resueltas:** el comentario sqlcommenter rompía psycopg2 por el carácter % (detectado por los mismos 5xx y logs); el mesh gestionado tardó ~55 min en aprovisionarse, solo sirve APIs v1beta1 y no preserva sidecars nativos (el Auth Proxy pasó a contenedor regular)."),
];

const moduloB = [
  h1("4. Módulo B — AIOps: detección automática de anomalías"),
  table(["Motor / política", "Regla", "Uso"], [
    ["[ESTÁTICA] Error rate / Latencia", "error_rate(1m) > 1 % · p99(1m) > 200 ms", "Línea base \"ingenua\" para medir ruido"],
    ["[AIOps] Anomalía de error / latencia", "valor(2m) > max(μ₁ₕ + 2σ₁ₕ, piso)", "Warning (ticket)"],
    ["[AIOps] CRÍTICA correlacionada", "**error_rate > μ₁ₕ + 2σ₁ₕ AND p99 > SLO (300 ms)**", "Página, con trace_id"],
    ["[AIOps] Burn rate", "burn rate 5 min del SLO de disponibilidad > 10x", "Página"],
    ["[AIOps-RT] (detector propio)", "Misma lógica evaluada cada 15 s sobre Managed Prometheus", "Cumplir MTTD < 2 min"],
  ], [30, 46, 24]),
  space(60),
  p("**Enriquecimiento:** cada alerta llega a **alert-enricher** (Cloud Run), que busca en Cloud Logging el request fallido o lento, recupera su traza y produce un **diagnóstico**: tiempo de red por salto (span cliente − span servidor) u origen del error (span 5xx más profundo). El resultado se notifica por correo con trace_id y enlace a la traza."),
  h2("4.1 Reducción de alertas ruidosas (evidencia cuantitativa)"),
  p("Prueba de 33 minutos con 7 perturbaciones transitorias de una sola señal (ruido) y un incidente real; la verdad de referencia es la degradación **multiseñal** observada en service-a (errores > 5 % y p99 > 300 ms). Los tres motores se evaluaron con los mismos datos:"),
  table(["Motor", "Alertas", "Ruido", "Precisión", "Páginas", "Páginas ruidosas", "MTTD real"], [
    ["Estático", "29", "15", "48 %", "29", "15", "212 s"],
    ["AIOps (Cloud Monitoring)", "17", "2", "88 %", "5", "**0**", "308 s"],
    ["**AIOps-RT (detector)**", "19", "2", "89 %", "5", "**0**", "**86 s**"],
  ], [26, 11, 10, 12, 11, 15, 15], { center: [1, 2, 3, 4, 5, 6] }),
  space(60),
  p("Resultado: **−87 % de alertas ruidosas (15 → 2)** y **−100 % de páginas ruidosas (15 → 0)**, con los dos eventos reales detectados. Las políticas PromQL de Cloud Monitoring agregaron 2.5–4 min de evaluación (la ingesta tenía 3–7 s), por lo que se implementó el detector en tiempo real para cumplir el MTTD."),
  ...image("E4-07a_alertas_enriquecidas_lista.jpg", 6.9, "Figura 5. Alertas críticas enriquecidas con trace_id: AIOps-RT llega 2–4 min antes que la política gestionada."),
];

const moduloC = [
  h1("5. Módulo C — Observabilidad de red y seguridad"),
  table(["Señal", "Fuente", "Alerta / panel"], [
    ["Tráfico E-W y N-S", "VPC Flow Logs (5 s, 50 %) con metadatos de pod/workload", "Paneles E-W y N-S; flujos desde namespaces no autorizados"],
    ["Movimiento lateral", "NetworkPolicy default-deny + NetworkLogging de Dataplane V2 (eBPF)", "[SEG] crítica, detectada en **56 s**"],
    ["Fuerza bruta en /login", "auth_attempts_total + VPC Flow Logs (IP, ciudad, ASN reales)", "[SEG] μ + 3σ; atacante identificado (Medellín, ASN 13489)"],
    ["CVEs activos", "Artifact Analysis (escaneo automático)", "472 CVEs (42 HIGH, 0 CRITICAL, 70 con corrección)"],
    ["Postura", "GKE Security Posture + chequeos propios estilo Security Health Analytics", "9 hallazgos (4 HIGH) como métricas"],
    ["Cifrado E-W", "Métricas L7 de Envoy", "100 % del tráfico con mTLS"],
  ], [20, 44, 36]),
  space(60),
  ...image("E5-06c_dashboard_seguridad_mtls.jpg", 6.9, "Figura 6. Dashboard \"Golden Signals de Seguridad\" durante la simulación de ataques."),
  p("**Security Command Center** no pudo activarse: exige una organización de Google Cloud (Workspace/Cloud Identity con dominio verificado) y la cuenta del laboratorio no la tiene. Se cubrió su función con **GKE Security Posture** (que además reportó CVE-2024-6387 en 90 resultados y el contenedor privilegiado de Chaos Mesh), **Artifact Analysis** y chequeos propios publicados como métricas. Hallazgos reales que alimentan el roadmap: la red default con SSH/RDP abiertos a Internet, el control plane público, el gateway HTTP sin TLS y Cloud SQL sin backups."),
  ...image("E5-09_gke_security_posture.jpg", 6.2, "Figura 7. GKE Security Posture: hallazgos de configuración de workloads y CVEs críticos (CVE-2024-6387)."),
];

const exp = V.experiments;
const moduloD = [
  h1("6. Módulo D — Chaos Engineering controlado"),
  p("Experimentos en el proyecto sandbox dedicado, con hipótesis de estado estable, blast radius acotado y rollback automático. El experimento 2 inyecta el error dentro del proceso porque **HTTPChaos no intercepta tráfico con mTLS STRICT** (verificado), y desactivar mTLS degradaría la seguridad."),
  ...image("chaos.png", 6.9, "Figura 8. p99 y error rate de service-a durante los experimentos y llegada de la primera alerta de cada motor."),
  table(["", "Exp. 1: +200 ms de red en service-b", "Exp. 2: 10 % de errores en data-service"], [
    ["Mecanismo", "Chaos Mesh NetworkChaos (tc), 302 s", "Falla en proceso con TTL, 304 s"],
    ["p99 service-a", "74 ms → **534 ms**", "78 ms → 88 ms"],
    ["SLI disponibilidad", "100 % → 100 %", "99.93 % → **85.93 %**"],
    ["SLI latencia ≤ 300 ms", "100 % → **29.17 %**", "100 % → 100 %"],
    ["**¿Se degradó el SLO?**", "**Sí**, latencia (objetivo 99 %)", "**Sí**, disponibilidad (objetivo 99.5 %)"],
    ["**¿Se consumió error budget?**", "1.282 requests lentos = **29.7 %** del budget diario; burn rate **70.8x** (lo agotaría en 20 min)", "256 errores = **11.9 %** del budget diario; burn rate **28.1x** (lo agotaría en 51 min)"],
    ["**MTTD** AIOps-RT / estática / AIOps CM", "**69 s ✓** / 195 s / 243 s", "**77 s ✓** / 196 s / 246 s"],
    ["**¿Alerta accionable?**", exp.exp1, exp.exp2],
  ], [22, 39, 39]),
  space(60),
  p("**Lecturas:** (1) solo el detector en tiempo real cumple el objetivo de MTTD; (2) la correlación funcionó como se diseñó: ningún experimento de una sola señal generó página (warning con trace_id), la página se reserva para degradación multiseñal; (3) la accionabilidad requirió iterar: el primer diagnóstico (\"span más lento\") apuntaba a una consulta de 7 ms cuando el problema era la red, y se reemplazó por el análisis por saltos; (4) un 10 % de errores en data-service se amplificó a ~14 % en service-a porque cada pedido lo invoca dos veces."),
  p("**Hallazgo adicional:** durante la prueba de ruido, apenas **+100 ms de latencia de red en data-service** provocó una falla en cascada (~90 % de errores en service-a, consultas de hasta 10 s), por consultas síncronas, ausencia de deadlines y reintentos que amplifican la carga. Es la primera iniciativa del roadmap. El error budget de la consola ya estaba agotado por los incidentes de puesta en marcha, por lo que el consumo se midió por experimento contra el budget diario en régimen (2.160 errores y 4.320 requests lentos por día)."),
  ...image("E4-10_traza_desde_alerta.jpg", 6.9, "Figura 9. Traza señalada por una alerta crítica durante la cascada: SELECT appdb.inventory de 5–10 s, reintento de service-b y errores propagados hasta service-a."),
];

const moduloE = [
  h1("7. Módulo E — Madurez de observabilidad y roadmap"),
  p("Escala: 1 Inicial · 2 Gestionado · 3 Definido · 4 Cuantificado · 5 Optimizado."),
  table(["Dominio", "Nivel", "Evidencia", "Brecha principal"], [
    ["Telemetría (3 pilares)", "4", "Correlación por trace_id, spans de BD, Query Insights enlazado, verificación automatizada", "Exemplars, logs vía OTLP"],
    ["OpenTelemetry", "3", "SDK manual + auto, DB semconv, Collector gateway", "OTel Operator, k8sattributes, tail sampling"],
    ["SRE (SLO / budget)", "3", "5 SLOs, burn rate, consumo por experimento, runbooks", "Multi-ventana, política de budget, postmortems"],
    ["AIOps", "4", "2σ + correlación + enriquecimiento; −87 % ruido; MTTD 86 s", "Estacionalidad, agrupación, RCA, auto-remediación"],
    ["Red", "3", "Flow Logs con metadatos, eBPF, L7, atribución IP/ASN", "Intranode visibility, Network Intelligence Center"],
    ["Seguridad", "2", "eBPF, fuerza bruta, CVEs, postura, dashboard", "SCC no disponible; hallazgos HIGH sin remediar"],
    ["DataOps", "2", "Pipeline con filtros y protección; métricas como código", "Retención, muestreo, costo, SLO del pipeline"],
    ["Resiliencia / Caos", "3", "2 experimentos automatizados, MTTD medido, cascada descubierta", "Caos continuo en CI, corrección de la cascada"],
  ], [20, 8, 40, 32], { center: [1] }),
  p("**Promedio actual: 3.0 / 5** (Definido), con Telemetría y AIOps en Cuantificado.", { para: { spacing: { before: 100, after: 100 } } }),
  table(["Mes", "Iniciativa", "Acciones principales", "KPI"], [
    ["1", "Remediar postura (Seguridad 2→3)", "Eliminar red default; control plane privado; TLS + Cloud Armor con rate limiting en /login; Cloud SQL privado con backups; imágenes parchadas/distroless", "0 hallazgos HIGH; 0 CVEs HIGH con fix"],
    ["1", "Corregir la cascada (Resiliencia 3→4)", "Deadlines y timeouts en servidor, bulkheads, circuit breaking, reintentos con presupuesto", "+100 ms en data-service → error rate < 1 %"],
    ["2", "DataOps (2→3)", "Tail sampling, retención por tipo de log, sink a BigQuery, costo de telemetría, SLO del pipeline", "−30 % costo/request; 0 spans de error perdidos"],
    ["2", "SRE (3→4) y OTel (3→4)", "Alertas multi-ventana, política de error budget en despliegues, postmortems; OTel Operator y exemplars", "100 % de incidentes con postmortem"],
    ["3", "Caos continuo y AIOps 2.0", "Chaos Mesh Schedule + CI con verificación de estado estable; baselines estacionales, RCA por topología, rollback automático", "MTTD < 60 s; precisión > 95 %; MTTR −50 %"],
  ], [7, 22, 47, 24], { center: [0] }),
  p("**Madurez esperada a 3 meses: 3.9 / 5.**", { para: { spacing: { before: 100 } } }),
];

const aws = [
  h1("8. Decisiones, limitaciones y equivalencia con AWS"),
  table(["Necesidad", "GCP (implementado)", "Equivalente en AWS"], [
    ["Orquestación", "GKE + Dataplane V2", "EKS + VPC CNI / Cilium"],
    ["Base de datos", "Cloud SQL + Auth Proxy + Query Insights", "RDS PostgreSQL + IAM auth + Performance Insights"],
    ["Service mesh", "Cloud Service Mesh (Envoy)", "AWS App Mesh / VPC Lattice"],
    ["Trazas, métricas, logs", "Cloud Trace, Managed Prometheus, Cloud Logging", "X-Ray / ADOT, Amazon Managed Prometheus, CloudWatch Logs"],
    ["Detección de anomalías", "Alertas PromQL + detector propio", "CloudWatch Anomaly Detection, DevOps Guru"],
    ["Red", "VPC Flow Logs", "VPC Flow Logs"],
    ["Seguridad", "Artifact Analysis, GKE Security Posture, chequeos propios (SCC sin organización)", "Inspector, Security Hub, GuardDuty"],
    ["Caos", "Chaos Mesh", "AWS Fault Injection Service"],
  ], [20, 40, 40]),
  space(60),
  bullet("**Solo GCP:** decisión de alcance del estudiante; la arquitectura es portable con los equivalentes de la tabla."),
  bullet("**Security Command Center:** requiere organización; sustituido sin perder las señales del dashboard."),
  bullet("**Fallas en el mesh:** Traffic Director propagó los cambios de VirtualService en 2–5 min, por lo que los experimentos usan Chaos Mesh y fallas en proceso con efecto inmediato."),
  bullet("**X-Forwarded-For:** el gateway gestionado no lo propaga; la atribución de clientes externos se hizo en la capa de red (externalTrafficPolicy=Local + Flow Logs)."),
  bullet("**Falsos positivos conocidos:** la alerta de \"origen no autorizado\" (que incluye pods efímeros sin metadatos en Flow Logs) se activa con los pods nuevos de un despliegue; queda como mejora correlacionarla con eventos de despliegue."),
  bullet("**Evidencia completa:** la bitácora del laboratorio (74 archivos de evidencia entre capturas y salidas de comandos) respalda cada cifra de este reporte."),
];

const conclusiones = [
  h1("9. Conclusiones"),
  bullet("La correlación por trace_id entre trazas, métricas, logs y consultas SQL convierte cada alerta en un punto de partida de diagnóstico, no en un síntoma aislado."),
  bullet("La detección dinámica con correlación redujo **87 %** el ruido y eliminó las páginas falsas; medirlo con una verdad de referencia basada en el impacto observado fue clave para no sobreestimar el resultado."),
  bullet("El MTTD depende tanto de la lógica como de la plataforma: las alertas gestionadas añadían minutos; un detector en tiempo real logró **69–86 s**."),
  bullet("Una alerta rápida no es necesariamente accionable: el diagnóstico tuvo que evolucionar para señalar la red o el servicio de origen."),
  bullet("Los experimentos de caos mostraron un riesgo real (falla en cascada ante +100 ms) que hoy encabeza el roadmap: la observabilidad sirvió para descubrir debilidades, no solo para vigilar."),
  space(80),
  p("**Entregables:** repositorio público con IaC, código de instrumentación, configuraciones y scripts (github.com/davasquezbel/obs-lab-final, tag v1.0); bitácora de evidencias con capturas y salidas de comandos; y video de demostración en vivo.", { run: { size: 20 }, align: AlignmentType.LEFT }),
];

// ── Documento ────────────────────────────────────────────────────────
const doc = new Document({
  creator: "David Vasquez",
  title: "Reporte final — Sistema observable de nivel producción en GCP",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, color: C.navy, font: FONT }, paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, color: C.blue, font: FONT }, paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [
    { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } },
    { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1080, hanging: 270 } } } },
  ] }] },
  sections: [
    { properties: { page: { size: { width: PAGE_W, height: 15840 }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
      children: cover },
    { properties: { page: { size: { width: PAGE_W, height: 15840 }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
      headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "Laboratorio Final · Observabilidad en Ambientes Productivos", size: 16, color: C.grey })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: C.grey })] })] }) },
      children: [...resumen, ...arquitectura, ...moduloA, ...moduloB, ...moduloC, ...moduloD, ...moduloE, ...aws, ...conclusiones] },
  ],
});
Packer.toBuffer(doc).then(b => { fs.writeFileSync(OUT, b); console.log("OK", OUT); });
