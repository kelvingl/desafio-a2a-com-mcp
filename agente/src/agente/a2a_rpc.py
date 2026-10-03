"""Endpoint A2A: GET do Agent Card e o binding JSON-RPC 2.0 em /a2a (SendMessage, GetTask)."""

from __future__ import annotations

import logging
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agente.bridge import ErroA2A, Ponte
from agente.tasks import TaskStore

logger = logging.getLogger(__name__)


def construir_app(ponte: Ponte, tasks: TaskStore, card: dict[str, Any], lifespan: Any = None) -> Starlette:
    async def agent_card(request: Request) -> JSONResponse:
        return JSONResponse(card)

    async def a2a(request: Request) -> JSONResponse:
        corpo = await request.json()
        rpc_id = corpo.get("id")
        metodo = corpo.get("method")
        params = corpo.get("params") or {}
        traceparent = request.headers.get("traceparent")

        try:
            if metodo == "SendMessage":
                mensagem = params.get("message") or {}
                texto = " ".join(p.get("text", "") for p in mensagem.get("parts") or [])
                task_id = mensagem.get("taskId")
                task = await ponte.enviar_mensagem(texto, task_id, traceparent)
                return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {"task": task.to_wire()}})

            if metodo == "GetTask":
                task = tasks.obter(params.get("id"))
                if task is None:
                    raise ErroA2A(f"Task desconhecida: {params.get('id')}")
                return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {"task": task.to_wire()}})

            return JSONResponse(
                {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": f"Metodo desconhecido: {metodo}"}}
            )
        except ErroA2A as exc:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32000, "message": exc.message}})
        except Exception:
            logger.exception("falha inesperada processando %s", metodo)
            return JSONResponse(
                {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "Erro interno"}}
            )

    return Starlette(
        routes=[
            Route("/.well-known/agent-card.json", agent_card, methods=["GET"]),
            Route("/a2a", a2a, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
