"""Tokens curtos e one-time-use para o handshake SSE.

Por que não Authorization: Bearer? O `EventSource` do navegador não aceita
headers customizados. As alternativas são cookie (exige mesmo domínio) ou
query string. Query string é a mais portável, mas o token aparece em URLs —
e URL vaza (histórico do navegador, logs de proxy, Referer).

Mitigação em camadas (defesa em profundidade — ver SECURITY.md):
  1. TTL de 60 segundos: a janela de replay é mínima.
  2. One-time-use: o `jti` é marcado como consumido no Redis (SET NX);
     um token interceptado depois do handshake não abre outra conexão.
  3. Escopo restrito: o token só serve para `sse:events`, não é a sessão
     do usuário.
"""

from __future__ import annotations

import time
import uuid

import jwt
import redis.asyncio as aioredis

from config.settings import Settings

SSE_SCOPE = "sse:events"
_JTI_KEY_PREFIX = "farol:sse:jti:"


class TokenError(Exception):
    """Token inválido, expirado, com escopo errado ou já consumido."""


def issue_sse_token(settings: Settings) -> tuple[str, int]:
    """Emite um JWT de vida curta para abrir UM stream SSE."""
    now = int(time.time())
    ttl = settings.sse_token_ttl_seconds
    claims = {
        "jti": uuid.uuid4().hex,
        "scope": SSE_SCOPE,
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_sse_token(token: str, settings: Settings) -> dict:
    """Valida assinatura, expiração e escopo. Não consome o jti."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expirado — solicite um novo em /auth/sse-token") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token inválido") from exc

    if claims.get("scope") != SSE_SCOPE:
        raise TokenError("token sem escopo para abrir streams SSE")
    return claims


async def consume_token(token: str, redis: aioredis.Redis, settings: Settings) -> dict:
    """Valida o token e o marca como usado (one-time-use).

    O SET NX é atômico: duas conexões disputando o mesmo token nunca passam
    as duas. A chave expira junto com o token — o Redis se limpa sozinho.
    """
    claims = decode_sse_token(token, settings)
    key = f"{_JTI_KEY_PREFIX}{claims['jti']}"
    was_set = await redis.set(key, "used", nx=True, ex=settings.sse_token_ttl_seconds)
    if not was_set:
        raise TokenError("token já utilizado — cada token abre apenas um stream")
    return claims
