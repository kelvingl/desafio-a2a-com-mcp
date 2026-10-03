"""A ponte: onde o input_required do MCP vira TASK_STATE_INPUT_REQUIRED, e onde
o requestState volta para o servidor no retry.

O agente nao decide regra de negocio nenhuma aqui - so traduz protocolo: guarda o
que o servidor MCP pediu (chave, requestState opaco, alternativas) associado a Task,
e refaz o tools/call original com um id de JSON-RPC novo quando o cliente A2A responde.
"""

from __future__ import annotations

from typing import Any

import mcp_types as types

from agente.mcp_client import ClienteMCP
from agente.parsing import PedidoReserva, parse_escolha, parse_pedido_reserva
from agente.tasks import CANCELED, COMPLETED, FAILED, INPUT_REQUIRED, WORKING, Pending, Task, TaskStore
from agente.trace import trace_id_de


class ErroA2A(Exception):
    """Erro de protocolo A2A (vira `error` no JSON-RPC, nunca um `result`)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Ponte:
    def __init__(self, mcp: ClienteMCP, tasks: TaskStore) -> None:
        self.mcp = mcp
        self.tasks = tasks

    async def enviar_mensagem(self, texto: str, task_id: str | None, traceparent: str | None) -> Task:
        trace_id = trace_id_de(traceparent)

        if task_id is not None:
            task = self.tasks.obter(task_id)
            if task is None:
                raise ErroA2A(f"Task desconhecida: {task_id}")
            if task.is_terminal():
                raise ErroA2A(f"Task {task_id} esta em estado terminal ({task.state})")
            await self._continuar(task, texto, trace_id)
            return task

        task = self.tasks.criar()
        task.adicionar_usuario(texto)
        task.state = WORKING

        pedido = parse_pedido_reserva(texto)
        if pedido is None:
            task.state = FAILED
            task.adicionar_agente(f"Pedido em formato invalido: {texto}")
            return task

        resultado = await self.mcp.reservar(pedido.sala, pedido.inicio, pedido.fim, pedido.responsavel, trace_id)
        self._tratar_resultado(task, pedido, resultado, trace_id)
        return task

    async def _continuar(self, task: Task, texto: str, trace_id_novo: str | None) -> None:
        pending = task.pending
        if pending is None:
            raise ErroA2A(f"Task {task.id} nao esta aguardando uma escolha")

        task.adicionar_usuario(texto, com_task_id=True)
        valor = parse_escolha(texto)

        if valor == "recusar":
            resposta_wire: dict[str, Any] = {"action": "decline"}
        elif valor is not None and valor in pending.alternativas:
            resposta_wire = {"action": "accept", "content": {"sala": valor}}
        else:
            # Fora do enum (ou fora do formato fixo): mantem a Task pausada e repete a pergunta.
            task.adicionar_agente(f"alternativas: {', '.join(pending.alternativas)}")
            return

        trace_id = trace_id_novo or pending.trace_id
        resultado = await self.mcp.retomar(
            pending.pedido.sala,
            pending.pedido.inicio,
            pending.pedido.fim,
            pending.pedido.responsavel,
            pending.chave,
            resposta_wire,
            pending.request_state,
            trace_id,
        )
        self._tratar_resultado(task, pending.pedido, resultado, trace_id)

    def _tratar_resultado(
        self, task: Task, pedido: PedidoReserva, resultado: types.CallToolResult | types.InputRequiredResult, trace_id: str | None
    ) -> None:
        if isinstance(resultado, types.InputRequiredResult):
            chave = next(iter(resultado.input_requests or {}))
            schema = resultado.input_requests[chave].params.requested_schema
            propriedade_sala = (schema.get("properties") or {}).get("sala", {})
            alternativas = propriedade_sala.get("enum") or (
                [propriedade_sala["const"]] if "const" in propriedade_sala else []
            )
            task.pending = Pending(
                chave=chave,
                request_state=resultado.request_state or "",
                alternativas=alternativas,
                pedido=pedido,
                trace_id=trace_id,
            )
            task.state = INPUT_REQUIRED
            task.adicionar_agente(f"alternativas: {', '.join(alternativas)}")
            return

        if resultado.is_error:
            texto_erro = " ".join(p.text for p in resultado.content if isinstance(p, types.TextContent))
            task.pending = None
            task.state = FAILED
            task.adicionar_agente(texto_erro)
            return

        dados = resultado.structured_content or {}
        task.pending = None
        if dados.get("reservado") is False:
            task.state = CANCELED
            task.adicionar_agente(f"Reserva cancelada: {dados.get('motivo') or 'recusado'}.")
            return

        task.state = COMPLETED
        task.adicionar_artifact_reserva(dados)
        task.adicionar_agente(f"Reserva {dados.get('reserva')} confirmada na {dados.get('sala')}.")
