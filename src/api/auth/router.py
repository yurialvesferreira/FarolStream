"""Endpoint de handshake: emite o token curto usado para abrir o stream SSE.

Em um sistema real, este endpoint ficaria atrás da autenticação de sessão
(cookie/Bearer) e o token herdaria a identidade do usuário. No boilerplate
ele é aberto, para manter o fluxo demonstrável com um único curl.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.settings import Settings, get_settings
from src.api.auth.tokens import issue_sse_token

router = APIRouter(prefix="/auth", tags=["auth"])


class SSETokenResponse(BaseModel):
    token: str
    token_type: str = "sse-handshake"
    expires_in: int


@router.post("/sse-token", response_model=SSETokenResponse, summary="Emite token curto (60s, one-time-use) para o handshake SSE")
async def create_sse_token(settings: Settings = Depends(get_settings)) -> SSETokenResponse:
    token, ttl = issue_sse_token(settings)
    return SSETokenResponse(token=token, expires_in=ttl)
