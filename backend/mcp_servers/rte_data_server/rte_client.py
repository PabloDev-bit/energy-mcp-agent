"""
Client RTE éCO2mix en temps réel (API Opendatasoft ODRÉ, sans authentification).

Sert au serveur MCP de données pour donner le dernier mix électrique publié,
sans passer par la base locale.
"""

from __future__ import annotations

import httpx

API_URL = (
    "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "eco2mix-national-tr/records"
)

FILIERES = [
    "nucleaire", "eolien", "solaire", "hydraulique",
    "gaz", "charbon", "fioul", "bioenergies",
]


def fetch_latest_mix() -> dict:
    """Dernier relevé publié (mesures réelles, pas les prévisions)."""
    params = {
        "limit": 1,
        "order_by": "date_heure desc",
        "where": "consommation is not null",
    }
    response = httpx.get(API_URL, params=params, timeout=30.0)
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        raise RuntimeError("Aucun relevé RTE disponible pour le moment.")

    rec = results[0]
    production = {f: rec.get(f) for f in FILIERES if rec.get(f) is not None}
    return {
        "date_heure": rec.get("date_heure"),
        "consommation_mw": rec.get("consommation"),
        "production_mw": production,
        "production_totale_mw": sum(production.values()),
    }
