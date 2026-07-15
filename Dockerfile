# Imagem única para os serviços Python (gateway SSE e publishers) —
# o docker-compose varia apenas o `command`.
#
# =============================================================================
# STAGE 1: builder — instala dependências em ambiente isolado
# =============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# =============================================================================
# STAGE 2: runtime — imagem final mínima, sem ferramentas de build
# =============================================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /install /usr/local

# Usuário não-root dedicado — sem shell, sem home, privilégios mínimos
RUN useradd --system --no-create-home --shell /usr/sbin/nologin farol \
    && chown -R farol:farol /app

COPY --chown=farol:farol config/ ./config/
COPY --chown=farol:farol src/api/ ./src/api/
COPY --chown=farol:farol src/publisher/ ./src/publisher/
COPY --chown=farol:farol src/__init__.py ./src/__init__.py

USER farol

ENV PYTHONUNBUFFERED=1

# Sem --reload: esse flag é apenas para desenvolvimento local
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
