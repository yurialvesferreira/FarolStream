"""A sintaxe do protocolo (docs/protocol.md) é a parte mais fácil de errar —
estes testes fixam o contrato de serialização e a validação na borda."""

import json

from src.api.sse.formatter import ALLOWED_EVENT_TYPES, encode_sse, to_server_sent_event


class TestEncodeSSE:
    def test_evento_completo_com_todos_os_campos(self):
        wire = encode_sse('{"x": 1}', event="trade", event_id="abc123", retry=3000)
        assert wire == 'id: abc123\nevent: trade\nretry: 3000\ndata: {"x": 1}\n\n'

    def test_termina_sempre_com_linha_em_branco(self):
        # Sem o \n\n final o navegador nunca dispara o evento.
        assert encode_sse("payload").endswith("\n\n")

    def test_payload_multilinha_vira_multiplas_linhas_data(self):
        wire = encode_sse("linha1\nlinha2")
        assert wire == "data: linha1\ndata: linha2\n\n"

    def test_payload_vazio_ainda_emite_data(self):
        assert encode_sse("") == "data: \n\n"


class TestToServerSentEvent:
    def _envelope(self, event_type: str = "log") -> str:
        return json.dumps({"id": "abc", "type": event_type, "data": {"k": "v"}})

    def test_envelope_valido_vira_evento_nomeado(self):
        event = to_server_sent_event(self._envelope("alert"))
        assert event is not None
        assert event.event == "alert"
        assert event.id == "abc"
        assert json.loads(event.data) == {"k": "v"}

    def test_tipo_desconhecido_e_descartado(self):
        assert to_server_sent_event(self._envelope("hack")) is None

    def test_json_malformado_e_descartado(self):
        assert to_server_sent_event("{nem json}") is None

    def test_envelope_sem_campos_obrigatorios_e_descartado(self):
        assert to_server_sent_event(json.dumps({"type": "log"})) is None

    def test_todos_os_tipos_permitidos_passam(self):
        for event_type in ALLOWED_EVENT_TYPES:
            assert to_server_sent_event(self._envelope(event_type)) is not None
