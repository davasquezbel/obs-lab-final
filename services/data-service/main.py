"""
data-service: capa de acceso a datos sobre GCP Cloud SQL (PostgreSQL 16).

- Conexión vía Cloud SQL Auth Proxy (sidecar) en 127.0.0.1:5432, identidad por Workload Identity.
- Cada query genera un span CLIENT con OTel Database Semantic Conventions
  (atributos estables + legacy para compatibilidad con backends antiguos).
- sqlcommenter: el traceparent viaja como comentario SQL, lo que permite a
  Cloud SQL Query Insights enlazar cada query con su traza en Cloud Trace.
"""

import os
import time
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import quote

import psycopg2
from psycopg2 import pool
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

from common.telemetry import Telemetry

SERVICE = "data-service"
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "appdb")
DB_USER = os.getenv("DB_USER", "app")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
CLOUDSQL_INSTANCE = os.getenv("CLOUDSQL_INSTANCE", "")

tel = Telemetry(SERVICE)
logger, tracer = tel.logger, tel.tracer

db_duration = tel.meter.create_histogram(
    "db_client_operation_duration",
    unit="s",
    description="Duración de operaciones contra Cloud SQL",
)
db_errors = tel.meter.create_counter(
    "db_client_errors",
    description="Errores de base de datos por tipo",
)

_pool: pool.ThreadedConnectionPool | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
    price NUMERIC(10,2) NOT NULL);
CREATE TABLE IF NOT EXISTS inventory (
    product_id TEXT PRIMARY KEY REFERENCES products(id), available INT NOT NULL,
    warehouse TEXT NOT NULL, last_updated TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS orders (
    id INT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
    quantity INT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""

SEED_SQL = """
INSERT INTO products (id, name, category, price)
SELECT 'P' || lpad(g::text, 3, '0'), 'Producto ' || g,
       (ARRAY['licores','vinos','cervezas','snacks'])[1 + g % 4], round((10 + g * 3.7)::numeric, 2)
FROM generate_series(1, 20) g ON CONFLICT DO NOTHING;
INSERT INTO inventory (product_id, available, warehouse)
SELECT 'P' || lpad(g::text, 3, '0'), (g * 37) % 120, (ARRAY['BOG','MDE','CLO'])[1 + g % 3]
FROM generate_series(1, 20) g ON CONFLICT DO NOTHING;
INSERT INTO orders (id, product_id, quantity, status)
SELECT g, 'P' || lpad((1 + g % 20)::text, 3, '0'), 1 + g % 5,
       (ARRAY['CREATED','PAID','SHIPPED','DELIVERED'])[1 + g % 4]
FROM generate_series(1, 100) g ON CONFLICT DO NOTHING;
"""


def _sqlcomment(action: str, route: str) -> str:
    """Comentario sqlcommenter con traceparent + tags de aplicación (Query Insights)."""
    ctx = trace.get_current_span().get_span_context()
    tags = {
        "action": action,
        "controller": SERVICE,
        "framework": "fastapi",
        "route": route,
        "traceparent": f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{int(ctx.trace_flags):02x}",
    }
    comment = " /*" + ",".join(f"{k}='{quote(v)}'" for k, v in sorted(tags.items())) + "*/"
    # La codificación URL usa '%', que psycopg2 interpretaría como placeholder
    return comment.replace("%", "%%")


@contextmanager
def db_span(operation: str, collection: str, query: str):
    """Span CLIENT con OTel DB Semantic Conventions (v1.26+ estables y legacy)."""
    with tracer.start_as_current_span(
        f"{operation} {DB_NAME}.{collection}",
        kind=SpanKind.CLIENT,
        attributes={
            # Estables
            "db.system.name": "postgresql",
            "db.namespace": DB_NAME,
            "db.operation.name": operation,
            "db.collection.name": collection,
            "db.query.text": query,
            "server.address": DB_HOST,
            "server.port": DB_PORT,
            # Legacy (compatibilidad)
            "db.system": "postgresql",
            "db.name": DB_NAME,
            "db.operation": operation,
            "db.sql.table": collection,
            "db.statement": query,
            "db.user": DB_USER,
            # Contexto GCP
            "gcp.cloudsql.instance": CLOUDSQL_INSTANCE,
        },
    ) as span:
        start = time.perf_counter()
        outcome = "ok"
        try:
            yield span
        except psycopg2.Error as e:
            outcome = "error"
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e).strip())
            span.set_attribute("error.type", type(e).__name__)
            if e.pgcode:
                span.set_attribute("db.response.status_code", e.pgcode)
            db_errors.add(1, {"db_operation_name": operation, "error_type": type(e).__name__})
            raise
        finally:
            db_duration.record(time.perf_counter() - start, {
                "db_system_name": "postgresql",
                "db_operation_name": operation,
                "db_collection_name": collection,
                "outcome": outcome,
            })


def query(operation: str, collection: str, sql: str, params: tuple, route: str, many: bool):
    with db_span(operation, collection, sql) as span:
        conn = _pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql + _sqlcomment(f"{operation.lower()}_{collection}", route), params)
                rows = cur.fetchall() if many else cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pool.putconn(conn)
        span.set_attribute("db.response.returned_rows", len(rows) if many else int(rows is not None))
        return rows


def init_db(retries: int = 30) -> None:
    global _pool
    for attempt in range(1, retries + 1):
        try:
            _pool = pool.ThreadedConnectionPool(
                1, 10, host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD, connect_timeout=5,
                application_name=SERVICE,
            )
            break
        except psycopg2.OperationalError as e:
            logger.warning("DB no disponible, reintentando", extra={"attempt": attempt, "error": str(e)})
            time.sleep(2)
    else:
        raise RuntimeError("No fue posible conectar a Cloud SQL")

    with tracer.start_as_current_span("db.schema.migrate"):
        conn = _pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
                cur.execute(SEED_SQL)
            conn.commit()
        finally:
            _pool.putconn(conn)
    logger.info("Esquema y datos semilla listos", extra={"instance": CLOUDSQL_INSTANCE})


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    if _pool:
        _pool.closeall()
    tel.shutdown()


app = FastAPI(title="data-service", version=os.getenv("APP_VERSION", "1.0.0"), lifespan=lifespan)
tel.instrument(app)


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE}


@app.get("/data/orders/{order_id}")
def get_order(order_id: int):
    row = query("SELECT", "orders",
                "SELECT id, product_id, quantity, status FROM orders WHERE id = %s",
                (order_id,), "/data/orders/{order_id}", many=False)
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return {"id": row[0], "product_id": row[1], "quantity": row[2], "status": row[3],
            "trace_id": tel.current_trace_id()}


@app.get("/data/inventory/{product_id}")
def get_inventory(product_id: str):
    row = query("SELECT", "inventory",
                "SELECT product_id, available, warehouse, last_updated FROM inventory WHERE product_id = %s",
                (product_id,), "/data/inventory/{product_id}", many=False)
    if not row:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return {"product_id": row[0], "available": row[1], "warehouse": row[2],
            "last_updated": row[3].isoformat()}


@app.get("/data/products")
def list_products(category: str = "all"):
    sql = "SELECT id, name, category, price FROM products"
    params: tuple = ()
    if category != "all":
        sql += " WHERE category = %s"
        params = (category,)
    rows = query("SELECT", "products", sql + " ORDER BY id LIMIT 50", params,
                 "/data/products", many=True)
    return {"count": len(rows),
            "products": [{"id": r[0], "name": r[1], "category": r[2], "price": float(r[3])} for r in rows]}
