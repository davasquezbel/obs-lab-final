// Reporte final — formato APA 7 (cuerpo). La portada del estudiante se inserta después
// en lugar del párrafo marcador «§§PORTADA§§» (ver merge_cover.py).
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType,
  AlignmentType, HeadingLevel, BorderStyle, ShadingType, LevelFormat, Header, PageNumber,
  VerticalAlign, ExternalHyperlink, SectionType,
} = require("docx");

const IMG = path.join(__dirname, "img");
const OUT = process.argv[2] || path.join(__dirname, "apa_body.docx");
const V = JSON.parse(fs.readFileSync(path.join(__dirname, "validation.json"), "utf8"));
const REPO = "https://github.com/davasquezbel/obs-lab-final";
const VIDEO = "https://drive.google.com/file/d/1z7YlikvfqPayfZmV53sQsuWniBeFkX1g/view?usp=sharing";

// ── APA 7: Times New Roman 12, doble espacio, márgenes 1", sangría 0.5" ─────
const FONT = "Times New Roman";
const PAGE_W = 12240, PAGE_H = 15840, MARGIN = 1440;
const CONTENT_W = PAGE_W - 2 * MARGIN;            // 9360 DXA = 6.5"
const DOUBLE = 480, SINGLE = 240;

// Texto con **negritas**, *cursivas* y [[enlaces|url]]
function runs(text, base = {}) {
  const out = [];
  for (const part of text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|\[\[[^\]]+\]\])/g).filter(Boolean)) {
    if (part.startsWith("**")) out.push(new TextRun({ ...base, text: part.slice(2, -2), bold: true }));
    else if (part.startsWith("[[")) {
      const [label, url] = part.slice(2, -2).split("|");
      out.push(new ExternalHyperlink({ link: url || label, children: [new TextRun({ ...base, text: label, style: "Hyperlink" })] }));
    } else if (part.startsWith("*")) out.push(new TextRun({ ...base, text: part.slice(1, -1), italics: true }));
    else out.push(new TextRun({ ...base, text: part }));
  }
  return out;
}
// Párrafo APA: doble espacio, sangría de primera línea 0.5", alineado a la izquierda
const p = (text, o = {}) => new Paragraph({
  spacing: { line: DOUBLE, before: 0, after: 0 }, indent: o.noIndent ? undefined : { firstLine: 720 },
  alignment: o.align || AlignmentType.LEFT, keepNext: o.keepNext, children: runs(text, o.run),
});
// Nivel 1: centrado, negrita | Nivel 2: alineado a la izquierda, negrita
const h1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, children: [new TextRun(t)] });
const h2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, children: [new TextRun(t)] });
const bullet = text => new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { line: DOUBLE, after: 0 }, children: runs(text) });

// Tablas y figuras APA: número en negrita, título en cursiva (ambos arriba), nota debajo
let nTabla = 0, nFigura = 0;
const label = (kind, n, title) => [
  new Paragraph({ keepNext: true, spacing: { line: DOUBLE, before: 240, after: 0 }, children: [new TextRun({ text: `${kind} ${n}`, bold: true })] }),
  new Paragraph({ keepNext: true, spacing: { line: DOUBLE, after: 0 }, children: [new TextRun({ text: title, italics: true })] }),
];
const note = text => new Paragraph({ spacing: { line: DOUBLE, after: 240 }, children: runs(`*Nota.* ${text}`) });

function figure(file, widthIn, title, noteText) {
  nFigura++;
  const buf = fs.readFileSync(path.join(IMG, file));
  const [w, h] = dims(buf);
  const wpx = widthIn * 96, hpx = wpx * h / w;
  return [
    ...label("Figura", nFigura, title),
    new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, keepLines: true, spacing: { line: SINGLE, after: 60 },
      children: [new ImageRun({ type: file.endsWith(".png") ? "png" : "jpg", data: buf, transformation: { width: wpx, height: hpx },
        altText: { title, description: title, name: file } })] }),
    note(noteText),
  ];
}
function dims(buf) {
  if (buf[0] === 0x89) return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
  let i = 2;
  while (i < buf.length) {
    const m = buf[i + 1], len = buf.readUInt16BE(i + 2);
    if (m >= 0xC0 && m <= 0xC2) return [buf.readUInt16BE(i + 7), buf.readUInt16BE(i + 5)];
    i += 2 + len;
  }
  throw new Error("dimensiones");
}

// Tabla APA: solo líneas horizontales (arriba, bajo el encabezado y al final), sin sombreado
const line = { style: BorderStyle.SINGLE, size: 6, color: "000000" };
const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
function table(title, headers, rows, widthsPct, noteText, o = {}) {
  nTabla++;
  const widths = widthsPct.map(x => Math.round(CONTENT_W * x / 100));
  widths[widths.length - 1] += CONTENT_W - widths.reduce((a, b) => a + b, 0);
  const last = rows.length - 1;
  const cell = (text, i, kind, ri) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
    shading: { fill: "FFFFFF", type: ShadingType.CLEAR, color: "auto" },
    borders: {
      top: kind === "head" ? line : none, left: none, right: none,
      bottom: kind === "head" || ri === last ? line : none,
    },
    margins: { top: 40, bottom: 40, left: 80, right: 80 },
    children: [new Paragraph({ spacing: { line: SINGLE, after: 0 }, alignment: (o.center || []).includes(i) ? AlignmentType.CENTER : AlignmentType.LEFT,
      children: runs(String(text), { size: 20, bold: kind === "head" ? true : undefined }) })],
  });
  return [
    ...label("Tabla", nTabla, title),
    new Table({
      width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
      borders: { top: none, bottom: none, left: none, right: none, insideHorizontal: none, insideVertical: none },
      rows: [new TableRow({ tableHeader: true, children: headers.map((t, i) => cell(t, i, "head")) }),
        ...rows.map((r, ri) => new TableRow({ cantSplit: true, children: r.map((t, i) => cell(t, i, "body", ri)) }))],
    }),
    note(noteText),
  ];
}

// ── Contenido ─────────────────────────────────────────────────────────
const titulo = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { line: DOUBLE, after: 0 },
    children: [new TextRun({ text: "Sistema observable de nivel producción en Google Cloud", bold: true })] }),
];

const resumen = [
  h1("Resumen ejecutivo"),
  p("Se construyó y operó un sistema de tres microservicios (service-a, service-b y data-service) sobre Google Kubernetes Engine (GKE) con base de datos gestionada Cloud SQL, instrumentado de punta a punta con OpenTelemetry y conectado a Google Cloud Observability (Google Cloud, s.f.-a). Sobre esa base se agregaron un service mesh de capa 7 (Cloud Service Mesh con mTLS), detección de anomalías y correlación AIOps con alertas enriquecidas con el trace_id del request afectado, observabilidad de red y seguridad (VPC Flow Logs, eBPF, CVE y postura) y experimentos de Chaos Engineering para validar la detección en menos de dos minutos. Toda la infraestructura se definió como código con Terraform."),
  p("La actividad plantea Google Cloud y Amazon Web Services; por decisión del equipo se implementó **solo en Google Cloud** y la sección de decisiones documenta la equivalencia de cada componente en AWS (Amazon Web Services, s.f.). El código fuente, la infraestructura como código, las configuraciones y los scripts están en el repositorio público [[" + REPO + "|" + REPO + "]] (etiqueta v1.0), y la demostración en vivo puede consultarse en [[" + VIDEO + "|este video]] (Bedoya Flórez et al., 2026a, 2026b). La Tabla 1 resume el resultado frente a cada criterio de evaluación."),
  ...table("Resultados frente a los criterios de la rúbrica", ["Criterio", "Resultado obtenido"], [
    ["Arquitectura observable completa", "3 microservicios con OpenTelemetry (3 pilares correlacionados por trace_id), spans de base de datos con DB Semantic Conventions, Cloud Service Mesh con 100 % del tráfico este-oeste en mTLS y métricas L7."],
    ["AIOps: detección y correlación", "Línea base μ + 2σ y regla error_rate > baseline + 2σ AND p99 > SLO; −87 % de alertas ruidosas y 0 páginas falsas frente a umbrales estáticos; alertas con trace_id y diagnóstico."],
    ["Observabilidad de red y seguridad", "Flow Logs este-oeste y norte-sur, microsegmentación con logging eBPF (movimiento lateral detectado en 56 s), fuerza bruta (μ + 3σ), CVE y postura como métricas; tablero de golden signals de seguridad."],
    ["Chaos Engineering y MTTD", "Dos experimentos (+200 ms en service-b; 10 % de errores en data-service): MTTD de 69 s y 77 s; SLO degradado y consumo de 29.7 % y 11.9 % del error budget diario."],
    ["Madurez y roadmap", "Autoevaluación en 8 dominios: 3.0 / 5; roadmap a tres meses con objetivo 3.9."],
  ], [28, 72], "MTTD = tiempo medio de detección; SLO = objetivo de nivel de servicio. Elaboración propia."),
];

const arquitectura = [
  h1("Arquitectura"),
  p("La Figura 1 presenta la arquitectura desplegada en el proyecto obs-lab-final (región us-central1) y la Tabla 2 resume las decisiones de diseño de cada capa. La telemetría sigue el modelo de los tres pilares de Google Cloud Observability: trazas en Cloud Trace, métricas en Managed Service for Prometheus y logs estructurados en Cloud Logging (Google Cloud, s.f.-a)."),
  ...figure("arquitectura.png", 6.3, "Arquitectura observable desplegada en Google Cloud", "Elaboración propia."),
  ...table("Componentes y decisiones de diseño por capa", ["Capa", "Componentes", "Decisión clave"], [
    ["Cómputo y red", "GKE Standard zonal (3 × e2-standard-2), nodos privados, Dataplane V2 (eBPF), VPC dedicada, Cloud NAT", "Nodos sin IP pública; tráfico de salida observable vía NAT y Flow Logs"],
    ["Datos", "Cloud SQL PostgreSQL 16 (Query Insights) mediante Cloud SQL Auth Proxy", "Sin redes autorizadas: acceso solo por proxy + IAM (Workload Identity)"],
    ["Aplicación", "service-a (orquestador, /login), service-b (inventario), data-service (capa de datos)", "Solo data-service accede a la base de datos"],
    ["Telemetría", "SDK de OpenTelemetry → OpenTelemetry Collector → Cloud Trace y Managed Prometheus; logs JSON → Cloud Logging", "Campos especiales de Cloud Logging para enlazar logs y trazas"],
    ["Malla", "Cloud Service Mesh gestionado, ingress gateway, mTLS STRICT", "Reintentos solo ante fallas de transporte, para no ocultar errores"],
    ["Operación", "SLO, 11 políticas de alerta, alert-enricher (Cloud Run), aiops-detector, Chaos Mesh, security-exporter", "Todo como código (Terraform y manifiestos)"],
  ], [16, 46, 38], "Elaboración propia."),
];

const moduloA = [
  h1("Módulo A: arquitectura observable completa"),
  h2("Tres pilares correlacionados"),
  p("La propagación W3C Trace Context une los tres servicios en una misma traza. Cada consulta a Cloud SQL genera un span de tipo cliente con los atributos estables de las convenciones semánticas de OpenTelemetry para bases de datos (db.system.name, db.namespace, db.operation.name, db.collection.name y db.query.text), además de los atributos heredados (OpenTelemetry, s.f.). Las métricas RED (tasa, errores y duración) se publican por servicio, con buckets de histograma alineados al SLO de 300 ms, y los logs JSON incluyen trace_id y span_id para enlazarse con la traza. El comentario sqlcommenter envía el traceparent a Cloud SQL, por lo que Query Insights muestra cada consulta junto a su traza. La Figura 2 muestra una petición real y la Figura 3, los atributos del span de base de datos."),
  ...figure("E2-02_trace_cascada.jpg", 6.3, "Traza de una petición real a través de los tres servicios y Cloud SQL", "Captura de Cloud Trace. La petición recorre service-a → data-service (SELECT appdb.orders) → service-b → data-service (SELECT appdb.inventory)."),
  ...figure("E2-03_span_db_semconv.jpg", 5.4, "Atributos del span SELECT appdb.orders según las DB Semantic Conventions", "Captura de Cloud Trace."),
  h2("Service mesh de capa 7"),
  p("Cloud Service Mesh inyecta Envoy en todos los workloads. El modo mTLS STRICT rechaza las conexiones en texto plano desde pods fuera de la malla, cada servicio tiene identidad SPIFFE y Envoy publica métricas de capa 7 (tasa, códigos de respuesta y latencia) que alimentan la topología del mesh. El tablero de seguridad confirma que el 100 % del tráfico este-oeste de la aplicación viaja cifrado (Figura 4)."),
  ...figure("E3-06_mesh_mtls.jpg", 6.3, "Conexiones de service-a con mTLS e identidad SPIFFE", "Captura de la consola de Cloud Service Mesh."),
  p("Durante la implementación se resolvieron tres incidencias: el comentario de sqlcommenter rompía psycopg2 por el carácter % (detectado gracias a los mismos 5xx y logs), el mesh gestionado tardó cerca de 55 minutos en aprovisionarse y solo admite las API v1beta1, y su injector no preserva los sidecars nativos, por lo que el Cloud SQL Auth Proxy pasó a ser un contenedor regular."),
];

const moduloB = [
  h1("Módulo B: AIOps y detección automática de anomalías"),
  p("Se configuraron tres motores de alerta sobre las mismas métricas (Tabla 3). La regla de correlación solicitada en la actividad, error_rate > baseline + 2σ y p99 > SLO, produce las únicas alertas que generan página; las anomalías de una sola señal se notifican como advertencias."),
  ...table("Políticas de alerta por motor", ["Motor / política", "Regla", "Uso"], [
    ["[ESTÁTICA] error rate / latencia", "error_rate(1m) > 1 %; p99(1m) > 200 ms", "Línea base \"ingenua\" para medir ruido"],
    ["[AIOps] anomalía de error / latencia", "valor(2m) > max(μ₁ₕ + 2σ₁ₕ, piso)", "Advertencia"],
    ["[AIOps] crítica correlacionada", "error_rate > μ₁ₕ + 2σ₁ₕ AND p99 > SLO (300 ms)", "Página con trace_id"],
    ["[AIOps] burn rate", "Burn rate de 5 min del SLO de disponibilidad > 10x", "Página"],
    ["[AIOps-RT] detector propio", "Misma lógica, evaluada cada 15 s sobre Managed Prometheus", "Cumplir MTTD < 2 min"],
  ], [30, 46, 24], "μ₁ₕ y σ₁ₕ son la media y la desviación estándar de la última hora. Elaboración propia."),
  p("Cada alerta llega al servicio alert-enricher (Cloud Run), que busca en Cloud Logging el request fallido o lento, recupera su traza y produce un diagnóstico: el tiempo de red por salto (span cliente menos span servidor) o el origen del error (el span 5xx más profundo). El resultado se notifica por correo con el trace_id y el enlace a la traza."),
  h2("Reducción de alertas ruidosas"),
  p("Se ejecutó una prueba de 33 minutos con siete perturbaciones transitorias de una sola señal y un incidente real. La verdad de referencia fue la degradación multiseñal observada en service-a (errores > 5 % y p99 > 300 ms) y los tres motores se evaluaron con los mismos datos (Tabla 4). El resultado fue una reducción de 87 % en alertas ruidosas (de 15 a 2) y de 100 % en páginas ruidosas (de 15 a 0), detectando los dos eventos reales. Las políticas PromQL de Cloud Monitoring agregaron entre 2.5 y 4 minutos de evaluación pese a que la ingesta tenía solo 3–7 s de retraso, por lo que se construyó un detector en tiempo real para cumplir el MTTD (Figura 5)."),
  ...table("Comparación cuantitativa de los motores de alerta", ["Motor", "Alertas", "Ruido", "Precisión", "Páginas", "Páginas ruidosas", "MTTD real"], [
    ["Estático", "29", "15", "48 %", "29", "15", "212 s"],
    ["AIOps (Cloud Monitoring)", "17", "2", "88 %", "5", "0", "308 s"],
    ["AIOps-RT (detector)", "19", "2", "89 %", "5", "0", "86 s"],
  ], [26, 11, 10, 12, 11, 15, 15], "Precisión = alertas verdaderas / alertas totales. Elaboración propia a partir del backtest sobre Managed Service for Prometheus.", { center: [1, 2, 3, 4, 5, 6] }),
  ...figure("E4-07a_alertas_enriquecidas_lista.jpg", 6.3, "Alertas críticas enriquecidas con trace_id en Cloud Logging", "AIOps-RT llega entre 2 y 4 minutos antes que la política gestionada. Captura de Logs Explorer."),
];

const moduloC = [
  h1("Módulo C: observabilidad de red y seguridad"),
  p("La Tabla 5 resume las señales de seguridad implementadas. La microsegmentación usa NetworkPolicy con denegación por defecto y el registro de decisiones de GKE Dataplane V2, basado en eBPF, que registra cada conexión bloqueada con el pod de origen, el destino y el puerto sin instrumentar las aplicaciones (Tigera, s.f.). Los VPC Flow Logs aportan el tráfico este-oeste con metadatos de pod y el tráfico norte-sur con la IP, la ciudad y el sistema autónomo del cliente."),
  ...table("Señales de seguridad, fuentes y alertas", ["Señal", "Fuente", "Alerta / panel"], [
    ["Tráfico este-oeste y norte-sur", "VPC Flow Logs (5 s, 50 %) con metadatos de pod y workload", "Paneles de tráfico; flujos desde namespaces no autorizados"],
    ["Movimiento lateral", "NetworkPolicy default-deny + NetworkLogging de Dataplane V2 (eBPF)", "Alerta crítica detectada en 56 s"],
    ["Fuerza bruta en /login", "auth_attempts_total + VPC Flow Logs (IP, ciudad, ASN)", "Alerta μ + 3σ; atacante identificado (Medellín, ASN 13489)"],
    ["CVE activos", "Artifact Analysis (escaneo automático)", "472 CVE (42 HIGH, 0 CRITICAL, 70 con corrección)"],
    ["Postura", "GKE Security Posture + chequeos propios estilo Security Health Analytics", "9 hallazgos (4 HIGH) publicados como métricas"],
    ["Cifrado este-oeste", "Métricas L7 de Envoy", "100 % del tráfico con mTLS"],
  ], [22, 42, 36], "Elaboración propia."),
  ...figure("E5-06c_dashboard_seguridad_mtls.jpg", 6.3, "Tablero \"Golden Signals de Seguridad\" durante la simulación de ataques", "Captura de Cloud Monitoring."),
  p("Security Command Center no pudo activarse porque requiere una organización de Google Cloud, es decir, Google Workspace o Cloud Identity con un dominio verificado (Google Cloud, s.f.-b), y la cuenta del laboratorio no la tiene. Su función se cubrió con GKE Security Posture, que además reportó la vulnerabilidad CVE-2024-6387 en 90 resultados y el contenedor privilegiado de Chaos Mesh (Figura 7), con Artifact Analysis y con chequeos propios publicados como métricas. Los hallazgos reales alimentan el roadmap: la red default con SSH y RDP abiertos a Internet, el control plane público, el gateway HTTP sin TLS y Cloud SQL sin copias de seguridad."),
  ...figure("E5-09_gke_security_posture.jpg", 6.0, "Panel de GKE Security Posture", "Hallazgos de configuración de workloads y CVE críticos. Captura de la consola de GKE."),
];

const moduloD = [
  h1("Módulo D: Chaos Engineering controlado"),
  p("Los experimentos siguieron los principios de Chaos Engineering: hipótesis de estado estable, variables del mundo real, radio de impacto acotado y reversión automática (Basiri et al., 2016). Se ejecutaron en el proyecto sandbox dedicado con Chaos Mesh (Chaos Mesh, s.f.). El segundo experimento inyecta el error dentro del proceso porque HTTPChaos no intercepta tráfico con mTLS STRICT (comportamiento verificado) y desactivar mTLS degradaría la seguridad. La Figura 8 muestra el impacto y la Tabla 6, el análisis de SLO, error budget y MTTD (Beyer et al., 2016)."),
  ...figure("chaos.png", 6.3, "Impacto de los experimentos en service-a y llegada de la primera alerta de cada motor", "p99 de latencia y tasa de errores de service-a. Elaboración propia con datos de Managed Service for Prometheus."),
  ...table("Resultados de los experimentos de caos", ["Aspecto", "Exp. 1: +200 ms de red en service-b", "Exp. 2: 10 % de errores en data-service"], [
    ["Mecanismo", "Chaos Mesh NetworkChaos (tc), 302 s", "Falla en proceso con TTL, 304 s"],
    ["p99 de service-a", "74 ms → 534 ms", "78 ms → 88 ms"],
    ["SLI de disponibilidad", "100 % → 100 %", "99.93 % → 85.93 %"],
    ["SLI de latencia ≤ 300 ms", "100 % → 29.17 %", "100 % → 100 %"],
    ["¿Se degradó el SLO?", "Sí, el de latencia (objetivo 99 %)", "Sí, el de disponibilidad (objetivo 99.5 %)"],
    ["¿Se consumió error budget?", "1.282 requests lentos = 29.7 % del budget diario; burn rate 70.8x (lo agotaría en 20 min)", "256 errores = 11.9 % del budget diario; burn rate 28.1x (lo agotaría en 51 min)"],
    ["MTTD (AIOps-RT / estática / AIOps CM)", "69 s / 195 s / 243 s", "77 s / 196 s / 246 s"],
    ["¿La alerta fue accionable?", V.experiments.exp1.replace(/\*\*/g, ""), V.experiments.exp2.replace(/\*\*/g, "")],
  ], [22, 39, 39], "SLI = indicador de nivel de servicio; CM = Cloud Monitoring. El budget diario en régimen es de 2.160 errores y 4.320 requests lentos. Elaboración propia."),
  p("Solo el detector en tiempo real cumplió el objetivo de MTTD. La correlación funcionó como se diseñó: ningún experimento de una sola señal generó página, sino advertencias con trace_id. La accionabilidad requirió iterar: el primer diagnóstico, basado en el span más lento, apuntaba a una consulta de 7 ms cuando el problema era la red, y se reemplazó por el análisis por saltos. Además, un 10 % de errores en data-service se amplificó a cerca de 14 % en service-a porque cada pedido lo invoca dos veces."),
  p("Durante la prueba de ruido se descubrió una falla en cascada: apenas 100 ms de latencia de red en data-service produjeron cerca de 90 % de errores en service-a y consultas de hasta 10 s (Figura 9), por las consultas síncronas, la ausencia de deadlines y los reintentos que amplifican la carga. Es la primera iniciativa del roadmap. El error budget mostrado en la consola ya estaba agotado por los incidentes de puesta en marcha, por lo que el consumo se midió por experimento frente al budget diario en régimen."),
  ...figure("E4-10_traza_desde_alerta.jpg", 6.3, "Traza señalada por una alerta crítica durante la falla en cascada", "SELECT appdb.inventory de 5–10 s, reintento de service-b y errores propagados hasta service-a. Captura de Cloud Trace."),
];

const moduloE = [
  h1("Módulo E: madurez de observabilidad y roadmap"),
  p("La Tabla 7 presenta la autoevaluación frente a los ocho dominios del Observability Foundation Blueprint con una escala de 1 a 5 (1 inicial, 2 gestionado, 3 definido, 4 cuantificado y 5 optimizado). El promedio actual es de 3.0 sobre 5: telemetría y AIOps alcanzan el nivel cuantificado, mientras que seguridad y DataOps, entendido como la gestión de los datos de observabilidad a escala (Karumuri et al., 2021), son las principales brechas."),
  ...table("Autoevaluación de madurez de observabilidad", ["Dominio", "Nivel", "Evidencia", "Brecha principal"], [
    ["Telemetría (3 pilares)", "4", "Correlación por trace_id, spans de BD, Query Insights enlazado, verificación automatizada", "Exemplars, logs vía OTLP"],
    ["OpenTelemetry", "3", "SDK manual y automático, DB semconv, Collector gateway", "OTel Operator, k8sattributes, tail sampling"],
    ["SRE (SLO / budget)", "3", "5 SLO, burn rate, consumo por experimento, runbooks", "Alertas multiventana, política de budget, postmortems"],
    ["AIOps", "4", "2σ, correlación y enriquecimiento; −87 % de ruido; MTTD 86 s", "Estacionalidad, agrupación, RCA, autorremediación"],
    ["Red", "3", "Flow Logs con metadatos, eBPF, L7, atribución IP/ASN", "Intranode visibility, Network Intelligence Center"],
    ["Seguridad", "2", "eBPF, fuerza bruta, CVE, postura, tablero", "SCC no disponible; hallazgos HIGH sin remediar"],
    ["DataOps", "2", "Pipeline con filtros y protección; métricas como código", "Retención, muestreo, costo, SLO del pipeline"],
    ["Resiliencia / caos", "3", "2 experimentos automatizados, MTTD medido, cascada descubierta", "Caos continuo en CI, corrección de la cascada"],
  ], [20, 8, 40, 32], "Escala: 1 inicial, 2 gestionado, 3 definido, 4 cuantificado, 5 optimizado. Elaboración propia.", { center: [1] }),
  p("El roadmap a tres meses (Tabla 8) prioriza primero los riesgos (postura de seguridad y la falla en cascada) y luego el gobierno de los datos de telemetría y la automatización. Con estas iniciativas la madurez esperada es de 3.9 sobre 5."),
  ...table("Roadmap de mejora a tres meses", ["Mes", "Iniciativa", "Acciones principales", "KPI"], [
    ["1", "Remediar la postura (seguridad 2→3)", "Eliminar la red default; control plane privado; TLS y Cloud Armor con rate limiting en /login; Cloud SQL privado con backups; imágenes parchadas o distroless", "0 hallazgos HIGH; 0 CVE HIGH con corrección"],
    ["1", "Corregir la cascada (resiliencia 3→4)", "Deadlines y timeouts en el servidor, bulkheads, circuit breaking, reintentos con presupuesto", "+100 ms en data-service → error rate < 1 %"],
    ["2", "DataOps (2→3)", "Tail sampling, retención por tipo de log, exportación a BigQuery, costo de telemetría, SLO del pipeline", "−30 % de costo por request; 0 spans de error perdidos"],
    ["2", "SRE (3→4) y OpenTelemetry (3→4)", "Alertas multiventana, política de error budget en despliegues, postmortems; OTel Operator y exemplars", "100 % de incidentes con postmortem"],
    ["3", "Caos continuo y AIOps 2.0", "Chaos Mesh Schedule y CI con verificación de estado estable; líneas base estacionales, RCA por topología, rollback automático", "MTTD < 60 s; precisión > 95 %; MTTR −50 %"],
  ], [7, 22, 47, 24], "KPI = indicador clave de desempeño; MTTR = tiempo medio de recuperación. Elaboración propia.", { center: [0] }),
];

const decisiones = [
  h1("Decisiones, limitaciones y equivalencia con AWS"),
  p("La Tabla 9 muestra el equivalente en AWS de cada componente implementado en Google Cloud, siguiendo las buenas prácticas de observabilidad de AWS (Amazon Web Services, s.f.). A continuación se listan las decisiones y limitaciones más relevantes."),
  ...table("Equivalencia de componentes entre Google Cloud y AWS", ["Necesidad", "Google Cloud (implementado)", "Equivalente en AWS"], [
    ["Orquestación", "GKE + Dataplane V2", "EKS + VPC CNI / Cilium"],
    ["Base de datos", "Cloud SQL + Auth Proxy + Query Insights", "RDS PostgreSQL + IAM auth + Performance Insights"],
    ["Service mesh", "Cloud Service Mesh (Envoy)", "AWS App Mesh / VPC Lattice"],
    ["Trazas, métricas y logs", "Cloud Trace, Managed Prometheus, Cloud Logging", "X-Ray / ADOT, Amazon Managed Prometheus, CloudWatch Logs"],
    ["Detección de anomalías", "Alertas PromQL + detector propio", "CloudWatch Anomaly Detection, DevOps Guru"],
    ["Red", "VPC Flow Logs", "VPC Flow Logs"],
    ["Seguridad", "Artifact Analysis, GKE Security Posture, chequeos propios", "Inspector, Security Hub, GuardDuty"],
    ["Caos", "Chaos Mesh", "AWS Fault Injection Service"],
  ], [22, 39, 39], "Elaboración propia."),
  bullet("**Solo Google Cloud:** decisión de alcance del equipo; la arquitectura es portable con los equivalentes de la Tabla 9."),
  bullet("**Security Command Center:** requiere organización; se sustituyó sin perder las señales del tablero."),
  bullet("**Fallas en el mesh:** Traffic Director propagó los cambios de VirtualService en 2–5 min, por lo que los experimentos usan Chaos Mesh y fallas en proceso con efecto inmediato."),
  bullet("**X-Forwarded-For:** el gateway gestionado no lo propaga; la atribución de clientes externos se hizo en la capa de red (externalTrafficPolicy=Local y Flow Logs)."),
  bullet("**Falsos positivos conocidos:** la alerta de origen no autorizado, que incluye pods efímeros sin metadatos en Flow Logs, se activa con los pods nuevos de un despliegue."),
  bullet("**Correos suprimidos:** la alerta basada en logs abre un solo incidente mientras sigan llegando coincidencias; los diagnósticos posteriores quedaron en Cloud Logging pero no generaron correo."),
];

const conclusiones = [
  h1("Conclusiones"),
  p("La correlación por trace_id entre trazas, métricas, logs y consultas SQL convierte cada alerta en un punto de partida de diagnóstico y no en un síntoma aislado. La detección dinámica con correlación redujo el ruido en 87 % y eliminó las páginas falsas; medirlo con una verdad de referencia basada en el impacto observado fue clave para no sobreestimar el resultado."),
  p("El MTTD depende tanto de la lógica de detección como de la plataforma: las alertas gestionadas añadían minutos, mientras que un detector en tiempo real logró entre 69 y 86 s. Una alerta rápida tampoco es necesariamente accionable: el diagnóstico tuvo que evolucionar para señalar la red o el servicio de origen. Finalmente, los experimentos de caos revelaron un riesgo real, la falla en cascada ante 100 ms de latencia, que hoy encabeza el roadmap: la observabilidad sirvió para descubrir debilidades y no solo para vigilar el sistema."),
  p("Los entregables son el repositorio público con la infraestructura como código, el código de instrumentación, las configuraciones y los scripts ([[" + REPO + "|" + REPO + "]], etiqueta v1.0), la bitácora de evidencias (74 archivos entre capturas y salidas de comandos) y el video de demostración en vivo ([[" + VIDEO + "|" + VIDEO + "]])."),
];

// Referencias APA 7 (orden alfabético, sangría francesa de 0.5")
const ref = text => new Paragraph({ spacing: { line: DOUBLE, after: 0 }, indent: { left: 720, hanging: 720 }, children: runs(text) });
const referencias = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("Referencias")] }),
  ref("Amazon Web Services. (s.f.). *AWS observability best practices*. [[https://aws-observability.github.io/observability-best-practices/|https://aws-observability.github.io/observability-best-practices/]]"),
  ref("Basiri, A., Behnam, N., de Rooij, R., Hochstein, L., Kosewski, L., Reynolds, J., & Rosenthal, C. (2016). Chaos engineering. *IEEE Software, 33*(3), 35–41. [[https://doi.org/10.1109/MS.2016.60|https://doi.org/10.1109/MS.2016.60]]"),
  ref("Bedoya Flórez, S., Cobos Suárez, S. A., & Vásquez Beltrán, D. A. (2026a). *Demostración en vivo del laboratorio final de observabilidad* [Video]. Google Drive. [[" + VIDEO + "|" + VIDEO + "]]"),
  ref("Bedoya Flórez, S., Cobos Suárez, S. A., & Vásquez Beltrán, D. A. (2026b). *obs-lab-final: sistema observable de nivel producción en GCP* (Versión 1.0) [Software]. GitHub. [[" + REPO + "|" + REPO + "]]"),
  ref("Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (Eds.). (2016). *Site reliability engineering: How Google runs production systems*. O'Reilly Media."),
  ref("Chaos Mesh. (s.f.). *Chaos Mesh documentation*. [[https://chaos-mesh.org/docs/|https://chaos-mesh.org/docs/]]"),
  ref("Google Cloud. (s.f.-a). *Google Cloud Observability documentation*. [[https://cloud.google.com/stackdriver/docs|https://cloud.google.com/stackdriver/docs]]"),
  ref("Google Cloud. (s.f.-b). *Security Command Center overview*. [[https://cloud.google.com/security-command-center/docs/concepts-security-command-center-overview|https://cloud.google.com/security-command-center/docs/concepts-security-command-center-overview]]"),
  ref("Karumuri, S., Solleza, F., Zdonik, S., & Tatbul, N. (2021). Towards observability data management at scale. *ACM SIGMOD Record*, *49*(4), 18–23. [[https://doi.org/10.1145/3456859.3456863|https://doi.org/10.1145/3456859.3456863]]"),
  ref("OpenTelemetry. (s.f.). *Semantic conventions for database client calls*. [[https://opentelemetry.io/docs/specs/semconv/database/|https://opentelemetry.io/docs/specs/semconv/database/]]"),
  ref("Tigera. (s.f.). *eBPF and network observability*. [[https://www.tigera.io/learn/guides/ebpf/|https://www.tigera.io/learn/guides/ebpf/]]"),
];

// ── Documento ────────────────────────────────────────────────────────
const page = { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN, header: 720, footer: 720 } };
const header = new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ children: [PageNumber.CURRENT] })] })] });

const doc = new Document({
  creator: "Sebastián Bedoya Flórez, Sergio Andrés Cobos Suárez, David Aníbal Vásquez Beltrán",
  title: "Sistema observable de nivel producción en Google Cloud",
  styles: {
    default: { document: { run: { font: FONT, size: 24 }, paragraph: { spacing: { line: DOUBLE } } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: true, color: "000000" },
        paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 240, after: 0, line: DOUBLE }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: true, color: "000000" },
        paragraph: { alignment: AlignmentType.LEFT, spacing: { before: 0, after: 0, line: DOUBLE }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [
    { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
  ] }] },
  sections: [
    { properties: { page }, headers: { default: header },
      children: [new Paragraph({ children: [new TextRun("§§PORTADA§§")] })] },
    { properties: { page, type: SectionType.NEXT_PAGE }, headers: { default: header },
      children: [...titulo, ...resumen, ...arquitectura, ...moduloA, ...moduloB, ...moduloC, ...moduloD, ...moduloE,
        ...decisiones, ...conclusiones, ...referencias] },
  ],
});
Packer.toBuffer(doc).then(b => { fs.writeFileSync(OUT, b); console.log("OK", OUT, "| tablas", nTabla, "| figuras", nFigura); });
