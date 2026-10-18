"""
service-a: orquestador / punto de entrada (tráfico N-S).

GET  /order/{id}  → data-service (pedido) → service-b (inventario) → respuesta consolidada
POST /login       → autenticación de demostración; los intentos fallidos alimentan
                    las Golden Signals de Seguridad (Módulo C).
"""

import hashlib
import hmac
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import BaseModel

from common.telemetry import Telemetry, client_ip

SERVICE = "service-a"
SERVICE_B_URL = os.getenv("SERVICE_B_URL", "http://service-b:8001")
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8002")
# Usuarios de prueba "usuario:clave,usuario2:clave2" (inyectados desde un Secret de K8s)
AUTH_USERS = dict(u.split(":", 1) for u in os.getenv("AUTH_USERS", "").split(",") if ":" in u)

tel = Telemetry(SERVICE)
logger, tracer = tel.logger, tel.tracer
HTTPXClientInstrumentor().instrument(tracer_provider=tel.tracer_provider)

auth_attempts = tel.meter.create_counter(
    "auth_attempts",
    description="Intentos de autenticación por resultado (success / failure)",
)

data_client: httpx.AsyncClient
inventory_client: httpx.AsyncClient


class LoginRequest(BaseModel):
    username: str
    password: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    global data_client, inventory_client
    data_client = httpx.AsyncClient(base_url=DATA_SERVICE_URL, timeout=3.0)
    inventory_client = httpx.AsyncClient(base_url=SERVICE_B_URL, timeout=3.0)
    yield
    await data_client.aclose()
    await inventory_client.aclose()
    tel.shutdown()


app = FastAPI(title="service-a", version=os.getenv("APP_VERSION", "1.0.0"), lifespan=lifespan)
tel.instrument(app)


async def _call(client: httpx.AsyncClient, path: str, upstream: str) -> dict:
    try:
        resp = await client.get(path)
    except httpx.HTTPError as e:
        logger.error("Upstream no disponible", extra={"upstream": upstream, "error": str(e)})
        raise HTTPException(status_code=503, detail=f"{upstream} unavailable")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=resp.json().get("detail", "not found"))
    if resp.status_code >= 400:
        logger.error("Upstream respondió error",
                     extra={"upstream": upstream, "upstream_status": resp.status_code})
        raise HTTPException(status_code=502, detail=f"{upstream} error {resp.status_code}")
    return resp.json()


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE}


@app.get("/order/{order_id}")
async def get_order(order_id: int):
    order = await _call(data_client, f"/data/orders/{order_id}", "data-service")
    inventory = await _call(inventory_client, f"/inventory/{order['product_id']}", "service-b")

    with tracer.start_as_current_span("order.assemble") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("order.status", order["status"])
        span.set_attribute("inventory.stock_status", inventory["stock_status"])

    logger.info("Pedido consolidado", extra={"order_id": order_id, "product_id": order["product_id"]})
    return {"order": order, "inventory": inventory, "trace_id": tel.current_trace_id()}


@app.post("/login")
async def login(body: LoginRequest, request: Request):
    source_ip = client_ip(request)
    expected = AUTH_USERS.get(body.username)
    ok = expected is not None and hmac.compare_digest(expected, body.password)
    result = "success" if ok else "failure"
    auth_attempts.add(1, {"auth_result": result, "auth_method": "password"})

    # Nunca se registra la clave; el usuario se registra como hash corto
    user_ref = hashlib.sha256(body.username.encode()).hexdigest()[:12]
    log = logger.info if ok else logger.warning
    log("auth attempt", extra={"event": "auth.login", "auth_result": result,
                               "user_ref": user_ref, "client_ip": source_ip,
                               "xff": request.headers.get("x-forwarded-for", ""),
                               "x_envoy_external_address": request.headers.get("x-envoy-external-address", "")})
    if not ok:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"status": "authenticated"}
