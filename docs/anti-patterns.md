# Anti-padrões de SSE (e como este repo evita cada um)

## 1. O "Falso SSE" — polling disfarçado de stream

O anti-padrão mais comum: um endpoint com `Content-Type: text/event-stream`
que **encerra a resposta após enviar um evento**, forçando o `EventSource` a
reconectar em loop. O resultado é polling HTTP com custo de handshake completo
a cada evento — pior que polling honesto, porque *parece* tempo real.

```python
# ❌ FALSO SSE: responde uma vez e fecha — o EventSource reconecta em loop
@app.get("/events")
async def fake_sse():
    event = await get_latest_event()
    return Response(
        f"data: {event}\n\n",
        media_type="text/event-stream",
    )  # a resposta TERMINA aqui; isso é polling com fantasia de stream
```

```python
# ✅ SSE REAL: um gerador que NUNCA retorna enquanto o cliente estiver vivo
@router.get("/events")
async def stream_events(request: Request):
    async def event_source():
        while True:                      # a conexão fica aberta
            raw = await queue.get()      # espera o próximo evento
            yield to_server_sent_event(raw)
    return EventSourceResponse(event_source())
```

Como diferenciar na prática: abra o DevTools → aba Network. No falso SSE, você
vê **uma requisição nova a cada evento**; no SSE real, **uma única requisição**
com status "pending" para sempre. Implementação real:
[`src/api/sse/stream.py`](../src/api/sse/stream.py).

## 2. Uma conexão Redis por cliente conectado

```python
# ❌ Cada stream abre seu próprio SUBSCRIBE:
#    1.000 abas = 1.000 conexões Redis
async def event_source():
    redis = aioredis.from_url(REDIS_URL)   # conexão nova POR REQUEST
    pubsub = redis.pubsub()
    await pubsub.subscribe("farol:events")
    ...
```

O Redis aguenta, até não aguentar — e quando o limite de conexões chega, cai
tudo de uma vez. A solução é **multiplexar**: uma única assinatura por processo
(Singleton) distribuindo para N filas em memória, uma por stream.
Implementação: [`src/api/core/redis_client.py`](../src/api/core/redis_client.py)
(`EventBroker`).

## 3. Zombie listeners — ninguém limpa quando o cliente desconecta

O cliente fechou a aba, mas o servidor continua com a fila dele registrada,
acumulando eventos que ninguém vai ler. Multiplique por milhares de conexões
ao longo de dias e você tem um memory leak de crescimento lento — o pior tipo.

A defesa tem duas camadas em [`stream.py`](../src/api/sse/stream.py):

- o loop verifica `await request.is_disconnected()` a cada ciclo;
- o `finally` chama `broker.unsubscribe(queue)` — roda **sempre**, inclusive
  quando o sse-starlette cancela o gerador.

E o espelho no cliente: [`useSSE.ts`](../src/frontend/src/hooks/useSSE.ts)
fecha o `EventSource` e cancela timers no cleanup do `useEffect`.

## 4. Sem heartbeat — o proxy derruba conexões saudáveis

SSE pode passar minutos sem tráfego (nenhum evento aconteceu). Para o Nginx com
`proxy_read_timeout` default de **60s**, silêncio é indistinguível de backend
morto — e a conexão cai. O cliente reconecta, fica 60s, cai de novo. O sistema
"funciona", com uma tempestade invisível de reconexões.

Defesa dupla, e os dois lados precisam existir:

- **Aplicação**: comentário `: keep-alive` a cada 20s
  ([`heartbeat.py`](../src/api/sse/heartbeat.py));
- **Proxy**: `proxy_read_timeout 3600s` + `proxy_buffering off`
  ([`nginx/nginx.conf`](../nginx/nginx.conf)).

Invariante a manter: `heartbeat < proxy_read_timeout`, com folga.

## 5. `onmessage` para eventos nomeados

```js
// ❌ Nunca dispara: todos os eventos deste stream têm campo `event:`
es.onmessage = (e) => render(e.data);

// ✅ Um listener por tipo nomeado
es.addEventListener('log',   renderLog);
es.addEventListener('alert', renderAlert);
es.addEventListener('trade', renderTrade);
```

O pior bug é o silencioso: nada quebra, nada aparece. Ver
[`useSSE.ts`](../src/frontend/src/hooks/useSSE.ts).

## 6. Token de sessão de longa duração na query string

`EventSource` não aceita headers → o token vai na URL → a URL vaza (histórico,
logs, `Referer`). Colocar o JWT de sessão de 24h ali é entregar a conta do
usuário para qualquer log de acesso. A alternativa: um token **dedicado ao
handshake**, com 60s de TTL, escopo mínimo e one-time-use — detalhado em
[`SECURITY.md`](../SECURITY.md) e implementado em
[`src/api/auth/tokens.py`](../src/api/auth/tokens.py).

## 7. WebSocket para um problema unidirecional

Não é bug, é excesso de arquitetura: se o fluxo é só servidor → cliente
(feeds, notificações, dashboards), WebSocket traz um protocolo com upgrade,
enquadramento binário e bibliotecas client-side — para não usar a metade
bidirecional. SSE é HTTP puro: passa por proxies comuns, tem reconexão nativa
com `Last-Event-ID` e o cliente é built-in no navegador. Use WebSocket quando o
**cliente** também precisa falar (chat, jogos, edição colaborativa).
