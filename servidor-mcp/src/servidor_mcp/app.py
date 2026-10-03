"""Monta o MCPServer: tools, resource, logging e protecao do requestState."""

from __future__ import annotations

import json
import os
import sys

from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.server import MCPServer
from mcp.server.request_state import RequestStateSecurity
from mcp.shared.exceptions import MCPError
from mcp_types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
from mcp_types.jsonrpc import INVALID_PARAMS, MISSING_REQUIRED_CLIENT_CAPABILITY
from pydantic import BaseModel

from servidor_mcp.dados import carregar_store
from servidor_mcp.erros import ERRO_DURACAO, ERRO_INTERVALO, ERRO_JANELA, ERRO_SEM_ALTERNATIVA, erro_sala
from servidor_mcp.politica import alternativas, conflitos, dentro_da_janela, duracao_valida, intervalo_valido

CHAVE_ESCOLHA = "reservar_sala:escolha_de_sala"
TTL_REQUEST_STATE_SEGUNDOS = 900.0


def _segredo_request_state() -> str:
    segredo = os.environ.get("REQUEST_STATE_SECRET")
    if not segredo:
        raise RuntimeError(
            "REQUEST_STATE_SECRET nao definido. Gere um com: "
            'python3 -c "import secrets; print(secrets.token_hex(32))" e exporte antes de subir o servidor.'
        )
    if len(segredo.encode()) < 32:
        raise RuntimeError("REQUEST_STATE_SECRET precisa ter pelo menos 32 bytes.")
    return segredo


async def _log_requisicoes(ctx, call_next):
    meta = (ctx.params or {}).get("_meta") or {}
    traceparent = meta.get("traceparent")
    print(
        f"[servidor-mcp] metodo={ctx.method} id={ctx.request_id} traceparent={traceparent}",
        file=sys.stderr,
        flush=True,
    )
    return await call_next(ctx)


STORE = carregar_store()

app = MCPServer(
    name="central-de-salas",
    version="1.0.0",
    request_state_security=RequestStateSecurity(keys=[_segredo_request_state()], ttl=TTL_REQUEST_STATE_SEGUNDOS),
    middleware=[_log_requisicoes],
)


class SalaOut(BaseModel):
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    salas: list[SalaOut]


class ConflitoOut(BaseModel):
    id: str
    inicio: str
    fim: str
    responsavel: str


class Disponibilidade(BaseModel):
    sala: str
    livre: bool
    conflitos: list[ConflitoOut]


class ReservaOut(BaseModel):
    reserva: str | None = None
    reservado: bool = True
    sala: str | None = None
    inicio: str | None = None
    fim: str | None = None
    responsavel: str | None = None
    politica: str | None = None
    motivo: str | None = None


def _validar_pedido(sala: str, inicio: str, fim: str) -> None:
    if STORE.sala_por_id(sala) is None:
        raise ToolError(erro_sala(sala))
    if not dentro_da_janela(inicio, fim):
        raise ToolError(ERRO_JANELA)
    if not duracao_valida(inicio, fim):
        raise ToolError(ERRO_DURACAO)
    if not intervalo_valido(inicio, fim):
        raise ToolError(ERRO_INTERVALO)


@app.tool(description="Lista todas as salas com capacidade e recursos.")
def listar_salas() -> ListaDeSalas:
    return ListaDeSalas(
        salas=[SalaOut(id=s.id, nome=s.nome, capacidade=s.capacidade, recursos=s.recursos) for s in STORE.salas]
    )


@app.tool(description="Diz se uma sala esta livre no intervalo, e quais reservas conflitam.")
def consultar_disponibilidade(sala: str, inicio: str, fim: str) -> Disponibilidade:
    _validar_pedido(sala, inicio, fim)
    conf = conflitos(sala, inicio, fim, STORE.reservas)
    return Disponibilidade(
        sala=sala,
        livre=not conf,
        conflitos=[ConflitoOut(id=c.id, inicio=c.inicio, fim=c.fim, responsavel=c.responsavel) for c in conf],
    )


def _exigir_capacidade_elicitation(ctx: Context) -> None:
    caps = ctx.client_capabilities
    elicitation = caps.elicitation if caps is not None else None
    if elicitation is not None and elicitation.form is not None:
        return
    raise MCPError(
        code=MISSING_REQUIRED_CLIENT_CAPABILITY,
        message="Client did not declare the form elicitation capability required by reservar_sala",
        data={"requiredCapabilities": {"elicitation": {"form": {}}}},
    )


def _requestState_invalido() -> MCPError:
    return MCPError(code=INVALID_PARAMS, message="Invalid or expired requestState")


def _retomar(inicio: str, fim: str, responsavel: str, ctx: Context) -> ReservaOut:
    assert ctx.request_state is not None
    try:
        estado = json.loads(ctx.request_state)
        chave = estado["chave"]
        alts: list[str] = estado["alternativas"]
    except (ValueError, KeyError, TypeError) as exc:
        raise _requestState_invalido() from exc

    resposta = (ctx.input_responses or {}).get(chave)
    if resposta is None:
        raise _requestState_invalido()

    if resposta.action in ("decline", "cancel"):
        return ReservaOut(reservado=False, motivo="recusado")

    conteudo = resposta.content or {}
    sala_escolhida = conteudo.get("sala")
    if sala_escolhida not in alts:
        raise _requestState_invalido()

    reserva = STORE.criar_reserva(sala_escolhida, inicio, fim, responsavel)
    return ReservaOut(
        reserva=reserva.id,
        reservado=True,
        sala=sala_escolhida,
        inicio=inicio,
        fim=fim,
        responsavel=responsavel,
        politica=STORE.politica_versao,
        motivo=None,
    )


@app.tool(description="Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar.")
def reservar_sala(
    sala: str, inicio: str, fim: str, responsavel: str, ctx: Context
) -> ReservaOut | InputRequiredResult:
    _validar_pedido(sala, inicio, fim)

    if ctx.request_state is not None:
        return _retomar(inicio, fim, responsavel, ctx)

    conf = conflitos(sala, inicio, fim, STORE.reservas)
    if not conf:
        reserva = STORE.criar_reserva(sala, inicio, fim, responsavel)
        return ReservaOut(
            reserva=reserva.id,
            reservado=True,
            sala=sala,
            inicio=inicio,
            fim=fim,
            responsavel=responsavel,
            politica=STORE.politica_versao,
            motivo=None,
        )

    alts = alternativas(sala, inicio, fim, STORE.salas, STORE.reservas)
    if not alts:
        raise ToolError(ERRO_SEM_ALTERNATIVA)

    _exigir_capacidade_elicitation(ctx)

    schema = {
        "type": "object",
        "properties": {
            "sala": {
                "type": "string",
                "enum": alts,
                "title": "Sala",
                "description": "Sala alternativa escolhida",
            }
        },
        "required": ["sala"],
    }
    estado = json.dumps({"chave": CHAVE_ESCOLHA, "alternativas": alts})
    return InputRequiredResult(
        input_requests={
            CHAVE_ESCOLHA: ElicitRequest(
                params=ElicitRequestFormParams(
                    message="A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa.",
                    requested_schema=schema,
                )
            )
        },
        request_state=estado,
    )


@app.resource("politica://uso", mime_type="text/markdown", description="Politica de uso das salas de reuniao.")
def politica_de_uso() -> str:
    return STORE.politica_texto
