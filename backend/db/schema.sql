-- schema.sql — DDL de référence pour energy-mcp-agent

CREATE TABLE IF NOT EXISTS production (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    filiere TEXT NOT NULL CHECK (filiere IN (
        'nucleaire', 'solaire', 'eolien', 'hydraulique',
        'gaz', 'charbon', 'fioul', 'bioenergies'
    )),
    puissance_mw REAL NOT NULL,
    region TEXT
);

CREATE INDEX IF NOT EXISTS idx_production_timestamp ON production(timestamp);
CREATE INDEX IF NOT EXISTS idx_production_filiere ON production(filiere);

CREATE TABLE IF NOT EXISTS consommation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    consommation_mw REAL NOT NULL,
    region TEXT
);

CREATE INDEX IF NOT EXISTS idx_consommation_timestamp ON consommation(timestamp);

CREATE TABLE IF NOT EXISTS meteo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    ville TEXT NOT NULL,
    temperature_c REAL,
    vitesse_vent_kmh REAL,
    nebulosite_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_meteo_timestamp ON meteo(timestamp);
CREATE INDEX IF NOT EXISTS idx_meteo_ville ON meteo(ville);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('rte', 'open-meteo')),
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows_inserted INTEGER DEFAULT 0,
    error_message TEXT
);