#!/usr/bin/env bash
# FarolStream — sobe toda a stack e roda um smoke test de SSE via curl.
set -euo pipefail

BASE_URL="http://localhost:8080"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()  { echo -e "${GREEN}[farol]${NC} $*"; }
warn()  { echo -e "${YELLOW}[farol]${NC} $*"; }
fail()  { echo -e "${RED}[farol]${NC} $*" >&2; exit 1; }

# --- Pré-requisitos ----------------------------------------------------------
command -v docker >/dev/null 2>&1 || fail "Docker não encontrado. Instale: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 não encontrado (plugin 'docker compose')."
command -v curl >/dev/null 2>&1 || fail "curl não encontrado."

# --- .env com segredo gerado -------------------------------------------------
if [[ ! -f .env ]]; then
    cp .env.example .env
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null \
        || openssl rand -base64 48 | tr -d '\n=+/')
    sed -i.bak "s|^JWT_SECRET=.*|JWT_SECRET=${SECRET}|" .env && rm -f .env.bak
    info ".env criado com JWT_SECRET aleatório"
else
    warn ".env já existe — mantendo o atual"
fi

# --- Sobe a stack ------------------------------------------------------------
info "Construindo e subindo os serviços (redis, api, 2 publishers, frontend, nginx)…"
docker compose up -d --build

# --- Aguarda o gateway responder através do Nginx ----------------------------
info "Aguardando o gateway ficar saudável…"
for _ in $(seq 1 30); do
    if curl -sf "${BASE_URL}/api/healthz" >/dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    sleep 2
done
[[ "${HEALTHY:-0}" == "1" ]] || fail "Gateway não respondeu em ${BASE_URL}/api/healthz. Veja: docker compose logs api nginx"

# --- Smoke test: handshake + stream ------------------------------------------
info "Handshake: solicitando token curto em /api/auth/sse-token…"
TOKEN=$(curl -sf -X POST "${BASE_URL}/api/auth/sse-token" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")

info "Abrindo o stream SSE por 6 segundos (eventos reais dos publishers):"
echo "────────────────────────────────────────────────────────────"
curl -sN --max-time 6 "${BASE_URL}/api/events?token=${TOKEN}" | head -n 20 || true
echo "────────────────────────────────────────────────────────────"

info "Provando o one-time-use: reutilizar o mesmo token deve falhar com 401…"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/events?token=${TOKEN}")
if [[ "$STATUS" == "401" ]]; then
    info "OK — token já consumido foi rejeitado (HTTP ${STATUS})"
else
    warn "Esperava 401 ao reutilizar o token, recebi HTTP ${STATUS}"
fi

echo
info "Tudo no ar! 🚨"
echo
echo "  Dashboard:  ${BASE_URL}"
echo "  API Docs:   ${BASE_URL}/api/docs"
echo "  Health:     ${BASE_URL}/api/healthz"
echo
echo "  Para encerrar: docker compose down"
