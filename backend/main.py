"""
API FastAPI de l'agent énergie.

Au démarrage, l'API lance les serveurs MCP, charge leurs outils et construit
le graphe LangGraph une seule fois. Chaque question passe ensuite par l'agent.

Lancement (depuis la racine du projet, Ollama démarré) :
    uvicorn backend.main:app --reload
Documentation interactive : http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from backend.agent.graph import MODEL_NAME, build_graph
from backend.agent.mcp_client import load_mcp_tools


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Les serveurs MCP restent ouverts pendant toute la vie de l'API
    async with load_mcp_tools() as tools:
        schema = await next(t for t in tools if t.name == "get_schema").ainvoke({})
        app.state.tools = tools
        app.state.agent = build_graph(tools, schema)
        yield


app = FastAPI(
    title="Energy MCP Agent",
    description="Agent IA qui répond en français sur l'électricité et la météo en France "
    "(RTE éCO2mix + Open-Meteo), via des serveurs MCP et LangGraph.",
    version="1.1.0",
    lifespan=lifespan,
)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Quelle est la part du nucléaire en août ?"])
    history: list[Message] = Field(default_factory=list, description="Échanges précédents (optionnel)")


class ToolCall(BaseModel):
    name: str
    args: dict


class AskResponse(BaseModel):
    answer: str
    tool_calls: list[ToolCall]
    model: str


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """La racine renvoie vers la documentation interactive."""
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME}


@app.get("/tools")
def list_tools() -> list[dict]:
    """Outils MCP disponibles pour l'agent."""
    return [{"name": t.name, "description": t.description} for t in app.state.tools]


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """Pose une question à l'agent et renvoie sa réponse et les outils utilisés."""
    messages: list[BaseMessage] = [
        HumanMessage(m.content) if m.role == "user" else AIMessage(m.content)
        for m in request.history
    ]
    messages.append(HumanMessage(request.question))

    try:
        result = await app.state.agent.ainvoke(
            {"messages": messages},
            config={"recursion_limit": 20},  # garde-fou contre les boucles
        )
    except GraphRecursionError:
        raise HTTPException(status_code=504, detail="L'agent n'a pas abouti (trop d'itérations).")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur de l'agent : {exc}")

    new_messages = result["messages"][len(messages):]
    calls = [
        ToolCall(name=c["name"], args=c["args"])
        for m in new_messages
        if isinstance(m, AIMessage)
        for c in m.tool_calls
    ]
    return AskResponse(answer=str(result["messages"][-1].content), tool_calls=calls, model=MODEL_NAME)
