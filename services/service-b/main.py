"""
service-b: servicio de inventario.

Consulta la disponibilidad en data-service (propagación W3C TraceContext vía httpx
auto-instrumentado) y aplica la regla de negocio de disponibilidad.
Objetivo del experimento de caos 1 (latencia de red de 200 ms).
"""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from common.telemetry import Telemetry

SERVICE = "service-b"
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8002")
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "10"))

tel = Telemetry(SERVICE)
logger, tracer = tel.logger, tel.tracer
HTTPXClientInstrumentor().instrument(tracer_provider=tel.tracer_provider)

stock_checks = tel.meter.create_counter(
    "inventory_stock_checks",
    description="Evaluaciones de stock por resultado",
)

client: httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = httpx.AsyncClient(base_url=DATA_SERVICE_URL, timeout=3.0)
    yield
    await client.aclose()
    tel.shutdown()


app = FastAPI(title="service-b", version=os.getenv("APP_VERSION", "1.0.0"), lifespan=lifespan)
tel.instrument(app)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE}


@app.get("/inventory/{product_id}")
async def get_inventory(product_id: str):
    try:
        resp = await client.get(f"/data/inventory/{product_id}")
    except httpx.HTTPError as e:
        logger.error("data-service no disponible", extra={"error": str(e), "product_id": product_id})
        raise HTTPException(status_code=503, detail="data-service unavailable")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    if resp.status_code >= 500:
        logger.error("data-service respondió error",
                     extra={"upstream_status": resp.status_code, "product_id": product_id})
        raise HTTPException(status_code=502, detail="data-service error")

    item = resp.json()
    with tracer.start_as_current_span("inventory.availability.evaluate") as span:
        available = item["available"]
        status = "OUT_OF_STOCK" if available == 0 else (
            "LOW_STOCK" if available < LOW_STOCK_THRESHOLD else "IN_STOCK")
        span.set_attribute("inventory.product_id", product_id)
        span.set_attribute("inventory.available", available)
        span.set_attribute("inventory.status", status)
        stock_checks.add(1, {"stock_status": status})

    return {**item, "stock_status": status}
