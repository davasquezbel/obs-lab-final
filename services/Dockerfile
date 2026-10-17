# Imagen común para los tres microservicios: docker build --build-arg SERVICE=<nombre> .
FROM python:3.12-slim

ARG SERVICE
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVICE_NAME=${SERVICE}

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY ${SERVICE}/main.py ./main.py

# Ejecutar sin privilegios de root
RUN useradd --uid 10001 --no-create-home appuser
USER 10001

ENV PORT=8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
