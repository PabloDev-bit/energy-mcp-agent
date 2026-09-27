"""Modèles SQLAlchemy pour energy-mcp-agent."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Production(Base):
    __tablename__ = "production"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    filiere: Mapped[str] = mapped_column(String, nullable=False, index=True)
    puissance_mw: Mapped[float] = mapped_column(Float, nullable=False)
    region: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "filiere IN ('nucleaire', 'solaire', 'eolien', 'hydraulique', "
            "'gaz', 'charbon', 'fioul', 'bioenergies')",
            name="ck_production_filiere",
        ),
    )


class Consommation(Base):
    __tablename__ = "consommation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    consommation_mw: Mapped[float] = mapped_column(Float, nullable=False)
    region: Mapped[str | None] = mapped_column(String, nullable=True)


class Meteo(Base):
    __tablename__ = "meteo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ville: Mapped[str] = mapped_column(String, nullable=False, index=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    vitesse_vent_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    nebulosite_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class IngestionLog(Base):
    __tablename__ = "ingestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "source IN ('rte', 'open-meteo')", name="ck_ingestion_log_source"
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_ingestion_log_status",
        ),
    )