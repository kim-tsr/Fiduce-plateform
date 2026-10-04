"""Gateway / BFF : point d'entrée unique de l'API.

Responsabilités :
- terminaison de l'API publique `/api/*` ;
- validation du JWT via le JWKS du service auth ;
- extraction du tenant/utilisateur depuis les *claims* et injection en en-têtes
  de confiance (`X-Tenant-ID`, `X-User-ID`, `X-Roles`) vers les services amont ;
- reverse-proxy vers auth / ledger / reporting.

Les services amont ne reçoivent jamais le JWT brut (sauf auth/userinfo) : ils
font confiance aux en-têtes d'identité posés ici. Cette frontière de confiance
est à durcir au niveau plateforme (mTLS de maillage, NetworkPolicies, etc.).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import HTTPException, Request
from starlette.responses import Response

from fiduce_platform.app_factory import build_app
from fiduce_platform.config import get_settings
from fiduce_platform.security import TokenVerifier

logger = logging.getLogger("gateway")
settings = get_settings(service_name="gateway", http_port=8080)

# En-têtes hop-by-hop à ne pas relayer.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}

client: httpx.AsyncClient | None = None
verifier: TokenVerifier | None = None


def _service_urls() -> dict[str, str | None]:
    return {
        "auth": settings.auth_service_url,
        "ledger": settings.ledger_service_url,
        "reporting": settings.reporting_service_url,
    }


@asynccontextmanager
async def lifespan(app):
    global client, verifier
    client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    verifier = TokenVerifier(settings)
    yield
    if client is not None:
        await client.aclose()


async def _ready_upstreams() -> bool:
    # Prêt si la gateway peut joindre le JWKS du service auth.
    if client is None or not settings.jwks_url:
        return False
    try:
        r = await client.get(settings.jwks_url)
        return r.status_code == 200
    except Exception:  # pragma: no cover
        return False


app = build_app(settings, lifespan=lifespan, readiness=[("auth-jwks", _ready_upstreams)])


def _filtered_headers(request: Request) -> dict[str, str]:
    return {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "authorization"
    }


async def _proxy(request: Request, base_url: str, path: str,
                 identity: dict[str, str] | None = None,
                 forward_auth: bool = False) -> Response:
    assert client is not None
    url = base_url.rstrip("/") + path
    headers = _filtered_headers(request)
    if forward_auth and "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    if identity:
        headers.update(identity)
    body = await request.body()
    try:
        upstream = await client.request(
            request.method, url, headers=headers, content=body,
            params=dict(request.query_params),
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Service amont injoignable: {exc}") from exc
    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    return Response(content=upstream.content, status_code=upstream.status_code,
                    headers=resp_headers)


def _verify_bearer(request: Request) -> dict:
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token Bearer requis")
    token = auth.split(" ", 1)[1]
    assert verifier is not None
    try:
        return verifier.verify(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Token invalide") from exc


# --- Routes publiques --------------------------------------------------------

@app.post("/api/auth/login")
async def login(request: Request):
    auth_url = _service_urls()["auth"]
    if not auth_url:
        raise HTTPException(status_code=503, detail="Service auth non configuré")
    return await _proxy(request, auth_url, "/login")


# --- Routes protégées (passerelle générique) ---------------------------------

@app.api_route(
    "/api/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def gateway_proxy(service: str, path: str, request: Request):
    urls = _service_urls()
    if service not in urls:
        raise HTTPException(status_code=404, detail="Service inconnu")
    base = urls[service]
    if not base:
        raise HTTPException(status_code=503, detail=f"Service {service} non configuré")

    claims = _verify_bearer(request)

    # Cas particulier : auth/userinfo a besoin du token brut.
    if service == "auth":
        return await _proxy(request, base, "/" + path, forward_auth=True)

    identity = {
        "x-tenant-id": claims["tenant"],
        "x-user-id": claims["sub"],
        "x-roles": ",".join(claims.get("roles", [])),
    }
    return await _proxy(request, base, "/" + path, identity=identity)
