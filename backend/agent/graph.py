"""
Graphe LangGraph de l'agent énergie.

Boucle classique d'agent à outils :
    agent (LLM) --> a demandé un outil ? --oui--> tools --> agent
                                         --non--> fin (réponse finale)

Deux garde-fous pour les modèles locaux :
  - le schéma de la base est injecté dans le prompt système au démarrage,
    le modèle n'a donc pas à penser à appeler get_schema ;
  - un appel d'outil écrit en texte (défaut fréquent de Qwen via Ollama)
    est détecté et converti en vrai appel d'outil.
"""

from __future__ import annotations

import json
import uuid

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

MODEL_NAME = "qwen2.5:14b"

SYSTEM_PROMPT = """Tu es un analyste du système électrique français.
Tu réponds aux questions à partir d'une base SQLite de données RTE éCO2mix.
Le schéma exact de la base est fourni plus bas : utilise UNIQUEMENT ces noms
de tables, de colonnes et de filières.

Méthode obligatoire :
1. Écris une requête SQL avec l'outil run_query. Agrège toujours les données
   (AVG, SUM, MAX, GROUP BY) au lieu de récupérer des lignes brutes.
2. Écris la requête sur une seule ligne.
3. Si une requête renvoie une erreur, corrige-la et rappelle run_query.
4. Réponds en français, avec les chiffres obtenus et leurs unités (MW, GWh, %).

Syntaxe SQLite (pas PostgreSQL) :
- Pour grouper par jour : strftime('%Y-%m-%d', timestamp)
- Pour grouper par heure : strftime('%H', timestamp)
- Pour grouper par mois : strftime('%Y-%m', timestamp)
- La fonction date_trunc n'existe pas en SQLite.
- Les dates de la base sont en 2026 : filtre sur la période indiquée dans le schéma.
- Pour filtrer un mois : timestamp >= '2026-09-01' AND timestamp < '2026-10-01'
  (borne de fin exclue, jamais <= sur le dernier jour).

Structure de la table production (très important) :
- Chaque relevé de 15 minutes produit UNE LIGNE PAR FILIÈRE (8 lignes).
- Pour une moyenne ou une somme sur UNE filière, filtre dans le WHERE :
  SELECT AVG(puissance_mw) FROM production WHERE filiere = 'eolien';
- N'utilise JAMAIS AVG(CASE WHEN filiere = ... ELSE 0 END) : les lignes des
  autres filières comptent pour 0 et divisent le résultat par 8.
- CASE WHEN ... ELSE 0 n'est correct QUE dans une SUM, pour un calcul de part.

Unités :
- puissance_mw et consommation_mw sont des puissances instantanées en MW,
  relevées toutes les 15 minutes.
- Une SUM de puissances n'est PAS en MW. Pour l'énergie produite ou consommée
  sur une période, calcule SUM(puissance_mw) * 0.25, le résultat est en MWh.
  Divise par 1000 pour des GWh, unité la plus lisible sur une journée.
- Pour une puissance typique sur une période, utilise AVG(puissance_mw), en MW.

Calculs de part ou de pourcentage :
- Calcule la part dans UNE SEULE requête, en divisant une somme par une somme
  sur la même période. Ne divise jamais une moyenne par une somme.
- Exemple, part du nucléaire dans la production :
  SELECT ROUND(100.0 * SUM(CASE WHEN filiere = 'nucleaire' THEN puissance_mw ELSE 0 END) / SUM(puissance_mw), 1) AS part_pct FROM production;

Vérification avant de répondre :
- Contrôle que chaque résultat est plausible. Puissances moyennes typiques
  en France, en MW :
    nucleaire 30 000 à 50 000 | eolien 1 500 à 12 000 | solaire 2 000 à 10 000
    hydraulique 2 000 à 10 000 | gaz 500 à 8 000 | bioenergies 800 à 1 500
    production totale 30 000 à 90 000 | consommation 30 000 à 80 000
- Part du nucléaire : environ 60 à 75 %.
- Un résultat très en dehors de ces fourchettes signale presque toujours une
  erreur de requête (mauvais filtre, mauvaise agrégation) : corrige et refais.

Règles :
- Les horodatages sont en UTC, au pas de 15 minutes. Pour une heure locale
  française, ajoute 2 heures en été (1 heure en hiver) et précise-le.
- N'invente jamais de chiffre : chaque valeur doit venir d'une requête.
- Si la question dépasse la période couverte par la base, dis-le clairement.
"""


def _parse_text_tool_call(content: str, tool_names: set[str]) -> list[dict]:
    """
    Récupère un appel d'outil que le modèle a écrit en texte, du type :
    {"name": "run_query", "arguments": {"sql": "..."}}
    Renvoie une liste vide si le texte ne contient pas d'appel valide.
    """
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict) or data.get("name") not in tool_names:
        return []

    args = data.get("arguments") or data.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return []

    return [
        {
            "name": data["name"],
            "args": args,
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "tool_call",
        }
    ]


def build_graph(tools: list[BaseTool], schema: str):
    llm = ChatOllama(
        model=MODEL_NAME,
        temperature=0,  # réponses stables, important pour écrire du SQL
        num_ctx=16384,  # contexte élargi (4096 par défaut, trop juste)
    ).bind_tools(tools)

    system_message = SystemMessage(f"{SYSTEM_PROMPT}\n\n=== SCHÉMA DE LA BASE ===\n{schema}")
    tool_names = {t.name for t in tools}

    async def call_model(state: MessagesState) -> dict:
        response = await llm.ainvoke([system_message, *state["messages"]])

        # Filet de sécurité : appel d'outil écrit en texte -> vrai appel d'outil
        if not response.tool_calls and isinstance(response.content, str):
            recovered = _parse_text_tool_call(response.content, tool_names)
            if recovered:
                response = AIMessage(content="", tool_calls=recovered)

        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)  # outil demandé -> "tools", sinon fin
    graph.add_edge("tools", "agent")

    return graph.compile()