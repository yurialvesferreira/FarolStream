# FarolStream — SSE em produção, do protocolo ao proxy

[![CI](https://github.com/yurialvesferreira/FarolStream/actions/workflows/ci.yml/badge.svg)](https://github.com/yurialvesferreira/FarolStream/actions/workflows/ci.yml)

> **Boilerplate open-source de Server-Sent Events:** dois microsserviços produtores, Redis Pub/Sub como orquestrador, gateway FastAPI com conexão multiplexada, Nginx com timeouts corretos e dashboard Next.js com eventos nomeados — tudo em um único `./quick_start.sh`.

---

## ✨ Visão Geral

Assim como um farol emite luz continuamente para quem navega, o **FarolStream** mantém um fluxo contínuo de eventos do servidor para o navegador. O caso de uso é um **painel de operações em tempo real** com três tipos de eventos nomeados — `log`, `alert` e `trade` — produzidos por dois microsserviços independentes.

A maioria dos tutoriais de SSE para no `yield "data: ...\n\n"`. Este boilerplate cobre o que quebra **depois** do tutorial: multiplexação da conexão Redis, limpeza de listeners zumbis, heartbeat, autenticação de `EventSource` (que não aceita headers) e — o ponto mais negligenciado — a configuração do proxy reverso, onde SSE morre silenciosamente em produção.

---

## 🚀 Quick Start (Fork & Run)

```bash
git clone https://github.com/yurialvesferreira/FarolStream.git
cd FarolStream
chmod +x quick_start.sh
./quick_start.sh
```

O script gera o `.env` com segredo aleatório, sobe a stack completa e roda um smoke test: pede um token, abre o stream via `curl -N`, mostra eventos reais chegando e prova que o token é one-time-use (a reutilização leva `401`).

| Serviço | URL | Descrição |
| --------- | ----- | ----------- |
| **Dashboard** | <http://localhost:8080> | Painel Dark Mode com 3 colunas (logs, alertas, trades) |
| **API Docs** | <http://localhost:8080/api/docs> | Documentação interativa do gateway (FastAPI) |
| **Health** | <http://localhost:8080/api/healthz> | Liveness + número de streams ativos |

> A **única porta pública é a 8080 (Nginx)** — API, frontend e Redis só existem na rede interna do Docker. Em produção, é assim que deve ser.

---

## 🏗️ Arquitetura

```text
┌──────────────────────┐      ┌──────────────────────┐
│   publisher-ops       │      │   publisher-market    │   ← 2 microsserviços
│   (log, alert)        │      │   (trade)             │     produtores (Python)
└──────────┬───────────┘      └──────────┬───────────┘
           │        PUBLISH farol:events │
           ▼                             ▼
          ┌───────────────────────────────┐
          │         Redis Pub/Sub          │   ← agente notificador
          └───────────────┬───────────────┘
                          │ SUBSCRIBE (conexão Singleton)
                          ▼
┌──────────┐   SSE   ┌────────────────────────────┐
│  Nginx   │◄────────┤   API Gateway SSE           │   ← FastAPI + sse-starlette
│ (proxy_  │         │   · 1 conexão Redis          │
│  read_   │         │   · N streams em memória     │
│  timeout,│         │   · heartbeat a cada 20s     │
│  buffer  │         │   · cleanup no disconnect    │
│  off)    │         │   · JWT curto via query      │
└────┬─────┘         └────────────────────────────┘
     │
     ▼
┌───────────────────┐
│ Dashboard Next.js  │   ← EventSource + addEventListener('log'|'alert'|'trade')
└───────────────────┘
```

**Por que dois produtores?** Com um único produtor, o Redis Pub/Sub parece burocracia. Com dois serviços independentes publicando no mesmo canal — sem saber nada de HTTP, SSE ou de quantos dashboards existem — o Pub/Sub mostra seu papel real: **desacoplar quem produz de quem entrega**.

**Por que SSE e não WebSocket?** O fluxo é unidirecional (servidor → cliente). SSE é HTTP puro: reconexão nativa com `Last-Event-ID`, cliente built-in no navegador e nenhum protocolo extra para operar. A comparação completa está em [docs/anti-patterns.md](docs/anti-patterns.md).

---

## 🗺️ Mapeamento conceito → componente

| Conceito | Onde é demonstrado |
| ---------- | ------------------- |
| Sintaxe do protocolo (`data:`, `event:`, `id:`, `retry:`, `\n\n`) | [src/api/sse/formatter.py](src/api/sse/formatter.py) + [docs/protocol.md](docs/protocol.md) |
| Singleton do Redis / multiplexação (1 conexão, N streams) | [src/api/core/redis_client.py](src/api/core/redis_client.py) |
| Cleanup no disconnect (zombie listeners) | [src/api/sse/stream.py](src/api/sse/stream.py) — `request.is_disconnected()` + `finally: unsubscribe()` |
| Heartbeat (`: keep-alive` a cada 20s) | [src/api/sse/heartbeat.py](src/api/sse/heartbeat.py) |
| Timeouts e buffering do proxy | [nginx/nginx.conf](nginx/nginx.conf) — `proxy_read_timeout 3600s`, `proxy_buffering off` |
| JWT via query string, TTL 60s, one-time-use | [src/api/auth/tokens.py](src/api/auth/tokens.py) + endpoint em [src/api/auth/router.py](src/api/auth/router.py) |
| Eventos nomeados no front (`addEventListener`, não `onmessage`) | [src/frontend/src/hooks/useSSE.ts](src/frontend/src/hooks/useSSE.ts) |
| Anti-padrão "Falso SSE" e outros seis | [docs/anti-patterns.md](docs/anti-patterns.md) |

---

## 🧩 Padrões de projeto aplicados

- **Singleton** (`EventBroker`): uma única assinatura Redis Pub/Sub por processo, criada no `lifespan` do FastAPI — nunca uma conexão por request.
- **Fan-Out / Publish-Subscribe**: o broker distribui cada mensagem para N filas `asyncio.Queue` em memória, uma por stream ativo, com política de descarte do evento mais antigo para consumidores lentos (backpressure).
- **Factory** (`ping_message_factory`, fábricas de eventos fake no publisher): pontos de criação isolados e substituíveis.
- **Separação de camadas**: `formatter.py` (protocolo) não conhece HTTP; `redis_client.py` (infra) não conhece SSE; `stream.py` (borda) orquestra ambos; `config/settings.py` centraliza toda a configuração (12-factor, validada no boot pelo Pydantic).
- **Validação na borda**: envelope malformado ou tipo de evento desconhecido vindo do Redis é descartado e logado — o stream nunca quebra por causa de um produtor mal comportado.

---

## 📂 Estrutura de pastas

```text
FarolStream/
├── src/
│   ├── api/                    # Gateway SSE (FastAPI)
│   │   ├── core/               # redis_client.py — EventBroker (Singleton)
│   │   ├── sse/                # formatter, stream (endpoint), heartbeat
│   │   ├── auth/               # tokens curtos one-time-use p/ handshake
│   │   └── main.py
│   ├── publisher/              # Microsserviço produtor de eventos fake
│   │   └── main.py             # mesma imagem, 2 papéis: ops | market
│   └── frontend/               # Next.js + Tailwind (Dark Mode)
│       └── src/
│           ├── app/            # Dashboard com 3 painéis
│           ├── components/     # EventPanel
│           └── hooks/useSSE.ts # EventSource + addEventListener por tipo
├── nginx/
│   └── nginx.conf              # proxy_read_timeout, buffering off, log seguro
├── config/
│   └── settings.py             # Pydantic Settings + .env
├── docs/
│   ├── anti-patterns.md        # Falso SSE, conexão por request, etc.
│   └── protocol.md             # Anatomia do event-stream
├── tests/                      # formatter (protocolo) e tokens (auth)
├── quick_start.sh              # docker compose up + smoke test com curl
├── docker-compose.yml          # redis + api + 2 publishers + frontend + nginx
├── Dockerfile                  # multi-stage, non-root
├── .env.example
├── SECURITY.md                 # tokens em logs, CORS, TTL de JWT
└── README.md
```

---

## 🔬 Vendo o protocolo cru

O dashboard é bonito, mas o protocolo é texto — dá para assistir com `curl`:

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/sse-token | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")
curl -N "http://localhost:8080/api/events?token=$TOKEN"
```

```text
: stream aberto
retry: 3000

id: 3f2a91c04b7d
event: trade
data: {"symbol": "PETR4", "price": 38.42, "change_pct": 1.27, "side": "buy", "quantity": 500, "timestamp": "..."}

: keep-alive

id: 8c1e55ab90f2
event: log
data: {"level": "info", "service": "checkout", "message": "Requisição processada com sucesso", "timestamp": "..."}
```

Repetir o mesmo comando com o mesmo token retorna `401` — cada token abre exatamente um stream.

---

## 🧪 Testes

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Quatro suítes, nenhuma exige Docker ou Redis real:

- **`test_formatter.py`** — serialização do protocolo (o `\n\n`, eventos nomeados, validação na borda);
- **`test_tokens.py`** — ciclo de vida do token (assinatura, expiração, escopo);
- **`test_broker.py`** — multiplexação, cleanup e backpressure do `EventBroker`, com fakeredis injetado via construtor (DI);
- **`test_gateway_e2e.py`** — o fluxo completo na borda HTTP: handshake → stream com protocolo verificado no fio → cleanup no disconnect → 401 na reutilização do token. O stream é dirigido no nível ASGI, porque clientes de teste HTTP bufferizam respostas infinitas.

O CI (GitHub Actions) roda `pytest` + `next build` com typecheck a cada push.

---

## 🔌 Adaptando para o seu projeto

O gateway é agnóstico ao domínio — os três passos para plugá-lo em outro sistema:

1. **Troque os produtores.** Qualquer serviço (em qualquer linguagem) que publique o envelope `{"id": "...", "type": "...", "data": {...}}` no canal Redis (`EVENTS_CHANNEL`) aparece nos streams. Os publishers deste repo são simuladores — substitua-os pelos seus serviços reais e delete `src/publisher/`.
2. **Declare seus tipos de evento.** `ALLOWED_EVENT_TYPES=pedido,estoque,pagamento` no `.env` (o gateway descarta tipos fora da lista) e a mesma lista no front: `useSSE(['pedido', 'estoque', 'pagamento'])`.
3. **Pendure o handshake na sua autenticação.** Proteja `POST /auth/sse-token` com a sessão real do seu sistema (cookie/Bearer) e inclua o `sub` do usuário nos claims em [tokens.py](src/api/auth/tokens.py) — o resto do fluxo permanece igual.

Sem `.env`, o compose sobe com defaults de desenvolvimento (e o gateway loga um aviso sobre o `JWT_SECRET` default) — o `quick_start.sh` gera um segredo forte automaticamente.

---

## ✅ Checklist de Validação para Produção

Cada item do checklist de prontidão aponta para o arquivo que o implementa:

- [x] **O stream nunca encerra a resposta por conta própria** (não é "Falso SSE" — polling disfarçado) → [src/api/sse/stream.py](src/api/sse/stream.py), explicado em [docs/anti-patterns.md](docs/anti-patterns.md)
- [x] **Uma conexão Redis por processo, não por cliente** → [src/api/core/redis_client.py](src/api/core/redis_client.py)
- [x] **Desconexões removem o listener do registro** (sem memory leak) → `finally` em [src/api/sse/stream.py](src/api/sse/stream.py)
- [x] **Heartbeat menor que o timeout do proxy** (20s < 3600s) → [src/api/sse/heartbeat.py](src/api/sse/heartbeat.py) + [nginx/nginx.conf](nginx/nginx.conf)
- [x] **`proxy_buffering off` no proxy reverso** → [nginx/nginx.conf](nginx/nginx.conf)
- [x] **Token de autenticação curto, com escopo mínimo e one-time-use** → [src/api/auth/tokens.py](src/api/auth/tokens.py)
- [x] **Token nunca aparece em logs de acesso** → `log_format` com `$uri` em [nginx/nginx.conf](nginx/nginx.conf), auditoria em [SECURITY.md](SECURITY.md)
- [x] **Front usa `addEventListener` para eventos nomeados** → [src/frontend/src/hooks/useSSE.ts](src/frontend/src/hooks/useSSE.ts)
- [x] **Reconexão do cliente refaz o handshake** (token consumido não é reutilizado) → [src/frontend/src/hooks/useSSE.ts](src/frontend/src/hooks/useSSE.ts)
- [x] **Payload inválido de produtor não derruba o stream** → [src/api/sse/formatter.py](src/api/sse/formatter.py)
- [x] **Queda do Redis não mata fan-out nem produtores** (retry com backoff + `restart: unless-stopped`; `/healthz` reporta `degraded` se o fan-out morrer) → [src/api/core/redis_client.py](src/api/core/redis_client.py), [src/publisher/main.py](src/publisher/main.py)
- [x] **Rate limit no handshake** (30 req/min por IP, HTTP 429) → [nginx/nginx.conf](nginx/nginx.conf)
- [x] **Containers non-root, multi-stage, Redis sem porta pública** → [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml)
- [ ] **Replay de eventos perdidos na reconexão** (`Last-Event-ID`) → exigiria Redis Streams no lugar do Pub/Sub; discutido em [docs/protocol.md](docs/protocol.md)
- [ ] **TLS, rate limit e emissão de token autenticada** → pendências deliberadas do boilerplate, detalhadas em [SECURITY.md](SECURITY.md)

---

## 📄 Licença

MIT — veja [LICENSE](LICENSE).
