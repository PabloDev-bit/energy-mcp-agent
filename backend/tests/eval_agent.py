"""
Évaluation automatique de l'agent énergie.

Pour chaque cas de test :
  1. calcule la bonne réponse avec une requête SQL de référence (vérifiée à la main) ;
  2. pose la question à l'agent dans une conversation vierge ;
  3. vérifie que la réponse de l'agent contient la bonne valeur.

Les réponses attendues sont recalculées à chaque lancement : les tests restent
valables après une nouvelle ingestion RTE.

Lancement (depuis la racine du projet, Ollama démarré) :
    python -m backend.tests.eval_agent
    python -m backend.tests.eval_agent --only eolien_juillet_aout
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import time
import logging
from dataclasses import dataclass, field
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from backend.agent.graph import MODEL_NAME, build_graph
from backend.agent.mcp_client import load_mcp_tools
from backend.mcp_servers.sql_query_server.server import DB_PATH


# ---------------------------------------------------------------------------
# Définition des cas de test
# ---------------------------------------------------------------------------

@dataclass
class EvalCase:
    id: str
    question: str
    kind: str  # "numbers" | "contains_any" | "refusal"
    reference_sql: str | None = None
    # Transforme les lignes SQL en valeurs attendues (nombres ou textes)
    transform: Callable[[list[tuple]], list] = lambda rows: []
    tolerance: float = 0.02  # tolérance relative pour les nombres (2 %)
    keywords: list[str] = field(default_factory=list)  # pour kind="refusal"


def _day_labels(rows: list[tuple]) -> list[str]:
    day = int(rows[0][0])
    return [f"{day} septembre", f"2026-09-{day:02d}", f"{day:02d}/09"]


def _local_hour_labels(rows: list[tuple]) -> list[str]:
    hour = (int(rows[0][0]) + 2) % 24  # UTC -> heure d'été française
    return [f"{hour} h", f"{hour}h", f"{hour} heure", f"{hour}:00"]


CASES: list[EvalCase] = [
    EvalCase(
        id="part_nucleaire",
        question="Quelle est la part moyenne du nucléaire dans la production totale ?",
        kind="numbers",
        reference_sql=(
            "SELECT 100.0 * SUM(CASE WHEN filiere = 'nucleaire' THEN puissance_mw ELSE 0 END)"
            " / SUM(puissance_mw) FROM production"
        ),
        transform=lambda rows: [rows[0][0]],
    ),
    EvalCase(
        id="jour_solaire_max_sept",
        question="Quel jour de septembre a eu le plus de production solaire ?",
        kind="contains_any",
        reference_sql=(
            "SELECT strftime('%d', timestamp) FROM production"
            " WHERE filiere = 'solaire' AND timestamp >= '2026-09-01' AND timestamp < '2026-10-01'"
            " GROUP BY strftime('%Y-%m-%d', timestamp) ORDER BY SUM(puissance_mw) DESC LIMIT 1"
        ),
        transform=_day_labels,
    ),
    EvalCase(
        id="heure_pic_conso",
        question=(
            "À quelle heure de la journée, en heure française, la consommation "
            "est-elle la plus forte en moyenne ?"
        ),
        kind="contains_any",
        reference_sql=(
            "SELECT CAST(strftime('%H', timestamp) AS INTEGER) FROM consommation"
            " GROUP BY 1 ORDER BY AVG(consommation_mw) DESC LIMIT 1"
        ),
        transform=_local_hour_labels,
    ),
    EvalCase(
        id="eolien_juillet_aout",
        question="Compare la production éolienne moyenne de juillet et d'août.",
        kind="numbers",
        reference_sql=(
            "SELECT AVG(puissance_mw) FROM production"
            " WHERE filiere = 'eolien' AND timestamp >= '2026-07-01' AND timestamp < '2026-09-01'"
            " GROUP BY strftime('%Y-%m', timestamp) ORDER BY strftime('%Y-%m', timestamp)"
        ),
        transform=lambda rows: [r[0] for r in rows],
    ),
    EvalCase(
        id="solaire_total_aout_gwh",
        question="Combien d'énergie solaire a été produite au total en août, en GWh ?",
        kind="numbers",
        reference_sql=(
            "SELECT SUM(puissance_mw) * 0.25 / 1000 FROM production"
            " WHERE filiere = 'solaire' AND timestamp >= '2026-08-01' AND timestamp < '2026-09-01'"
        ),
        transform=lambda rows: [rows[0][0]],
        tolerance=0.01,  # oublier le 31 août donne ~3 % d'écart : doit échouer
    ),
    EvalCase(
        id="conso_moyenne_septembre",
        question="Quelle a été la consommation électrique moyenne en septembre ?",
        kind="numbers",
        reference_sql=(
            "SELECT AVG(consommation_mw) FROM consommation"
            " WHERE timestamp >= '2026-09-01' AND timestamp < '2026-10-01'"
        ),
        transform=lambda rows: [rows[0][0]],
    ),
    EvalCase(
        id="part_renouvelables",
        question=(
            "Quelle est la part des énergies renouvelables (solaire, éolien, "
            "hydraulique, bioénergies) dans la production totale ?"
        ),
        kind="numbers",
        reference_sql=(
            "SELECT 100.0 * SUM(CASE WHEN filiere IN ('solaire', 'eolien', 'hydraulique', 'bioenergies')"
            " THEN puissance_mw ELSE 0 END) / SUM(puissance_mw) FROM production"
        ),
        transform=lambda rows: [rows[0][0]],
    ),
    EvalCase(
        id="hors_periode",
        question="Quelle était la production nucléaire moyenne en janvier 2026 ?",
        kind="refusal",
        keywords=[
            "pas de donnée", "aucune donnée", "ne couvre", "ne contient pas",
            "pas disponible", "hors de la période", "en dehors", "aucun résultat",
            "couvre uniquement", "ne dispose pas", "pas couvert", "n'est pas couverte",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Vérification des réponses
# ---------------------------------------------------------------------------

# Nombres au format français ou anglais : "157 553", "4 034,66", "68.9"
NUMBER_RE = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def extract_numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in NUMBER_RE.findall(text):
        cleaned = re.sub(r"[ \u00a0\u202f]", "", match).replace(",", ".")
        try:
            values.append(float(cleaned))
        except ValueError:
            pass
    return values


def number_found(expected: float, found: list[float], tolerance: float) -> bool:
    """Accepte la valeur à la tolérance près, y compris convertie MWh <-> GWh."""
    for value in found:
        for scale in (1, 1000, 0.001):
            if abs(value * scale - expected) <= tolerance * abs(expected):
                return True
    return False


def check(case: EvalCase, answer: str, expected: list) -> bool:
    lowered = answer.lower()
    if case.kind == "numbers":
        found = extract_numbers(answer)
        return bool(expected) and all(number_found(e, found, case.tolerance) for e in expected)
    if case.kind == "contains_any":
        return any(label.lower() in lowered for label in expected)
    if case.kind == "refusal":
        return any(keyword in lowered for keyword in case.keywords)
    raise ValueError(f"Type de vérification inconnu : {case.kind}")


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------

async def run_case(app, case: EvalCase, conn: sqlite3.Connection) -> dict:
    expected = case.transform(conn.execute(case.reference_sql).fetchall()) if case.reference_sql else []

    start = time.perf_counter()
    try:
        output = await app.ainvoke(
            {"messages": [HumanMessage(case.question)]},  # conversation vierge
            config={"recursion_limit": 20},
        )
        messages = output["messages"]
        answer = str(messages[-1].content)
        tool_calls = sum(len(m.tool_calls) for m in messages if isinstance(m, AIMessage))
    except GraphRecursionError:
        answer, tool_calls = "(boucle interrompue : limite d'itérations atteinte)", -1
    except Exception as exc:  # une erreur ne doit pas arrêter toute l'évaluation
        answer, tool_calls = f"(erreur : {exc})", -1
    elapsed = time.perf_counter() - start

    return {
        "case": case,
        "expected": expected,
        "answer": answer,
        "passed": check(case, answer, expected),
        "seconds": elapsed,
        "tool_calls": tool_calls,
    }


def _format_expected(expected: list) -> str:
    return ", ".join(f"{e:,.1f}".replace(",", " ") if isinstance(e, float) else str(e) for e in expected)


async def main(only: str | None) -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cases = [c for c in CASES if only is None or c.id == only]
    if not cases:
        raise SystemExit(f"Aucun cas de test nommé {only!r}.")

    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    results: list[dict] = []

    async with load_mcp_tools() as tools:
        schema = await next(t for t in tools if t.name == "get_schema").ainvoke({})
        app = build_graph(tools, schema)

        print(f"Évaluation de {MODEL_NAME} sur {len(cases)} cas\n")
        for i, case in enumerate(cases, start=1):
            print(f"[{i}/{len(cases)}] {case.id:<26}", end="", flush=True)
            result = await run_case(app, case, conn)
            status = "OK   " if result["passed"] else "ÉCHEC"
            print(f"{status} ({result['seconds']:.1f} s, {result['tool_calls']} appel(s) d'outil)")
            results.append(result)

    conn.close()

    failures = [r for r in results if not r["passed"]]
    if failures:
        print("\n--- Détail des échecs ---")
        for r in failures:
            print(f"\n{r['case'].id}")
            print(f"  Question : {r['case'].question}")
            if r["expected"]:
                print(f"  Attendu  : {_format_expected(r['expected'])}")
            print(f"  Réponse  : {r['answer'][:400]}")

    passed = len(results) - len(failures)
    avg_time = sum(r["seconds"] for r in results) / len(results)
    print(f"\nScore : {passed}/{len(results)} ({100 * passed / len(results):.0f} %)")
    print(f"Temps moyen par question : {avg_time:.1f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Évaluation automatique de l'agent énergie")
    parser.add_argument("--only", help="ne lancer qu'un seul cas de test, par son id")
    asyncio.run(main(parser.parse_args().only))