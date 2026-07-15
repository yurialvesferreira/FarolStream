# Segurança

Este documento descreve as decisões de segurança do FarolStream e o que
**precisa** mudar antes de levar o padrão para produção de verdade.

## O problema central: autenticar `EventSource`

O `EventSource` do navegador não permite headers customizados — não existe
`Authorization: Bearer` para SSE nativo. As opções reais são cookie (exige
mesmo domínio e cuidado com CSRF) ou **query string**. Este projeto usa query
string, que é a mais portável, e trata o risco de vazamento de URL com defesa
em profundidade:

| Camada | Implementação |
|--------|---------------|
| **TTL de 60s** | O token expira um minuto após a emissão ([`tokens.py`](src/api/auth/tokens.py)) — a janela para replay é mínima. |
| **One-time-use** | O `jti` é marcado como consumido com `SET NX` atômico no Redis; um token interceptado **depois** do handshake não abre outra conexão. |
| **Escopo mínimo** | O token carrega `scope: sse:events` — não é a sessão do usuário; se vazar, não dá acesso a mais nada. |
| **Fora dos logs** | O `log_format` do Nginx usa `$uri` (sem query string), então o token nunca aparece no access log ([`nginx/nginx.conf`](nginx/nginx.conf)). |

## Tokens em logs

O vazamento mais provável de um token em query string não é interceptação de
rede (TLS resolve isso) — é **log de acesso**. Auditoria rápida em qualquer
projeto que use este padrão:

- Nginx/proxies: o formato de log inclui `$request` ou `$args`? Troque por `$uri`.
- APM/tracing: a URL completa vai para o Datadog/Sentry? Configure scrubbing.
- Frontend: a URL do stream nunca deve virar `href` nem ser passada a
  `history.pushState`.

## CORS

`CORSMiddleware` restrito à origem do dashboard (`CORS_ORIGINS` no `.env`).
No compose, o fluxo inteiro passa pelo Nginx na mesma origem
(`http://localhost:8080`), então o CORS nem chega a ser exercitado — mas está
configurado para o caso de o dashboard ser servido de outro domínio.
**Nunca use `*` com endpoints autenticados.**

## TTL do JWT

`SSE_TOKEN_TTL_SECONDS=60` é deliberadamente curto: o token serve para UM
handshake, não para a sessão. Se o front demorar mais de 60s entre pedir o
token e abrir o stream, o correto é pedir outro (o `useSSE.ts` já faz isso no
fluxo de reconexão). Aumentar o TTL para "resolver" um 401 é tratar o sintoma
e alargar a janela de ataque.

## Antes de produção

- [ ] **TLS**: o compose expõe HTTP puro. Em produção, o Nginx termina TLS
      (ou fica atrás de um LB que o faça). Token em query string sem TLS é
      token público.
- [ ] **Autenticar a emissão**: `/auth/sse-token` está aberto no boilerplate.
      Em produção ele fica atrás da sessão real (cookie/Bearer) e o token SSE
      herda o `sub` do usuário.
- [ ] **`JWT_SECRET` forte e rotacionável**: o `quick_start.sh` gera um
      aleatório para dev; em produção, use um gerenciador de segredos, não
      `.env` commitado.
- [ ] **Rate limit** em `/auth/sse-token` (ex.: `limit_req` no Nginx) para
      impedir farm de tokens.
- [ ] **Limite de streams por usuário** no `EventBroker`, para conter abuso de
      conexões abertas.

## Postura dos containers

Todos os serviços rodam **non-root** (usuário `farol` dedicado, sem shell e
sem home), imagens multi-stage sem toolchain de build no runtime, e o Redis
não expõe porta para o host — só a rede interna do compose fala com ele.
A única porta pública é a 8080 do Nginx.

## Reportando vulnerabilidades

Abra uma issue no repositório ou contate o mantenedor. Este é um projeto
educacional — ainda assim, reports são bem-vindos.
