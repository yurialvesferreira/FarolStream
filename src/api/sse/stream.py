"""Endpoint SSE: GET /events?token=<jwt-curto>.

Responsabilidades do handler:
  1. Autenticar o handshake (token curto, one-time-use — ver src/api/auth/).
  2. Registrar um stream no EventBroker (fila em memória, conexão Redis única).
  3. Encerrar e LIMPAR o stream quando o cliente desconecta — o `finally`
     garante que não sobram zombie listeners consumindo memória.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from config.settings import get_settings
from src.api.auth.tokens import TokenError, consume_token
from src.api.core.redis_client import get_broker
from src.api.sse.formatter import to_server_sent_event
from src.api.sse.heartbeat import keep_alive_factory

router = APIRouter(tags=["sse"])

# Frequência com que o loop verifica se o cliente ainda está conectado
# enquanto a fila está vazia.
DISCONNECT_POLL_SECONDS = 1.0


@router.get("/events", summary="Stream SSE com eventos nomeados: log, alert e trade")
async def stream_events(request: Request, token: str = Query(...)) -> EventSourceResponse:
    settings = get_settings()
    broker = get_broker()

    # EventSource não permite headers customizados, então o JWT chega via
    # query string — por isso ele é curto (60s) e one-time-use (ver SECURITY.md).
    try:
        await consume_token(token, broker.redis, settings)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    queue = broker.subscribe()

    async def event_source() -> AsyncIterator[ServerSentEvent]:
        try:
            # `retry` instrui o navegador sobre o intervalo de reconexão.
            yield ServerSentEvent(comment="stream aberto", retry=settings.sse_retry_ms)
            while True:
                # Sem esta verificação, um cliente que fechou a aba continuaria
                # registrado no broker até o próximo yield falhar — o clássico
                # zombie listener.
                if await request.is_disconnected():
                    break
                try:
                    raw = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_POLL_SECONDS)
                except TimeoutError:
                    continue
                event = to_server_sent_event(raw)
                if event is not None:
                    yield event
        finally:
            broker.unsubscribe(queue)

    return EventSourceResponse(
        event_source(),
        ping=settings.heartbeat_interval_seconds,
        ping_message_factory=keep_alive_factory,
        headers={
            "Cache-Control": "no-cache",
            # Desliga o buffering em proxies que respeitam o header (Nginx via
            # X-Accel); a configuração explícita está em nginx/nginx.conf.
            "X-Accel-Buffering": "no",
        },
    )
