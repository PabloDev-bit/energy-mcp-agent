# Energy MCP Agent

Agent IA qui répond en français à des questions sur l'électricité et la météo en France.
Il croise les données **RTE éCO2mix** (production par filière et consommation) avec la
météo **Open-Meteo**, en passant par des **serveurs MCP** (Model Context Protocol)
orchestrés par **LangGraph**, avec un **LLM local via Ollama** (aucune API payante).

Exemples de questions :
- « Quelle est la part du nucléaire dans la production en août ? »
- « Quels ont été les jours les plus venteux, et la production éolienne ces jours-là ? »
- « Quel est le mix électrique en ce moment ? »
- « Quel temps est prévu à Bordeaux demain ? »

## Architecture

```
Question ──> FastAPI (/ask) ou chat CLI
                │
                ▼
         Agent LangGraph (Qwen 2.5 14B via Ollama)
         boucle : LLM ──> outil ──> LLM ──> réponse
                │
      ┌─────────┴──────────────────────┐
      ▼                                ▼
 MCP sql-query-server            MCP energy-data-server
 - get_schema                    - get_live_mix (RTE temps réel)
 - run_query (SELECT seul,       - get_weather_forecast (Open-Meteo)
   lecture seule)                - get_data_coverage
      │
      ▼
 SQLite data/energy.db
 production · consommation · meteo · ingestion_log
      ▲
      │ scripts d'ingestion
 ingest_rte.py (API ODRÉ éCO2mix) · ingest_meteo.py (API Open-Meteo, 8 villes)
```

## Points techniques

- **MCP** : chaque serveur tourne en sous-processus (transport stdio). Le client
  (`backend/agent/mcp_client.py`) convertit leurs outils en outils LangChain.
  Ajouter un serveur = ajouter une entrée dans `MCP_SERVERS`.
- **Sécurité SQL** : base ouverte en lecture seule, une seule requête `SELECT`/`WITH`
  autorisée, résultats plafonnés à 200 lignes.
- **Garde-fous pour LLM local** : schéma injecté dans le prompt, conversion des appels
  d'outils écrits en texte, message explicite quand une période n'est pas couverte
  (pour empêcher le modèle d'inventer un chiffre), fourchettes de plausibilité.
- **Croisement énergie / météo** : chaque table est agrégée par jour dans une CTE,
  puis les CTE sont jointes (les pas de temps diffèrent : 15 min pour RTE, 1 h pour la météo).
- **Évaluation automatique** (`backend/tests/eval_agent.py`) : les réponses attendues
  sont recalculées en SQL à chaque lancement, puis comparées à celles de l'agent.

## Installation (Windows / PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
ollama pull qwen2.5:14b
```

## Utilisation (depuis la racine du projet)

```powershell
# 1. Ingestion des données
python -m backend.scripts.ingest_rte
python -m backend.scripts.ingest_meteo

# 2. Chat en ligne de commande
python -m backend.scripts.chat_cli

# 3. API (documentation sur http://127.0.0.1:8000/docs)
uvicorn backend.main:app --reload

# 4. Évaluation automatique
python -m backend.tests.eval_agent
```

## Stack

Python · FastAPI · LangGraph · LangChain · MCP (SDK Python) · SQLite / SQLAlchemy ·
Ollama (Qwen 2.5) · httpx · API RTE éCO2mix (ODRÉ) · API Open-Meteo
