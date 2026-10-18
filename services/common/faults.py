"""
Inyección de fallas en proceso (chaos a nivel de aplicación).

Por qué existe: HTTPChaos de Chaos Mesh no puede interceptar tráfico HTTP cuando el
pod está en Cloud Service Mesh con mTLS STRICT (el tráfico llega cifrado y redirigido
por Envoy). Para inyectar errores HTTP sin desactivar mTLS, el servicio expone un
endpoint de control protegido por token, con duración acotada (rollback automático
como el TTL de Chaos Mesh).

Uso (desde scripts/app-fault.sh, vía kubectl exec en cada pod):
  POST /chaos/fault  {"error_rate": 0.1, "latency_ms": 0, "latency_rate": 0, "duration_s": 300}
  Header: x-chaos-token: <CHAOS_TOKEN>

IMPORTANTE: install() debe llamarse ANTES de Telemetry.instrument() para que el
middleware quede por dentro del middleware RED y los errores inyectados se midan.
"""

import asyncio
import os
import random
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace

_state = {"error_rate": 0.0, "latency_ms": 0, "latency_rate": 0.0, "until": 0.0}


def install(app: FastAPI, logger) -> None:
    token = os.getenv("CHAOS_TOKEN", "")

    @app.post("/chaos/fault")
    async def set_fault(request: Request):
        if not token or request.headers.get("x-chaos-token") != token:
            raise HTTPException(status_code=403, detail="forbidden")
        body = await request.json()
        duration = max(0, min(int(body.get("duration_s", 60)), 1800))
        _state.update(
            error_rate=min(max(float(body.get("error_rate", 0)), 0.0), 1.0),
            latency_ms=max(int(body.get("latency_ms", 0)), 0),
            latency_rate=min(max(float(body.get("latency_rate", 0)), 0.0), 1.0),
            until=time.time() + duration,
        )
        logger.warning("chaos: falla activada", extra={"event": "chaos.fault", **_state,
                                                        "duration_s": duration})
        return {**_state, "duration_s": duration}

    @app.get("/chaos/fault")
    async def get_fault():
        return {**_state, "active": time.time() < _state["until"]}

    @app.middleware("http")
    async def inject(request: Request, call_next):
        path = request.url.path
        if time.time() < _state["until"] and not path.startswith(("/chaos", "/health")):
            span = trace.get_current_span()
            if _state["latency_ms"] and random.random() < _state["latency_rate"]:
                span.set_attribute("chaos.injected", "latency")
                await asyncio.sleep(_state["latency_ms"] / 1000)
            if random.random() < _state["error_rate"]:
                span.set_attribute("chaos.injected", "error")
                return JSONResponse({"detail": "chaos: error inyectado"}, status_code=500)
        return await call_next(request)
