"""Configuration centralisée, lue depuis l'environnement.

Aucune valeur sensible n'est codée en dur. Les secrets (clé privée JWT, URL avec
mot de passe, etc.) sont fournis via l'environnement, lui-même alimenté en
production par le gestionnaire de secrets de la plateforme (hors périmètre de ce
dépôt applicatif).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # pydantic-settings : priorité kwargs > variables d'env > .env > défauts.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Identité du service ------------------------------------------------------
    service_name: str = "fiduce-service"
    service_namespace: str = "fiduce"
    http_port: int = 8000
    log_level: str = "INFO"

    # PostgreSQL ---------------------------------------------------------------
    database_url: str | None = None  # postgresql://user:pass@host:5432/db
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_connect_retries: int = 30
    db_connect_backoff_s: float = 1.0

    # Redis --------------------------------------------------------------------
    redis_url: str | None = None  # redis://host:6379/0
    cache_ttl_s: int = 30

    # NATS / JetStream ---------------------------------------------------------
    nats_url: str | None = None  # nats://host:4222
    nats_stream: str = "FIDUCE"

    # OpenTelemetry ------------------------------------------------------------
    # Endpoint OTLP/HTTP (ex. http://otel-collector:4318). Si absent : pas
    # d'export distant, le service tourne quand même.
    otel_exporter_otlp_endpoint: str | None = None

    # Authentification / JWT ---------------------------------------------------
    jwt_issuer: str = "https://auth.fiduce.local"
    jwt_audience: str = "fiduce-api"
    jwt_access_ttl_s: int = 3600
    jwt_key_id: str = "fiduce-rsa-1"
    # Clé privée RSA au format PEM. En prod : injectée via un secret. En dev :
    # si absente, une clé éphémère est générée au démarrage (cf. security.py).
    jwt_private_key_pem: str | None = None
    # Côté gateway : URL du JWKS exposé par le service auth.
    jwks_url: str | None = None

    # URLs amont (gateway -> services) ----------------------------------------
    auth_service_url: str | None = None
    ledger_service_url: str | None = None
    reporting_service_url: str | None = None

    # Données de démonstration -------------------------------------------------
    # À désactiver en production (demo_seed=false). Le mot de passe de démo n'est
    # PAS un secret de prod : il sert uniquement à amorcer des comptes de test.
    demo_seed: bool = True
    demo_password: str = "demo-password"


@lru_cache
def _cached(**overrides: object) -> Settings:  # pragma: no cover - trivial
    return Settings(**overrides)


def get_settings(**overrides: object) -> Settings:
    """Retourne les settings. Les `overrides` (ex. service_name) priment sur l'env."""
    return Settings(**overrides)
