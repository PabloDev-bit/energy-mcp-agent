"""
Serveur MCP "sql-query-server".

Expose la base energy.db à un agent IA via deux outils :
  - get_schema : décrit les tables et colonnes disponibles
  - run_query  : exécute une requête SQL en LECTURE SEULE

Lancement (depuis la racine du projet) :
    python -m backend.mcp_servers.sql_query_server.server
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from mcp.server import MCPServer

# Chemin absolu vers la base, indépendant du dossier depuis lequel on lance le serveur
DB_PATH = Path(__file__).resolve().parents[3] / "data" / "energy.db"

MAX_ROWS = 200  # plafond de lignes renvoyées au LLM (évite de saturer son contexte)

SCHEMA_REMINDER = (
    "Rappel : tables production(timestamp, filiere, puissance_mw, region), "
    "consommation(timestamp, consommation_mw, region), "
    "meteo(timestamp, ville, temperature_c, vitesse_vent_kmh, nebulosite_pct). "
    "Filières : nucleaire, solaire, eolien, hydraulique, gaz, charbon, fioul, "
    "bioenergies. Syntaxe SQLite uniquement."
)

mcp = MCPServer("sql-query-server")


def _connect_readonly() -> sqlite3.Connection:
    """Ouvre la base en mode lecture seule : toute écriture échouera côté SQLite."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}. Lance d'abord l'ingestion RTE.")
    return sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)


def _clean_sql(sql: str) -> str:
    """Certains modèles écrivent "\\n" en toutes lettres au lieu d'un vrai saut de ligne."""
    return sql.replace("\\n", " ").replace("\\t", " ").strip()


def _is_safe_select(sql: str) -> bool:
    """Accepte une seule requête qui commence par SELECT ou WITH."""
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:  # plusieurs instructions enchaînées
        return False
    return re.match(r"^(select|with)\b", cleaned, re.IGNORECASE) is not None


@mcp.tool()
def get_schema() -> str:
    """
    Décrit les tables de la base énergie (production, consommation, meteo,
    ingestion_log) avec leurs colonnes et types, ainsi que la plage de dates
    couverte. À appeler AVANT d'écrire une requête SQL.
    """
    with _connect_readonly() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]

        lines: list[str] = []
        for table in tables:
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            col_desc = ", ".join(f"{c[1]} ({c[2]})" for c in cols)
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            lines.append(f"- {table} [{count} lignes] : {col_desc}")

        date_range = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM consommation"
        ).fetchone()

    return (
        "Base SQLite des données électriques françaises (source RTE éCO2mix).\n"
        "Horodatages stockés en UTC, pas de 15 minutes. Puissances en MW.\n"
        "Valeurs de production.filiere : nucleaire, solaire, eolien, hydraulique, "
        "gaz, charbon, fioul, bioenergies.\n"
        f"Période couverte : {date_range[0]} -> {date_range[1]}\n\n"
        "Tables :\n" + "\n".join(lines)
    )


@mcp.tool()
def run_query(sql: str) -> str:
    """
    Exécute une requête SQL SELECT (ou WITH ... SELECT) sur la base énergie et
    renvoie le résultat sous forme de tableau texte. Les écritures sont interdites.
    Le résultat est limité à 200 lignes : utilise GROUP BY, AVG, SUM ou LIMIT
    pour agréger plutôt que de récupérer des données brutes.
    """
    sql = _clean_sql(sql)

    if not _is_safe_select(sql):
        return "Erreur : seule une requête unique SELECT ou WITH est autorisée."

    try:
        with _connect_readonly() as conn:
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description or []]
            rows = cursor.fetchmany(MAX_ROWS + 1)
    except sqlite3.Error as exc:
        # On renvoie l'erreur au LLM, avec un rappel du schéma pour qu'il se corrige
        return f"Erreur SQL : {exc}\n{SCHEMA_REMINDER}"

    if not rows:
        return "Aucun résultat."

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    header = " | ".join(columns)
    body = "\n".join(" | ".join(str(v) for v in row) for row in rows)
    note = f"\n(Résultat tronqué à {MAX_ROWS} lignes)" if truncated else ""

    return f"{header}\n{body}{note}"


if __name__ == "__main__":
    mcp.run(transport="stdio")