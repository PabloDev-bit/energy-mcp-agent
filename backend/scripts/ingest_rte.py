"""
Script d'ingestion des données RTE éCO2mix (production + consommation)
dans la base SQLite locale.

Source : API Opendatasoft ODRÉ, dataset "eco2mix-national-tr"
Doc du dataset : https://odre.opendatasoft.com/explore/dataset/eco2mix-national-tr/
Pas d'authentification requise (quota : 50 000 appels/mois/utilisateur).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.db.models import Consommation, IngestionLog, Production
from backend.db.session import SessionLocal, init_db

API_URL = "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets/eco2mix-national-tr/records"

# Mapping colonne API -> nom de filière dans notre table `production`
FILIERE_FIELDS = {
    "nucleaire": "nucleaire",
    "eolien": "eolien",
    "solaire": "solaire",
    "hydraulique": "hydraulique",
    "gaz": "gaz",
    "charbon": "charbon",
    "fioul": "fioul",
    "bioenergies": "bioenergies",
}

PAGE_SIZE = 100  # max autorisé par l'API Opendatasoft


def utc_now() -> datetime:
    """Heure actuelle en UTC, sans fuseau (format de stockage SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fetch_records(limit: int = 500, where: str | None = None) -> list[dict]:
    """Récupère les enregistrements les plus récents via pagination."""
    records: list[dict] = []
    offset = 0

    with httpx.Client(timeout=30.0) as client:
        while len(records) < limit:
            params = {
                "limit": min(PAGE_SIZE, limit - len(records)),
                "offset": offset,
                "order_by": "date_heure desc",
            }
            if where:
                params["where"] = where

            response = client.get(API_URL, params=params)
            response.raise_for_status()
            batch = response.json().get("results", [])

            if not batch:
                break

            records.extend(batch)
            offset += len(batch)

            if len(batch) < params["limit"]:
                break

    return records


def ingest(limit: int = 500) -> None:
    init_db()
    session = SessionLocal()

    log = IngestionLog(source="rte", started_at=utc_now(), status="running")
    session.add(log)
    session.commit()

    rows_inserted = 0
    skipped = 0

    try:
        # Filtre les créneaux futurs (prévisions présentes mais mesures encore vides)
        records = fetch_records(limit=limit, where="consommation is not null")

        # Horodatages déjà en base, pour éviter les doublons
        existing_ts = {row[0] for row in session.query(Consommation.timestamp).all()}

        for rec in records:
            date_heure_str = rec.get("date_heure")
            if not date_heure_str:
                continue

            # Stocké en UTC naïf (SQLite gère mal les fuseaux horaires)
            ts = (
                datetime.fromisoformat(date_heure_str)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            if ts in existing_ts:
                skipped += 1
                continue

            # --- Production par filière ---
            for api_field, filiere_name in FILIERE_FIELDS.items():
                puissance = rec.get(api_field)
                if puissance is None:
                    continue
                session.add(
                    Production(
                        timestamp=ts,
                        filiere=filiere_name,
                        puissance_mw=float(puissance),
                        region=None,
                    )
                )
                rows_inserted += 1

            # --- Consommation ---
            conso = rec.get("consommation")
            if conso is not None:
                session.add(
                    Consommation(timestamp=ts, consommation_mw=float(conso), region=None)
                )
                rows_inserted += 1

            existing_ts.add(ts)

        log.status = "success"
        log.finished_at = utc_now()
        log.rows_inserted = rows_inserted
        session.commit()

        print(
            f"Ingestion terminée : {rows_inserted} lignes insérées "
            f"({len(records)} relevés RTE récupérés, {skipped} déjà en base)."
        )

    except Exception as exc:
        session.rollback()
        log.status = "failed"
        log.finished_at = utc_now()
        log.error_message = str(exc)
        session.add(log)
        session.commit()
        print(f"Échec de l'ingestion : {exc}")
        raise

    finally:
        session.close()


if __name__ == "__main__":
    ingest(limit=500)