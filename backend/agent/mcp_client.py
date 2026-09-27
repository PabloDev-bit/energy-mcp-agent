"""
Client MCP de l'agent.

Lance chaque serveur MCP comme sous-processus (transport stdio), récupère la
liste de ses outils, puis les convertit en outils LangChain utilisables par
LangGraph. Ajouter un serveur = ajouter une entrée dans MCP_SERVERS.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.tools import StructuredTool
from mcp import Client, StdioServerParameters
from mcp.types import TextContent

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Serveurs MCP branchés sur l'agent (on ajoutera rte-data et viz ici)
MCP_SERVERS: dict[str, StdioServerParameters] = {
    "sql": StdioServerParameters(
        command=sys.executable,  # le Python du venv actif
        args=["-m", "backend.mcp_servers.sql_query_server.server"],
        cwd=str(PROJECT_ROOT),
    ),
}


def _result_to_text(result: Any) -> str:
    """Convertit le résultat MCP en texte lisible par le LLM."""
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    text = "\n".join(texts) if texts else "(réponse vide)"
    return f"ERREUR OUTIL : {text}" if result.is_error else text


def _make_langchain_tool(client: Client, mcp_tool: Any) -> StructuredTool:
    """Enveloppe un outil MCP dans un outil LangChain."""

    async def _call(**kwargs: Any) -> str:
        result = await client.call_tool(mcp_tool.name, kwargs)
        return _result_to_text(result)

    return StructuredTool(
        name=mcp_tool.name,
        description=mcp_tool.description or mcp_tool.name,
        args_schema=mcp_tool.input_schema,  # schéma JSON généré par le serveur MCP
        coroutine=_call,
    )


@asynccontextmanager
async def load_mcp_tools() -> AsyncIterator[list[StructuredTool]]:
    """
    Démarre tous les serveurs MCP et fournit leurs outils.
    Les connexions restent ouvertes tant qu'on est dans le bloc `async with`.
    """
    async with AsyncExitStack() as stack:
        tools: list[StructuredTool] = []
        for params in MCP_SERVERS.values():
            client = await stack.enter_async_context(Client(params))
            listed = await client.list_tools()
            tools.extend(_make_langchain_tool(client, t) for t in listed.tools)
        yield tools