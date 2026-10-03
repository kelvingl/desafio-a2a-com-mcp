"""O agente como host MCP: um unico Client vivo falando Streamable HTTP com o
servidor MCP, sempre expondo o resultado cru do tools/call (nunca deixando o
SDK resolver sozinho uma elicitation em modo sincrono)."""

from __future__ import annotations

import logging
import re
from typing import Any

import mcp_types as types
from mcp.client.client import Client

from agente.trace import novo_traceparent

logger = logging.getLogger(__name__)

_VERSAO_RE = re.compile(r"^versao:\s*(\S+)", re.MULTILINE)

ResultadoToolCall = types.CallToolResult | types.InputRequiredResult


async def _elicitation_nunca_usada(
    context: Any, params: types.ElicitRequestParams
) -> types.ElicitResult | types.ErrorData:
    """Nosso servidor so fala MRTR via InputRequiredResult; uma elicitation sincrona
    nunca deveria chegar aqui. Existe apenas para declarar a capability no handshake
    (a sessao so marca elicitation.form quando ha um callback nao-default)."""
    logger.warning("elicitation sincrona recebida inesperadamente; recusando")
    return types.ElicitResult(action="decline")


def _extrair_versao_politica(texto: str) -> str:
    m = _VERSAO_RE.search(texto)
    if not m:
        raise ValueError("politica://uso sem linha 'versao: <data>'")
    return m.group(1)


class ClienteMCP:
    """Host MCP do agente: conecta uma vez, descobre as tools, le a politica."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._client: Client | None = None
        self.politica_versao: str = ""
        self._ferramentas: list[str] = []

    async def conectar(self) -> None:
        self._client = Client(self.url, mode="2026-07-28", elicitation_callback=_elicitation_nunca_usada)
        await self._client.__aenter__()

        listagem = await self._client.session.list_tools()
        self._ferramentas = sorted(t.name for t in listagem.tools)
        logger.info("tools/list descobriu: %s", self._ferramentas)
        if "reservar_sala" not in self._ferramentas:
            raise RuntimeError("o servidor MCP nao expoe a tool reservar_sala")

        leitura = await self._client.session.read_resource("politica://uso", allow_input_required=True)
        if isinstance(leitura, types.InputRequiredResult):
            raise RuntimeError("leitura de politica://uso nao deveria pedir input")
        texto = leitura.contents[0].text
        self.politica_versao = _extrair_versao_politica(texto)
        logger.info("politica://uso versao=%s", self.politica_versao)

    async def fechar(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    def _meta(self, trace_id: str | None) -> dict[str, Any] | None:
        return {"traceparent": novo_traceparent(trace_id)} if trace_id else None

    async def reservar(
        self, sala: str, inicio: str, fim: str, responsavel: str, trace_id: str | None = None
    ) -> ResultadoToolCall:
        assert self._client is not None, "ClienteMCP.conectar() precisa rodar antes de qualquer chamada"
        return await self._client.session.call_tool(
            "reservar_sala",
            {"sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel},
            meta=self._meta(trace_id),
            allow_input_required=True,
        )

    async def retomar(
        self,
        sala: str,
        inicio: str,
        fim: str,
        responsavel: str,
        chave: str,
        resposta: dict[str, Any],
        request_state: str,
        trace_id: str | None = None,
    ) -> ResultadoToolCall:
        assert self._client is not None, "ClienteMCP.conectar() precisa rodar antes de qualquer chamada"
        return await self._client.session.call_tool(
            "reservar_sala",
            {"sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel},
            input_responses={chave: resposta},
            request_state=request_state,
            meta=self._meta(trace_id),
            allow_input_required=True,
        )
