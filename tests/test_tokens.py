"""Ciclo de vida do token de handshake: assinatura, expiração e escopo.

O one-time-use (consume_token) depende de Redis e é exercitado de ponta a
ponta pelo quick_start.sh, que prova o 401 na reutilização.
"""

import jwt
import pytest

from config.settings import Settings
from src.api.auth.tokens import SSE_SCOPE, TokenError, decode_sse_token, issue_sse_token


@pytest.fixture
def settings() -> Settings:
    return Settings(jwt_secret="segredo-de-teste-com-32-bytes-ou-mais!", sse_token_ttl_seconds=60)


class TestIssueAndDecode:
    def test_round_trip(self, settings):
        token, ttl = issue_sse_token(settings)
        claims = decode_sse_token(token, settings)
        assert ttl == 60
        assert claims["scope"] == SSE_SCOPE
        assert "jti" in claims

    def test_cada_token_tem_jti_unico(self, settings):
        token_a, _ = issue_sse_token(settings)
        token_b, _ = issue_sse_token(settings)
        jti_a = decode_sse_token(token_a, settings)["jti"]
        jti_b = decode_sse_token(token_b, settings)["jti"]
        assert jti_a != jti_b


class TestRejeicoes:
    def test_token_expirado(self, settings):
        expired = Settings(jwt_secret="segredo-de-teste-com-32-bytes-ou-mais!", sse_token_ttl_seconds=-10)
        token, _ = issue_sse_token(expired)
        with pytest.raises(TokenError, match="expirado"):
            decode_sse_token(token, settings)

    def test_assinatura_invalida(self, settings):
        outra_chave = Settings(jwt_secret="outro-segredo-tambem-com-32-bytes-ok!")
        token, _ = issue_sse_token(outra_chave)
        with pytest.raises(TokenError, match="inválido"):
            decode_sse_token(token, settings)

    def test_escopo_errado(self, settings):
        import time
        import uuid

        now = int(time.time())
        token = jwt.encode(
            {"jti": uuid.uuid4().hex, "scope": "admin:tudo", "iat": now, "exp": now + 60},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError, match="escopo"):
            decode_sse_token(token, settings)

    def test_lixo_nao_e_token(self, settings):
        with pytest.raises(TokenError):
            decode_sse_token("nem.um.jwt", settings)
