"""
Client Open-Meteo (gratuit, sans clé API).

- fetch_history  : historique horaire (API "archive") pour une ville et une période
- fetch_forecast : prévisions horaires des prochains jours (API "forecast")

Doc : https://open-meteo.com/en/docs
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_FIELDS = "temperature_2m,wind_speed_10m,cloud_cover"

# Grandes villes réparties sur le territoire : leur moyenne donne une
# approximation de la météo "nationale", à croiser avec les données RTE nationales.
VILLES: dict[str, tuple[float, float]] = {
    "Paris": (48.8566, 2.3522),
    "Lyon": (45.7640, 4.8357),
    "Marseille": (43.2965, 5.3698),
    "Lille": (50.6292, 3.0573),
    "Bordeaux": (44.8378, -0.5792),
    "Toulouse": (43.6047, 1.4442),
    "Nantes": (47.2184, -1.5536),
    "Strasbourg": (48.5734, 7.7521),
}


def _parse_hourly(payload: dict, ville: str) -> list[dict]:
    """Transforme la réponse JSON d'Open-Meteo en une liste de relevés horaires."""
    hourly = payload.get("hourly", {})
    rows: list[dict] = []
    for i, ts in enumerate(hourly.get("time", [])):
        rows.append(
            {
                "timestamp": datetime.fromisoformat(ts),  # UTC (timezone=UTC demandé)
                "ville": ville,
                "temperature_c": hourly["temperature_2m"][i],
                "vitesse_vent_kmh": hourly["wind_speed_10m"][i],
                "nebulosite_pct": hourly["cloud_cover"][i],
            }
        )
    return rows


def _coords(ville: str) -> tuple[str, float, float]:
    for name, (lat, lon) in VILLES.items():
        if name.lower() == ville.strip().lower():
            return name, lat, lon
    raise ValueError(f"Ville inconnue : {ville}. Villes disponibles : {', '.join(VILLES)}")


def fetch_history(ville: str, start: date, end: date) -> list[dict]:
    """Relevés horaires observés entre start et end inclus, en UTC."""
    name, lat, lon = _coords(ville)
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": HOURLY_FIELDS,
        "timezone": "UTC",
    }
    response = httpx.get(ARCHIVE_URL, params=params, timeout=60.0)
    response.raise_for_status()
    return _parse_hourly(response.json(), name)


def fetch_forecast(ville: str, days: int = 3) -> list[dict]:
    """
    Prévisions horaires à partir d'aujourd'hui, sur `days` jours, en HEURE
    FRANÇAISE (Europe/Paris) : c'est ce qu'attend l'utilisateur pour "demain".
    """
    name, lat, lon = _coords(ville)
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY_FIELDS,
        "forecast_days": max(1, min(days, 7)),
        "timezone": "Europe/Paris",
    }
    response = httpx.get(FORECAST_URL, params=params, timeout=30.0)
    response.raise_for_status()
    return _parse_hourly(response.json(), name)
