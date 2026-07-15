# Anatomia do `text/event-stream`

SSE é um protocolo de texto absurdamente simples: uma resposta HTTP que nunca
termina, com `Content-Type: text/event-stream`, onde cada evento é um bloco de
linhas `campo: valor` encerrado por **uma linha em branco** (`\n\n`).

A implementação executável desta sintaxe está em
[`src/api/sse/formatter.py`](../src/api/sse/formatter.py) (função `encode_sse`),
com testes em [`tests/test_formatter.py`](../tests/test_formatter.py).

## Um evento no fio

```
id: a1b2c3d4e5f6
event: trade
data: {"symbol": "PETR4", "price": 38.42, "change_pct": 1.27}

```

| Campo | Papel |
|-------|-------|
| `data:` | Payload do evento. **Obrigatório** — evento sem `data` não dispara listener. Múltiplas linhas `data:` são concatenadas com `\n` pelo navegador. |
| `event:` | Nome do evento. Define **qual listener** dispara no cliente: `addEventListener('trade', …)`. Sem ele, o evento cai em `onmessage`. |
| `id:` | Identificador do evento. O navegador o guarda e, ao reconectar, envia `Last-Event-ID` — a base para replay (ver limitações abaixo). |
| `retry:` | Instrui o navegador sobre o intervalo de reconexão automática, em ms. Enviamos `retry: 3000` na abertura do stream. |
| `: comentário` | Linha iniciada por `:` é ignorada pelo cliente. É o mecanismo do **heartbeat** (`: keep-alive` a cada 20s — ver [`heartbeat.py`](../src/api/sse/heartbeat.py)). |

## O detalhe que derruba implementações manuais: `\n\n`

O delimitador de evento é a **linha em branco**. Esquecer o `\n\n` final faz o
navegador acumular tudo como um único evento eterno que nunca dispara. É o bug
número 1 de quem serializa SSE na mão — e o motivo de `encode_sse` terminar,
sempre, com `"\n".join(lines) + "\n\n"`.

## Eventos nomeados × `onmessage`

```js
const es = new EventSource('/api/events?token=…');

es.onmessage = (e) => { /* SÓ eventos SEM campo event: */ };

es.addEventListener('log',   (e) => { /* event: log   */ });
es.addEventListener('alert', (e) => { /* event: alert */ });
es.addEventListener('trade', (e) => { /* event: trade */ });
```

Como o FarolStream emite **apenas** eventos nomeados, um cliente que use só
`onmessage` recebe **nada** — silenciosamente. O hook
[`useSSE.ts`](../src/frontend/src/hooks/useSSE.ts) registra um listener por tipo.

## Reconexão e `Last-Event-ID`

O `EventSource` reconecta sozinho ao perder a conexão, reenviando o último `id`
visto no header `Last-Event-ID`. Dois pontos importantes neste projeto:

1. **Redis Pub/Sub é fire-and-forget**: mensagens publicadas enquanto o cliente
   estava desconectado são perdidas. Suportar replay de verdade exigiria trocar
   Pub/Sub por **Redis Streams** (`XADD`/`XREAD` com IDs) — é a evolução natural
   deste boilerplate.
2. **O token do handshake é one-time-use**: a reconexão automática reutilizaria
   a mesma URL (mesmo token) e levaria `401`. Por isso o `useSSE.ts` intercepta
   `onerror`, fecha a conexão e refaz o handshake com token novo.

## Cabeçalhos da resposta

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

`Cache-Control: no-cache` impede caches intermediários de "guardarem" um stream
infinito; `X-Accel-Buffering: no` sinaliza a proxies compatíveis para não
bufferizarem (a configuração explícita e comentada está em
[`nginx/nginx.conf`](../nginx/nginx.conf)).
