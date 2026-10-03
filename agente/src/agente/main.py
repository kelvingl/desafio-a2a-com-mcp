"""Entrypoint: conecta no servidor MCP (host) e sobe o servidor A2A por fora."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette

from agente.a2a_rpc import construir_app
from agente.bridge import Ponte
from agente.card import construir_agent_card
from agente.mcp_client import ClienteMCP
from agente.tasks import TaskStore

logging.basicConfig(level=logging.INFO, format="[agente] %(message)s")


def montar_app() -> Starlette:
    agente_host = os.environ.get("AGENTE_HOST", "127.0.0.1")
    agente_port = int(os.environ.get("AGENTE_PORT", "7300"))
    mcp_url = os.environ.get("MCP_URL", "http://127.0.0.1:7301/mcp")

    mcp_client = ClienteMCP(mcp_url)
    tasks = TaskStore()
    ponte = Ponte(mcp_client, tasks)
    card = construir_agent_card(f"http://{agente_host}:{agente_port}")

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        await mcp_client.conectar()
        try:
            yield
        finally:
            await mcp_client.fechar()

    return construir_app(ponte, tasks, card, lifespan=lifespan)


app = montar_app()


def main() -> None:
    host = os.environ.get("AGENTE_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENTE_PORT", "7300"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
