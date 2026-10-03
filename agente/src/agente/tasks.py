"""Maquina de estados da Task A2A e o estado pausado (por Task, em memoria)."""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from agente.parsing import PedidoReserva

SUBMITTED = "TASK_STATE_SUBMITTED"
WORKING = "TASK_STATE_WORKING"
INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
COMPLETED = "TASK_STATE_COMPLETED"
CANCELED = "TASK_STATE_CANCELED"
FAILED = "TASK_STATE_FAILED"

TERMINAIS = {COMPLETED, CANCELED, FAILED}


def _novo_id(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_hex(6)}"


@dataclass
class Pending:
    """O que o servidor MCP pediu, guardado por Task - nunca exposto ao cliente A2A."""

    chave: str
    request_state: str
    alternativas: list[str]
    pedido: PedidoReserva
    trace_id: str | None


@dataclass
class Task:
    id: str
    context_id: str
    state: str = SUBMITTED
    history: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    pending: Pending | None = None
    _ultima_mensagem_agente: dict[str, Any] | None = field(default=None, repr=False)

    def is_terminal(self) -> bool:
        return self.state in TERMINAIS

    def adicionar_usuario(self, texto: str, com_task_id: bool = False) -> None:
        msg: dict[str, Any] = {
            "messageId": _novo_id("msg"),
            "role": "ROLE_USER",
            "parts": [{"text": texto}],
        }
        if com_task_id:
            msg["taskId"] = self.id
        self.history.append(msg)

    def adicionar_agente(self, texto: str) -> None:
        msg: dict[str, Any] = {
            "messageId": _novo_id("msg"),
            "role": "ROLE_AGENT",
            "parts": [{"text": texto}],
            "taskId": self.id,
            "contextId": self.context_id,
        }
        self.history.append(msg)
        self._ultima_mensagem_agente = msg

    def adicionar_artifact_reserva(self, dados: dict[str, Any]) -> None:
        conteudo = {
            "reserva": dados.get("reserva"),
            "sala": dados.get("sala"),
            "inicio": dados.get("inicio"),
            "fim": dados.get("fim"),
            "responsavel": dados.get("responsavel"),
            "politica": dados.get("politica"),
        }
        self.artifacts.append(
            {
                "artifactId": _novo_id("art"),
                "name": "reserva",
                "parts": [{"text": json.dumps(conteudo)}],
            }
        )

    def to_wire(self) -> dict[str, Any]:
        status: dict[str, Any] = {"state": self.state}
        if self._ultima_mensagem_agente is not None:
            status["message"] = self._ultima_mensagem_agente
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": status,
            "history": list(self.history),
            "artifacts": list(self.artifacts),
        }


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def criar(self) -> Task:
        with self._lock:
            task = Task(id=_novo_id("task"), context_id=_novo_id("ctx"))
            self._tasks[task.id] = task
            return task

    def obter(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)
