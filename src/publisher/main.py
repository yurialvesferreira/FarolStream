"""Publisher — microsserviço simulador de eventos.

Publica envelopes JSON no canal Redis (`farol:events`) sem saber nada sobre
SSE, HTTP ou quantos dashboards estão conectados. É esse desacoplamento que
o Pub/Sub compra: produtores e gateway evoluem de forma independente.

A MESMA imagem sobe como DOIS serviços no docker-compose, variando apenas
`PUBLISHER_ROLE`:

  - ops    → eventos `log` (frequentes) e `alert` (raros)
  - market → eventos `trade`

Dois produtores independentes publicando no mesmo canal é o cenário que
justifica o Redis como orquestrador entre microsserviços.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import signal
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import redis.asyncio as aioredis

from config.settings import get_settings

logger = logging.getLogger("publisher")

_RECONNECT_DELAY_SECONDS = 2.0

# --- Fábricas de eventos fake -------------------------------------------------

_SERVICES = ["checkout", "payments", "auth", "orders", "notifications"]
_LOG_MESSAGES = [
    "Requisição processada com sucesso",
    "Cache invalidado para a chave de sessão",
    "Retry agendado após timeout de upstream",
    "Conexão com o banco reciclada pelo pool",
    "Webhook entregue na segunda tentativa",
]
_ALERTS = [
    ("critical", "Taxa de erro acima de 5% nos últimos 5 minutos"),
    ("warning", "Latência p99 acima de 800ms"),
    ("warning", "Fila de webhooks acumulando mensagens"),
    ("critical", "Circuit breaker aberto para o serviço de pagamentos"),
]
_SYMBOLS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "FAROL3"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def make_log() -> dict:
    return {
        "level": random.choices(["info", "warning", "error"], weights=[70, 20, 10])[0],
        "service": random.choice(_SERVICES),
        "message": random.choice(_LOG_MESSAGES),
        "timestamp": _now(),
    }


def make_alert() -> dict:
    severity, title = random.choice(_ALERTS)
    return {
        "severity": severity,
        "title": title,
        "source": random.choice(_SERVICES),
        "timestamp": _now(),
    }


def make_trade() -> dict:
    price = round(random.uniform(8, 120), 2)
    return {
        "symbol": random.choice(_SYMBOLS),
        "price": price,
        "change_pct": round(random.uniform(-3.5, 3.5), 2),
        "side": random.choice(["buy", "sell"]),
        "quantity": random.choice([100, 200, 500, 1000]),
        "timestamp": _now(),
    }


# (fábrica, peso relativo) por papel do serviço
_FACTORIES_BY_ROLE: dict[str, list[tuple[str, Callable[[], dict], int]]] = {
    "ops": [("log", make_log, 85), ("alert", make_alert, 15)],
    "market": [("trade", make_trade, 100)],
}

# --- Loop principal -----------------------------------------------------------


def build_envelope(event_type: str, data: dict) -> dict:
    """Contrato compartilhado com o gateway (src/api/sse/formatter.py)."""
    return {"id": uuid.uuid4().hex[:12], "type": event_type, "data": data}


async def run() -> None:
    settings = get_settings()
    factories = _FACTORIES_BY_ROLE[settings.publisher_role]
    types, makers, weights = zip(*factories)

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info(
        "Publisher role=%r publicando em %r", settings.publisher_role, settings.events_channel
    )

    try:
        while not stop.is_set():
            index = random.choices(range(len(types)), weights=weights)[0]
            envelope = build_envelope(types[index], makers[index]())
            try:
                await redis.publish(
                    settings.events_channel, json.dumps(envelope, ensure_ascii=False)
                )
            except (aioredis.RedisError, OSError) as exc:
                # Queda do Redis não pode matar o produtor: descarta o evento
                # (Pub/Sub é fire-and-forget mesmo) e tenta de novo no próximo
                # ciclo — a conexão se refaz sozinha quando o Redis voltar.
                logger.warning("Redis indisponível (%s); tentando novamente…", exc)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=_RECONNECT_DELAY_SECONDS)
                continue

            delay = random.uniform(
                settings.publisher_min_interval_seconds,
                settings.publisher_max_interval_seconds,
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
    finally:
        await redis.aclose()
        logger.info("Publisher encerrado")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run())
