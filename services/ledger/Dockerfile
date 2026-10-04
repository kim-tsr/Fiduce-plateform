# syntax=docker/dockerfile:1
# Image du service "ledger" (multi-stage, exécution non-root).
# Contexte de build attendu : RACINE du dépôt.
#   docker build -f services/ledger/Dockerfile -t fiduce/ledger .

FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/ledger/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/libs
# Utilisateur non privilégié à UID fixe (compatible runAsNonRoot Kubernetes).
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY libs/ ./libs/
COPY services/ledger/ ./ledger/
USER 10001
EXPOSE 8000
CMD ["uvicorn", "ledger.app:app", "--host", "0.0.0.0", "--port", "8000"]
