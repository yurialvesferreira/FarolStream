#!/usr/bin/env bash
# FarolStream — sobe toda a stack e roda um smoke test de SSE.
# Usa curl quando disponível; sem curl, cai para python3 + urllib.
set -euo pipefail

BASE_URL="http://localhost:8080"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()  { echo -e "${GREEN}[farol]${NC} $*"; }
warn()  { echo -e "${YELLOW}[farol]${NC} $*"; }
fail()  { echo -e "${RED}[farol]${NC} $*" >&2; exit 1; }

# --- Pré-requisitos ----------------------------------------------------------
command -v docker >/dev/null 2>&1 || fail "Docker não encontrado. Instale: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 não encontrado (plugin 'docker compose')."
command -v python3 >/dev/null 2>&1 || fail "python3 não encontrado."

HAVE_CURL=0
command -v curl >/dev/null 2>&1 && HAVE_CURL=1

# --- Helpers HTTP (curl ou python3) -------------------------------------------
http_ok() {  # $1=url → sucesso se resposta 2xx
    if [[ $HAVE_CURL == 1 ]]; then
        curl -sf "$1" >/dev/null 2>&1
    else
        python3 - "$1" <<'PY'
import sys, urllib.request
try:
    urllib.request.urlopen(sys.argv[1], timeout=5)
except Exception:
    sys.exit(1)
PY
    fi
}

http_post_field() {  # $1=url $2=campo do JSON de resposta
    if [[ $HAVE_CURL == 1 ]]; then
        curl -sf -X POST "$1" | python3 -c "import sys, json; print(json.load(sys.stdin)['$2'])"
    else
        python3 - "$1" "$2" <<'PY'
import sys, json, urllib.request
req = urllib.request.Request(sys.argv[1], data=b"", method="POST")
print(json.load(urllib.request.urlopen(req, timeout=5))[sys.argv[2]])
PY
    fi
}

http_stream() {  # $1=url $2=segundos $3=máx. de linhas
    if [[ $HAVE_CURL == 1 ]]; then
        curl -sN --max-time "$2" "$1" | head -n "$3" || true
    else
        python3 - "$1" "$2" "$3" <<'PY'
import sys, time, urllib.request
url, secs, max_lines = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
deadline = time.time() + secs
printed = 0
try:
    resp = urllib.request.urlopen(url, timeout=secs)
    while printed < max_lines and time.time() < deadline:
        line = resp.readline()
        if not line:
            break
        print(line.decode(errors="replace").rstrip("\n"), flush=True)
        printed += 1
except Exception:
    pass
PY
    fi
}

http_status() {  # $1=url → imprime o código HTTP
    if [[ $HAVE_CURL == 1 ]]; then
        curl -s -o /dev/null -w "%{http_code}" "$1"
    else
        python3 - "$1" <<'PY'
import sys, urllib.request, urllib.error
try:
    print(urllib.request.urlopen(sys.argv[1], timeout=5).status)
except urllib.error.HTTPError as exc:
    print(exc.code)
except Exception:
    print(0)
PY
    fi
}

# --- .env com segredo gerado ---------------------------------------------------
if [[ ! -f .env ]]; then
    cp .env.example .env
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    sed -i.bak "s|^JWT_SECRET=.*|JWT_SECRET=${SECRET}|" .env && rm -f .env.bak
    info ".env criado com JWT_SECRET aleatório"
else
    warn ".env já existe — mantendo o atual"
fi

# --- Sobe a stack ---------------------------------------------------------------
info "Construindo e subindo os serviços (redis, api, 2 publishers, frontend, nginx)…"
docker compose up -d --build

# --- Aguarda o gateway responder através do Nginx -------------------------------
info "Aguardando o gateway ficar saudável…"
HEALTHY=0
for _ in $(seq 1 30); do
    if http_ok "${BASE_URL}/api/healthz"; then
        HEALTHY=1
        break
    fi
    sleep 2
done
[[ "$HEALTHY" == "1" ]] || fail "Gateway não respondeu em ${BASE_URL}/api/healthz. Veja: docker compose logs api nginx"

# --- Smoke test: handshake + stream ----------------------------------------------
info "Handshake: solicitando token curto em /api/auth/sse-token…"
TOKEN=$(http_post_field "${BASE_URL}/api/auth/sse-token" "token")

info "Abrindo o stream SSE por 6 segundos (eventos reais dos publishers):"
echo "────────────────────────────────────────────────────────────"
http_stream "${BASE_URL}/api/events?token=${TOKEN}" 6 20
echo "────────────────────────────────────────────────────────────"

info "Provando o one-time-use: reutilizar o mesmo token deve falhar com 401…"
STATUS=$(http_status "${BASE_URL}/api/events?token=${TOKEN}")
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
