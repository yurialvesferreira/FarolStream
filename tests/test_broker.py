"""EventBroker: multiplexação, cleanup e backpressure — com fakeredis.

O construtor aceita um cliente injetado (DI) justamente para estes testes
não dependerem de um Redis real nem de monkeypatch.
"""

import asyncio
import json

import fakeredis.aioredis
import pytest

from src.api.core.redis_client import EventBroker

CHANNEL = "farol:events:test"


def _fake_pair() -> tuple[fakeredis.aioredis.FakeRedis, fakeredis.aioredis.FakeRedis]:
    """Dois clientes (broker e publisher) sobre o mesmo servidor fake."""
    server = fakeredis.FakeServer()
    make = lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)  # noqa: E731
    return make(), make()


async def _publish_and_settle(publisher, payload: dict) -> None:
    await publisher.publish(CHANNEL, json.dumps(payload))
    await asyncio.sleep(0.1)  # dá tempo do fan-out rodar


def test_uma_conexao_alimenta_n_streams():
    async def scenario():
        broker_client, publisher = _fake_pair()
        broker = EventBroker("redis://ignorado", CHANNEL, redis_client=broker_client)
        await broker.start()
        try:
            fila_a, fila_b = broker.subscribe(), broker.subscribe()
            assert broker.listener_count == 2

            await _publish_and_settle(publisher, {"type": "log", "data": {"n": 1}})

            # A MESMA mensagem chega nas duas filas (fan-out, não rodízio)
            assert json.loads(fila_a.get_nowait())["data"] == {"n": 1}
            assert json.loads(fila_b.get_nowait())["data"] == {"n": 1}
        finally:
            await broker.stop()

    asyncio.run(scenario())


def test_unsubscribe_remove_o_stream():
    async def scenario():
        broker_client, publisher = _fake_pair()
        broker = EventBroker("redis://ignorado", CHANNEL, redis_client=broker_client)
        await broker.start()
        try:
            fila = broker.subscribe()
            broker.unsubscribe(fila)
            assert broker.listener_count == 0

            await _publish_and_settle(publisher, {"type": "log", "data": {}})
            assert fila.empty()  # zombie listener não recebe nada
        finally:
            await broker.stop()

    asyncio.run(scenario())


def test_consumidor_lento_perde_o_mais_antigo_nao_trava_o_fan_out():
    async def scenario():
        broker_client, publisher = _fake_pair()
        broker = EventBroker(
            "redis://ignorado", CHANNEL, queue_maxsize=2, redis_client=broker_client
        )
        await broker.start()
        try:
            fila = broker.subscribe()
            for n in range(4):  # fila com maxsize=2 recebe 4 eventos
                await _publish_and_settle(publisher, {"n": n})

            recebidos = []
            while not fila.empty():
                recebidos.append(json.loads(fila.get_nowait())["n"])
            # Política drop-oldest: sobram apenas os 2 mais recentes
            assert recebidos == [2, 3]
        finally:
            await broker.stop()

    asyncio.run(scenario())


def test_is_healthy_reflete_a_task_de_fan_out():
    async def scenario():
        broker_client, _ = _fake_pair()
        broker = EventBroker("redis://ignorado", CHANNEL, redis_client=broker_client)
        assert not broker.is_healthy  # antes do start não há task

        await broker.start()
        assert broker.is_healthy

        await broker.stop()
        assert not broker.is_healthy

    asyncio.run(scenario())


def test_get_broker_sem_init_levanta_erro(monkeypatch):
    import src.api.core.redis_client as rc

    monkeypatch.setattr(rc, "_broker", None)
    with pytest.raises(RuntimeError):
        rc.get_broker()
