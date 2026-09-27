"""
Chat en ligne de commande avec l'agent énergie.

Lancement (depuis la racine du projet) :
    python -m backend.scripts.chat_cli
Tape "exit" pour quitter.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from backend.agent.graph import MODEL_NAME, build_graph
from backend.agent.mcp_client import load_mcp_tools


async def main() -> None:
    async with load_mcp_tools() as tools:
        print(f"Modèle : {MODEL_NAME}")
        print(f"Outils MCP chargés : {', '.join(t.name for t in tools)}")

        # Récupère le schéma une fois, via le serveur MCP, pour l'injecter dans le prompt
        schema_tool = next(t for t in tools if t.name == "get_schema")
        schema = await schema_tool.ainvoke({})
        print("Schéma de la base chargé.")
        print('Pose ta question (ou "exit" pour quitter).')

        app = build_graph(tools, schema)
        history: list[BaseMessage] = []

        while True:
            question = (await asyncio.to_thread(input, "\nToi > ")).strip()
            if question.lower() in {"exit", "quit", "q"}:
                break
            if not question:
                continue

            history.append(HumanMessage(question))
            result = await app.ainvoke(
                {"messages": history},
                config={"recursion_limit": 20},  # garde-fou contre les boucles infinies
            )

            # Affiche les appels d'outils faits pendant ce tour
            for msg in result["messages"][len(history):]:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for call in msg.tool_calls:
                        print(f"  [outil] {call['name']} {call['args']}")

            history = result["messages"]
            print(f"\nAgent > {history[-1].content}")


if __name__ == "__main__":
    asyncio.run(main())