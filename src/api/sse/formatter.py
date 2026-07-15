"""Tradução do payload vindo do Redis para o protocolo SSE.

Anatomia de um evento nomeado no fio (ver docs/protocol.md):

    id: a1b2c3d4e5f6\\n
    event: trade\\n
    data: {"symbol": "PETR4", "price": 38.42}\\n
    \\n                                          ← linha em branco fecha o evento

Contrato do envelope publicado no Redis pelos produtores:

    {"id": "<hex>", "type": "log|alert|trade", "data": {...}}

O gateway valida o envelope na borda: tipo desconhecido ou JSON malformado
é descartado (e logado) em vez de vazar para o navegador.
"""

from __future__ import annotations

import json
import logging

from sse_starlette.sse import ServerSentEvent

logger = logging.getLogger(__name__)

ALLOWED_EVENT_TYPES = frozenset({"log", "alert", "trade"})


def encode_sse(
    data: str,
    event: str | None = None,
    event_id: str | None = None,
    retry: int | None = None,
) -> str:
    """Serializa um evento no formato text/event-stream, campo a campo.

    É exatamente o que o sse-starlette faz por baixo dos panos — mantida aqui
    como referência executável (e testável) da sintaxe do protocolo.
    """
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    if retry is not None:
        lines.append(f"retry: {retry}")
    # Payloads multilinha viram múltiplas linhas `data:`; o navegador
    # as reagrupa com "\n" antes de disparar o listener.
    lines.extend(f"data: {line}" for line in (data.splitlines() or [""]))
    return "\n".join(lines) + "\n\n"


def to_server_sent_event(raw: str) -> ServerSentEvent | None:
    """Converte o envelope JSON do Redis em um evento SSE nomeado.

    Retorna None para mensagens inválidas — o stream nunca quebra por causa
    de um produtor mal comportado.
    """
    try:
        envelope = json.loads(raw)
        event_type = envelope["type"]
        data = envelope["data"]
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Mensagem malformada descartada: %.120s", raw)
        return None

    if event_type not in ALLOWED_EVENT_TYPES:
        logger.warning("Tipo de evento desconhecido descartado: %r", event_type)
        return None

    return ServerSentEvent(
        data=json.dumps(data, ensure_ascii=False),
        event=event_type,
        id=envelope.get("id"),
    )
