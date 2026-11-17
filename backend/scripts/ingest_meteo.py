"""
Ingestion des données météo Open-Meteo dans la base SQLite locale.

La période récupérée est alignée sur celle des données RTE déjà en base,
pour pouvoir croiser énergie et météo heure par heure.

Lancement (depuis la racine du projet) :
    python -m backend.scripts.ingest_meteo
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func

from backend.db.models import Consommation, IngestionLog, Meteo
from backend.db.session import SessionLocal, init_db
from backend.mcp_servers.rte_data_server.meteo_client import VILLES, fetch_history


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def rte_period(session) -> tuple[date, date]:
    """Première et dernière date des données RTE en base."""
    start, end = session.query(
        func.min(Consommation.timestamp), func.max(Consommation.timestamp)
    ).one()
    if start is None:
        raise RuntimeError("Aucune donnée RTE en base : lance d'abord ingest_rte.")
    return start.date(), end.date()


def ingest() -> None:
    init_db()
    session = SessionLocal()

    log = IngestionLog(source="open-meteo", started_at=utc_now(), status="running")
    session.add(log)
    session.commit()

    rows_inserted = 0
    skipped = 0

    try:
        start, end = rte_period(session)
        print(f"Période RTE en base : {start} -> {end}")

        # Couples (horodatage, ville) déjà en base, pour éviter les doublons
        existing = {(ts, ville) for ts, ville in session.query(Meteo.timestamp, Meteo.ville)}

        for ville in VILLES:
            rows = fetch_history(ville, start, end)
            added = 0
            for row in rows:
                key = (row["timestamp"], row["ville"])
                if key in existing:
                    skipped += 1
                    continue
                # Open-Meteo renvoie parfois null sur les toutes dernières heures
                if row["temperature_c"] is None:
                    continue
                session.add(Meteo(**row))
                existing.add(key)
                added += 1
            rows_inserted += added
            print(f"  {ville:<11} {added} relevés horaires ajoutés")

        log.status = "success"
        log.finished_at = utc_now()
        log.rows_inserted = rows_inserted
        session.commit()
        print(f"Ingestion météo terminée : {rows_inserted} lignes insérées, {skipped} déjà en base.")

    except Exception as exc:
        session.rollback()
        log.status = "failed"
        log.finished_at = utc_now()
        log.error_message = str(exc)
        session.add(log)
        session.commit()
        print(f"Échec de l'ingestion météo : {exc}")
        raise

    finally:
        session.close()


if __name__ == "__main__":
    ingest()
