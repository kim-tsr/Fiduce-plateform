"""Primitives de sécurité : signature JWT RS256, JWKS, hachage de mots de passe.

La clé privée RSA provient de la configuration (secret injecté en prod). En
développement, si aucune clé n'est fournie, une clé éphémère est générée au
démarrage — aucun secret n'est donc codé en dur dans le dépôt.
"""
from __future__ import annotations

import base64
import logging
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class TokenIssuer:
    """Charge (ou génère) la clé privée et émet des JWT signés."""

    def __init__(self, settings) -> None:
        self.settings = settings
        if settings.jwt_private_key_pem:
            self._private = serialization.load_pem_private_key(
                settings.jwt_private_key_pem.encode(), password=None
            )
            logger.info("Clé privée JWT chargée depuis la configuration")
        else:
            logger.warning(
                "Aucune clé JWT fournie : génération d'une clé éphémère (DEV uniquement)"
            )
            self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._public = self._private.public_key()
        self._private_pem = self._private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    def issue(self, *, subject: str, tenant: str, roles: list[str], username: str) -> str:
        now = int(time.time())
        claims = {
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
            "sub": subject,
            "tenant": tenant,
            "username": username,
            "roles": roles,
            "iat": now,
            "nbf": now,
            "exp": now + self.settings.jwt_access_ttl_s,
        }
        return jwt.encode(
            claims,
            self._private_pem,
            algorithm="RS256",
            headers={"kid": self.settings.jwt_key_id},
        )

    @property
    def public_pem(self) -> str:
        return self._public.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def jwks(self) -> dict:
        numbers = self._public.public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.settings.jwt_key_id,
                    "n": _b64url_uint(numbers.n),
                    "e": _b64url_uint(numbers.e),
                }
            ]
        }


class TokenVerifier:
    """Vérifie les JWT via le JWKS exposé par le service d'authentification."""

    def __init__(self, settings) -> None:
        self.settings = settings
        if not settings.jwks_url:
            raise RuntimeError("JWKS_URL non configurée")
        self._jwk_client = jwt.PyJWKClient(settings.jwks_url)

    def verify(self, token: str) -> dict:
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.settings.jwt_audience,
            issuer=self.settings.jwt_issuer,
            options={"require": ["exp", "iss", "aud", "sub", "tenant"]},
        )


# --- Mots de passe (argon2, import paresseux pour ne pas l'imposer partout) ---


def hash_password(password: str) -> str:
    from argon2 import PasswordHasher

    return PasswordHasher().hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    try:
        return PasswordHasher().verify(stored_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # pragma: no cover
        return False
