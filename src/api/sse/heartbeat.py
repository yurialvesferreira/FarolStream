"""Heartbeat do stream: comentário `: keep-alive` em intervalo fixo.

Linhas que começam com `:` são comentários no protocolo SSE — o navegador
as ignora, mas elas mantêm bytes fluindo na conexão. Sem isso, qualquer
intermediário com timeout de leitura (Nginx, load balancers, NATs) derruba
a conexão ociosa e o cliente entra em loop de reconexão.

Regra de ouro: intervalo do heartbeat < proxy_read_timeout do Nginx.
Aqui: 20s de heartbeat vs 3600s de proxy_read_timeout (ver nginx/nginx.conf).
"""

from sse_starlette.sse import ServerSentEvent


def keep_alive_factory() -> ServerSentEvent:
    """Fábrica usada pelo EventSourceResponse a cada ciclo de ping."""
    return ServerSentEvent(comment="keep-alive")
