"""E2E do gateway sem Docker nem Redis real (fakeredis + ASGI cru).

Verifica o contrato completo na borda HTTP:
  1. handshake emite token;
  2. o stream entrega o protocolo correto no fio (comentário de abertura,
     `retry:`, evento nomeado com `id:`/`event:`/`data:`);
  3. o disconnect remove o stream do broker (sem zombie listeners);
  4. o token é one-time-use (reutilização → 401) e lixo → 401.

O stream é dirigido no nível ASGI porque clientes de teste HTTP bufferizam
o corpo — inviável para uma resposta que nunca termina.
"""

import asyncio
import json

import fakeredis
import fakeredis.aioredis
import httpx
import pytest

import src.api.core.redis_client as rc
from src.publisher.main import build_envelope, make_trade

CHANNEL = "farol:events"  # default de config/settings.py


@pytest.fixture
def fake_redis(monkeypatch):
    """Redireciona toda criação de conexão Redis para um servidor fake."""
    server = fakeredis.FakeServer()

    def fake_from_url(url, **kwargs):
        return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    monkeypatch.setattr(rc.aioredis, "from_url", fake_from_url)
    return fake_from_url


def _asgi_scope(path: str, query: str) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query.encode(),
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }


def test_fluxo_completo_do_gateway(fake_redis):
    from src.api.main import app

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            client = httpx.AsyncClient(transport=transport, base_url="http://test")

            # 1. handshake
            response = await client.post("/auth/sse-token")
            assert response.status_code == 200
            token = response.json()["token"]

            # 2. stream: ASGI cru, publicando um envelope real de publisher
            chunks: list[bytes] = []
            meta: dict = {}
            receive_queue: asyncio.Queue = asyncio.Queue()
            await receive_queue.put({"type": "http.request", "body": b"", "more_body": False})

            async def receive():
                return await receive_queue.get()

            async def send(message):
                if message["type"] == "http.response.start":
                    meta["status"] = message["status"]
                    meta["headers"] = {k.decode(): v.decode() for k, v in message["headers"]}
                elif message["type"] == "http.response.body":
                    chunks.append(message.get("body", b""))
                    if b"data:" in b"".join(chunks) and receive_queue.empty():
                        # cliente "fecha a aba" após o primeiro evento
                        await receive_queue.put({"type": "http.disconnect"})
                        await receive_queue.put({"type": "http.disconnect"})

            stream_task = asyncio.create_task(
                app(_asgi_scope("/events", f"token={token}"), receive, send)
            )

            async def publish_soon():
                await asyncio.sleep(0.3)
                publisher = fake_redis("redis://ignorado")
                await publisher.publish(
                    CHANNEL, json.dumps(build_envelope("trade", make_trade()))
                )

            await asyncio.wait_for(asyncio.gather(stream_task, publish_soon()), timeout=15)

            assert meta["status"] == 200
            assert meta["headers"]["content-type"].startswith("text/event-stream")
            wire = b"".join(chunks).decode()
            assert ": stream aberto" in wire
            assert "retry: 3000" in wire
            assert "event: trade" in wire
            assert "id: " in wire

            # 3. cleanup no disconnect
            response = await client.get("/healthz")
            assert response.json()["active_streams"] == 0
            assert response.json()["broker_connected"] is True

            # 4. one-time-use e token inválido
            assert (await client.get(f"/events?token={token}")).status_code == 401
            assert (await client.get("/events?token=lixo")).status_code == 401

            await client.aclose()

    asyncio.run(scenario())
