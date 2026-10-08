# syntax=docker/dockerfile:1
# Image du service "auth" (multi-stage, exécution non-root).
# Contexte de build attendu : RACINE du dépôt.
#   docker build -f services/auth/Dockerfile -t fiduce/auth .

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS builder
WORKDIR /build
COPY services/auth/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/libs
# Utilisateur non privilégié à UID fixe (compatible runAsNonRoot Kubernetes).
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY libs/ ./libs/
COPY services/auth/ ./auth/
USER 10001
EXPOSE 8000
CMD ["uvicorn", "auth.app:app", "--host", "0.0.0.0", "--port", "8000"]
