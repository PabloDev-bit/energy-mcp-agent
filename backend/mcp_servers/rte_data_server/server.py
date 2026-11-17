"""
Serveur MCP "energy-data-server".

Donne à l'agent l'accès aux données EN DIRECT, en complément de la base locale :
  - get_live_mix         : dernier mix électrique publié par RTE (API éCO2mix)
  - get_weather_forecast : prévisions météo Open-Meteo pour une grande ville
  - get_data_coverage    : périodes couvertes par la base et dernières ingestions

Lancement (depuis la racine du projet) :
    python -m backend.mcp_servers.rte_data_server.server
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from mcp.server import MCPServer

from backend.mcp_servers.rte_data_server.meteo_client import VILLES, fetch_forecast
from backend.mcp_servers.rte_data_server.rte_client import fetch_latest_mix

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "energy.db"

mcp = MCPServer("energy-data-server")


@mcp.tool()
def get_live_mix() -> str:
    """
    Renvoie le DERNIER mix électrique français publié par RTE, en temps réel :
    consommation et production par filière, en MW, avec la part de chaque filière.
    À utiliser pour les questions sur "maintenant", "en ce moment", "aujourd'hui".
    Ne pas utiliser pour l'historique : pour ça, interroger la base avec run_query.
    """
    try:
        mix = fetch_latest_mix()
    except Exception as exc:
        return f"Erreur : impossible de joindre l'API RTE ({exc})."

    total = mix["production_totale_mw"] or 1
    lignes = [
        f"- {filiere} : {mw:.0f} MW ({100 * mw / total:.1f} %)"
        for filiere, mw in sorted(mix["production_mw"].items(), key=lambda x: -x[1])
    ]
    return (
        f"Relevé RTE du {mix['date_heure']} (heure française incluse dans la date).\n"
        f"Consommation : {mix['consommation_mw']:.0f} MW\n"
        f"Production totale : {mix['production_totale_mw']:.0f} MW\n"
        "Production par filière :\n" + "\n".join(lignes)
    )


@mcp.tool()
def get_weather_forecast(ville: str, jours: int = 3) -> str:
    """
    Renvoie les prévisions météo Open-Meteo d'une grande ville française,
    résumées par jour en heure française : température moyenne, min et max (°C),
    vent moyen (km/h) et nébulosité moyenne (%). Chaque jour est étiqueté
    (aujourd'hui, demain, ...) : réponds avec le jour demandé par l'utilisateur.
    `jours` compte à partir d'aujourd'hui inclus (1 à 7) : laisse 3 par défaut,
    "demain" nécessite au moins 2.
    Villes disponibles : Paris, Lyon, Marseille, Lille, Bordeaux, Toulouse,
    Nantes, Strasbourg.
    """
    try:
        rows = fetch_forecast(ville, max(jours, 2))
    except ValueError as exc:
        return f"Erreur : {exc}"
    except Exception as exc:
        return f"Erreur : impossible de joindre l'API Open-Meteo ({exc})."

    par_jour: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["temperature_c"] is not None:
            par_jour[row["timestamp"].date().isoformat()].append(row)

    etiquettes = ["aujourd'hui", "demain", "après-demain"]
    lignes = []
    for i, (jour, releves) in enumerate(sorted(par_jour.items())):
        etiquette = etiquettes[i] if i < len(etiquettes) else f"dans {i} jours"
        temps = [r["temperature_c"] for r in releves]
        vent = sum(r["vitesse_vent_kmh"] for r in releves) / len(releves)
        nuages = sum(r["nebulosite_pct"] for r in releves) / len(releves)
        lignes.append(
            f"- {jour} ({etiquette}) : {sum(temps) / len(temps):.1f} °C en moyenne "
            f"(min {min(temps):.1f}, max {max(temps):.1f}), "
            f"vent {vent:.0f} km/h, nébulosité {nuages:.0f} %"
        )
    ville_nom = rows[0]["ville"]
    return (
        f"Prévisions Open-Meteo pour {ville_nom} (dates en heure française) :\n"
        + "\n".join(lignes)
    )


@mcp.tool()
def get_data_coverage() -> str:
    """
    Indique les périodes couvertes par la base locale (données RTE et météo),
    le nombre de lignes par table et les dernières ingestions.
    À utiliser pour savoir si une question porte sur une période disponible.
    """
    if not DB_PATH.exists():
        return "Base introuvable : lance d'abord les scripts d'ingestion."

    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        lignes = []
        for table in ("production", "consommation", "meteo"):
            debut, fin, n = conn.execute(
                f"SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM {table}"
            ).fetchone()
            periode = f"{debut[:16]} -> {fin[:16]}" if debut else "vide"
            lignes.append(f"- {table} : {n} lignes, {periode}")

        villes = [r[0] for r in conn.execute("SELECT DISTINCT ville FROM meteo ORDER BY ville")]
        logs = conn.execute(
            "SELECT source, finished_at, status, rows_inserted FROM ingestion_log "
            "ORDER BY id DESC LIMIT 4"
        ).fetchall()

    ingestions = [f"- {s} le {(f or '?')[:16]} : {st}, {n} lignes" for s, f, st, n in logs]
    return (
        "Couverture de la base (horodatages en UTC) :\n" + "\n".join(lignes)
        + f"\nVilles météo : {', '.join(villes) or 'aucune'}"
        + "\nDernières ingestions :\n" + "\n".join(ingestions)
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
