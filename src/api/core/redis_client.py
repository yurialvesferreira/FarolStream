"""Conexão única com o Redis, multiplexada para N streams SSE.

O anti-padrão clássico é abrir uma conexão SUBSCRIBE por cliente conectado:
1.000 abas abertas = 1.000 conexões Redis. Aqui o `EventBroker` mantém
UMA assinatura Pub/Sub (Singleton por processo) e distribui cada mensagem
para N filas em memória — uma por stream SSE ativo (padrão Fan-Out).

Ciclo de vida de um stream:
    subscribe()   → registra uma fila no broker (cliente conectou)
    unsubscribe() → remove a fila (cliente desconectou — sem zombie listeners)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


_RECONNECT_DELAY_SECONDS = 2.0


class EventBroker:
    """Uma conexão Redis Pub/Sub, N filas de assinantes em memória."""

    def __init__(
        self,
        redis_url: str,
        channel: str,
        queue_maxsize: int = 100,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        # Injeção de dependência: os testes passam um cliente fake sem tocar
        # na criação da conexão real (ver tests/test_broker.py).
        self._redis = redis_client or aioredis.from_url(redis_url, decode_responses=True)
        self._channel = channel
        self._queue_maxsize = queue_maxsize
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._pubsub: aioredis.client.PubSub | None = None
        self._fan_out_task: asyncio.Task[None] | None = None

    @property
    def redis(self) -> aioredis.Redis:
        """Cliente Redis compartilhado para comandos pontuais (ex.: SET NX do jti)."""
        return self._redis

    @property
    def listener_count(self) -> int:
        return len(self._subscribers)

    @property
    def is_healthy(self) -> bool:
        """False se a task de fan-out morreu — o /healthz expõe isso.

        Sem este sinal, uma queda permanente do Redis deixaria streams abertos
        que nunca mais recebem eventos, com o health check mentindo "ok".
        """
        return self._fan_out_task is not None and not self._fan_out_task.done()

    async def start(self) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel)
        self._fan_out_task = asyncio.create_task(self._fan_out(), name="broker-fan-out")
        logger.info("EventBroker assinou o canal %r com uma única conexão", self._channel)

    async def stop(self) -> None:
        if self._fan_out_task is not None:
            self._fan_out_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._fan_out_task
        if self._pubsub is not None:
            await self._pubsub.aclose()
        await self._redis.aclose()
        logger.info("EventBroker encerrado")

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.add(queue)
        logger.info("Stream registrado (%d ativos)", self.listener_count)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)
        logger.info("Stream removido (%d ativos)", self.listener_count)

    async def _fan_out(self) -> None:
        assert self._pubsub is not None
        while True:
            try:
                async for message in self._pubsub.listen():
                    if message["type"] != "message":
                        continue
                    self._dispatch(message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                # Queda do Redis não pode matar o fan-out em silêncio: os
                # streams continuariam abertos sem nunca receber eventos.
                logger.exception(
                    "Conexão Pub/Sub perdida; reassinando em %.0fs", _RECONNECT_DELAY_SECONDS
                )
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
            with contextlib.suppress(Exception):
                await self._pubsub.subscribe(self._channel)

    def _dispatch(self, data: str) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                # Consumidor lento: descarta o evento mais antigo em vez de
                # bloquear o fan-out para todos os outros streams.
                queue.get_nowait()
                queue.put_nowait(data)


# --- Singleton por processo, criado no lifespan do FastAPI (src/api/main.py) ---

_broker: EventBroker | None = None


async def init_broker(redis_url: str, channel: str, queue_maxsize: int) -> EventBroker:
    global _broker
    if _broker is None:
        _broker = EventBroker(redis_url, channel, queue_maxsize)
        await _broker.start()
    return _broker


def get_broker() -> EventBroker:
    if _broker is None:
        raise RuntimeError("EventBroker não inicializado — verifique o lifespan da aplicação")
    return _broker


async def close_broker() -> None:
    global _broker
    if _broker is not None:
        await _broker.stop()
        _broker = None
