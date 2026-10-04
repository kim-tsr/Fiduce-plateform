"""Service d'authentification : émet des JWT RS256 et expose un JWKS."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from fiduce_platform.app_factory import build_app
from fiduce_platform.config import get_settings
from fiduce_platform.db import close_db, get_pool, init_db, ping_db
from fiduce_platform.security import (
    TokenIssuer,
    hash_password,
    verify_password,
)

logger = logging.getLogger("auth")
settings = get_settings(service_name="auth", http_port=8000)

# Comptes de démonstration (amorçage). NON destinés à la production.
DEMO_USERS = [
    {"tenant": "acme", "username": "alice", "roles": ["admin", "user"]},
    {"tenant": "acme", "username": "bob", "roles": ["user"]},
    {"tenant": "globex", "username": "carol", "roles": ["user"]},
]

issuer: TokenIssuer | None = None


async def _seed_demo() -> None:
    if not settings.demo_seed:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        for u in DEMO_USERS:
            await conn.execute(
                "INSERT INTO tenants (id, name) VALUES ($1, $2) "
                "ON CONFLICT (id) DO NOTHING",
                u["tenant"], u["tenant"].upper(),
            )
            exists = await conn.fetchval(
                "SELECT 1 FROM users WHERE tenant_id=$1 AND username=$2",
                u["tenant"], u["username"],
            )
            if not exists:
                await conn.execute(
                    "INSERT INTO users (tenant_id, username, password_hash, roles) "
                    "VALUES ($1, $2, $3, $4)",
                    u["tenant"], u["username"],
                    hash_password(settings.demo_password), u["roles"],
                )
                logger.info("Compte démo créé: %s/%s", u["tenant"], u["username"])


@asynccontextmanager
async def lifespan(app):
    global issuer
    issuer = TokenIssuer(settings)
    await init_db(settings)
    await _seed_demo()
    yield
    await close_db()


app = build_app(settings, lifespan=lifespan, readiness=[("postgres", ping_db)])


class LoginRequest(BaseModel):
    tenant: str
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


@app.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, password_hash, roles FROM users "
            "WHERE tenant_id=$1 AND username=$2",
            body.tenant, body.username,
        )
    if row is None or not verify_password(row["password_hash"], body.password):
        # Message volontairement générique (pas d'oracle tenant/user).
        raise HTTPException(status_code=401, detail="Identifiants invalides")

    assert issuer is not None
    token = issuer.issue(
        subject=str(row["id"]),
        tenant=body.tenant,
        roles=list(row["roles"]),
        username=body.username,
    )
    return TokenResponse(access_token=token, expires_in=settings.jwt_access_ttl_s)


@app.get("/.well-known/jwks.json")
async def jwks():
    assert issuer is not None
    return issuer.jwks()


@app.get("/userinfo")
async def userinfo(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token Bearer requis")
    token = authorization.split(" ", 1)[1]
    assert issuer is not None
    try:
        claims = jwt.decode(
            token,
            issuer.public_pem,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Token invalide") from exc
    return {
        "sub": claims["sub"],
        "tenant": claims["tenant"],
        "username": claims.get("username"),
        "roles": claims.get("roles", []),
    }
