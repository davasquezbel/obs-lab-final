"""
Bootstrap de OpenTelemetry común a los tres microservicios.

Pilares:
  - Trazas   → OTLP/gRPC → OTel Collector → Cloud Trace
  - Métricas → OTLP/gRPC → OTel Collector → Managed Service for Prometheus
  - Logs     → JSON en stdout → agente de GKE → Cloud Logging
               (con los campos especiales que Cloud Logging usa para enlazar log ↔ traza)
"""

import logging
import os
import time

from fastapi import FastAPI, Request
from pythonjsonlogger import jsonlogger

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "sandbox")

# Buckets alineados con el SLO de latencia (p99 < 300 ms) para que el
# percentil calculado por PromQL tenga resolución alrededor del umbral.
LATENCY_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3,
                   0.4, 0.5, 0.75, 1.0, 2.5, 5.0]


class GcpJsonFormatter(jsonlogger.JsonFormatter):
    """Log JSON con trace_id/span_id y los campos que Cloud Logging reconoce."""

    def __init__(self, service_name: str):
        super().__init__("%(message)s")
        self.service_name = service_name

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["severity"] = record.levelname
        log_record["logger"] = record.name
        log_record["service"] = self.service_name
        log_record["version"] = APP_VERSION
        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.is_valid:
            trace_id = format(ctx.trace_id, "032x")
            span_id = format(ctx.span_id, "016x")
            log_record["trace_id"] = trace_id
            log_record["span_id"] = span_id
            # Campos especiales → enlace automático log ↔ traza en la consola
            log_record["logging.googleapis.com/trace"] = f"projects/{PROJECT_ID}/traces/{trace_id}"
            log_record["logging.googleapis.com/spanId"] = span_id
            log_record["logging.googleapis.com/trace_sampled"] = ctx.trace_flags.sampled


class Telemetry:
    def __init__(self, service_name: str):
        self.service_name = service_name

        # Resource: identidad común a todas las señales. Resource.create() además
        # incorpora OTEL_RESOURCE_ATTRIBUTES (k8s.namespace.name, k8s.pod.name).
        resource = Resource.create({
            SERVICE_NAME: service_name,
            SERVICE_VERSION: APP_VERSION,
            "deployment.environment.name": ENVIRONMENT,
            "cloud.provider": "gcp",
            "cloud.platform": "gcp_kubernetes_engine",
        })

        self.tracer_provider = TracerProvider(resource=resource)
        self.tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
        )
        trace.set_tracer_provider(self.tracer_provider)
        self.tracer = trace.get_tracer(service_name, APP_VERSION)

        self.meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=OTEL_ENDPOINT, insecure=True),
                export_interval_millis=10_000,
            )],
            views=[View(instrument_name="*duration",
                        aggregation=ExplicitBucketHistogramAggregation(LATENCY_BUCKETS))],
        )
        metrics.set_meter_provider(self.meter_provider)
        self.meter = metrics.get_meter(service_name, APP_VERSION)

        handler = logging.StreamHandler()
        handler.setFormatter(GcpJsonFormatter(service_name))
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
        # El access log de uvicorn se reemplaza por el log estructurado del middleware
        logging.getLogger("uvicorn.access").disabled = True
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.logger = logging.getLogger(service_name)

        # SLIs RED (Rate, Errors, Duration) del lado servidor
        self.requests = self.meter.create_counter(
            "http_server_requests",
            description="Requests HTTP atendidos (SLI de disponibilidad / error rate)",
        )
        self.duration = self.meter.create_histogram(
            "http_server_request_duration",
            unit="s",
            description="Latencia de requests HTTP (SLI de latencia p50/p95/p99)",
        )

    def instrument(self, app: FastAPI) -> None:
        """Middleware RED + auto-instrumentación FastAPI (el span queda como padre)."""

        @app.middleware("http")
        async def red_metrics(request: Request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            start = time.perf_counter()
            status = 500
            try:
                response = await call_next(request)
                status = response.status_code
                return response
            finally:
                elapsed = time.perf_counter() - start
                route = request.scope.get("route")
                attrs = {
                    "http_route": route.path if route else "unmatched",
                    "http_method": request.method,
                    "http_status_code": str(status),
                    "status_class": f"{status // 100}xx",
                }
                self.requests.add(1, attrs)
                self.duration.record(elapsed, attrs)
                level = logging.ERROR if status >= 500 else logging.INFO
                self.logger.log(level, "request completed", extra={
                    **attrs,
                    "latency_ms": round(elapsed * 1000, 2),
                    "client_ip": request.headers.get("x-forwarded-for",
                                                     request.client.host if request.client else ""),
                })

        # exclude_spans: omite los spans internos ASGI "http send/receive" (ruido)
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=self.tracer_provider, excluded_urls="health",
            exclude_spans=["send", "receive"],
        )

    def current_trace_id(self) -> str:
        return format(trace.get_current_span().get_span_context().trace_id, "032x")

    def shutdown(self) -> None:
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
