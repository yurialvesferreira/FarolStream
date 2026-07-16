"""FarolStream Gateway — API SSE (FastAPI + sse-starlette).

Composição da aplicação:
  - lifespan: cria o EventBroker (Singleton) na subida e o encerra na descida;
  - routers: /auth/sse-token (handshake) e /events (stream);
  - /healthz: usado pelo healthcheck do Docker e pelo quick_start.sh.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from src.api.auth.router import router as auth_router
from src.api.core.redis_client import close_broker, get_broker, init_broker
from src.api.sse.stream import router as sse_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.jwt_secret == "dev-secret-change-me":
        logging.getLogger(__name__).warning(
            "JWT_SECRET está no valor default de desenvolvimento — "
            "gere um segredo forte antes de expor este serviço (ver SECURITY.md)"
        )
    await init_broker(
        redis_url=settings.redis_url,
        channel=settings.events_channel,
        queue_maxsize=settings.stream_queue_maxsize,
    )
    yield
    await close_broker()


settings = get_settings()

app = FastAPI(
    title="FarolStream Gateway",
    description="Gateway SSE que multiplexa uma conexão Redis Pub/Sub para N streams.",
    version="1.0.0",
    lifespan=lifespan,
    root_path=settings.api_root_path,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(sse_router)


@app.get("/healthz", tags=["ops"], summary="Liveness + streams ativos + saúde do broker")
async def healthz() -> dict:
    broker = get_broker()
    # "degraded" = a task de fan-out morreu (ex.: Redis fora do ar de vez):
    # streams abertos não recebem mais eventos e o orquestrador deve reciclar.
    return {
        "status": "ok" if broker.is_healthy else "degraded",
        "broker_connected": broker.is_healthy,
        "active_streams": broker.listener_count,
    }
