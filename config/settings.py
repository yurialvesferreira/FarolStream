"""Configuração central (12-factor): tudo vem do ambiente, com defaults de dev.

Pydantic Settings valida os tipos na inicialização — configuração inválida
derruba o serviço no boot, não no primeiro request em produção.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Infraestrutura ---
    redis_url: str = "redis://localhost:6379/0"
    events_channel: str = "farol:events"
    # Prefixo sob o qual o Nginx expõe a API (ele remove o prefixo ao fazer
    # proxy; o root_path faz o Swagger/openapi.json funcionarem atrás dele).
    api_root_path: str = "/api"

    # --- SSE ---
    # O heartbeat DEVE ser menor que o proxy_read_timeout do Nginx,
    # senão o proxy derruba conexões saudáveis (ver nginx/nginx.conf).
    heartbeat_interval_seconds: int = 20
    stream_queue_maxsize: int = 100
    sse_retry_ms: int = 3000
    # Tipos de evento aceitos pelo gateway (separados por vírgula). Para usar
    # o boilerplate em outro domínio, troque aqui — sem tocar em código.
    allowed_event_types: str = "log,alert,trade"

    # --- Auth (handshake SSE) ---
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    sse_token_ttl_seconds: int = 60

    # --- CORS ---
    # Lista separada por vírgula; em produção, restrinja ao domínio do dashboard.
    cors_origins: str = "http://localhost:8080"

    # --- Publisher (simulador de eventos) ---
    publisher_role: Literal["ops", "market"] = "ops"
    publisher_min_interval_seconds: float = 0.4
    publisher_max_interval_seconds: float = 2.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_event_type_set(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.allowed_event_types.split(",") if t.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
