"""Explicit, reversible database migration manager maintaining SQLite WAL compatibility."""
from __future__ import annotations

import datetime as dt
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db import Base, get_engine

MIGRATIONS: list[dict] = [
    {
        "version": "001_phase1_baseline",
        "description": "Phase 1 baseline opportunity, source, evidence, and verification tables",
        "up_sql": [],  # Managed via Base.metadata.create_all for baseline
        "down_sql": [],
    },
    {
        "version": "002_phase2_tender_details",
        "description": "Create tender_details 1-to-1 extension table and indexes for Phase 2 Tender Scout",
        "up_sql": [
            """
            CREATE TABLE IF NOT EXISTS tender_details (
                opportunity_id VARCHAR(32) NOT NULL PRIMARY KEY,
                tender_id VARCHAR(128),
                reference_number VARCHAR(128),
                issuing_authority VARCHAR(255) NOT NULL,
                department VARCHAR(255) NOT NULL DEFAULT 'Not stated',
                tender_category VARCHAR(64) NOT NULL DEFAULT 'Not stated',
                product_category VARCHAR(255) NOT NULL DEFAULT 'Not stated',
                sector VARCHAR(64) NOT NULL DEFAULT 'Other industries',
                estimated_value VARCHAR(128) NOT NULL DEFAULT 'Not published',
                emd_amount VARCHAR(128) NOT NULL DEFAULT 'Not published',
                tender_fee VARCHAR(128) NOT NULL DEFAULT 'Not published',
                document_download_date DATE,
                pre_bid_date DATE,
                pre_bid_details TEXT NOT NULL DEFAULT 'Not published',
                bid_opening_date DATE,
                turnover_requirement VARCHAR(255) NOT NULL DEFAULT 'Not stated',
                experience_requirement TEXT NOT NULL DEFAULT 'Not stated',
                required_registrations JSON NOT NULL DEFAULT '[]',
                msme_preference TEXT NOT NULL DEFAULT 'Not stated',
                eligibility_intelligence JSON NOT NULL DEFAULT '{}',
                tender_status VARCHAR(32) NOT NULL DEFAULT 'open',
                corrigendum_history JSON NOT NULL DEFAULT '[]',
                cancellation_reason TEXT,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_tender_details_tender_id ON tender_details (tender_id)",
            "CREATE INDEX IF NOT EXISTS ix_tender_details_reference_number ON tender_details (reference_number)",
            "CREATE INDEX IF NOT EXISTS ix_tender_details_sector ON tender_details (sector)",
            "CREATE INDEX IF NOT EXISTS ix_tender_details_tender_status ON tender_details (tender_status)",
        ],
        "down_sql": [
            "DROP INDEX IF EXISTS ix_tender_details_tender_status",
            "DROP INDEX IF EXISTS ix_tender_details_sector",
            "DROP INDEX IF EXISTS ix_tender_details_reference_number",
            "DROP INDEX IF EXISTS ix_tender_details_tender_id",
            "DROP TABLE IF EXISTS tender_details",
        ],
    },
]


def ensure_migrations_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(64) PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at VARCHAR(64) NOT NULL
                )
                """
            )
        )


def list_applied_migrations(engine: Engine | None = None) -> list[dict]:
    eng = engine or get_engine()
    ensure_migrations_table(eng)
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT version, description, applied_at FROM schema_migrations ORDER BY version ASC")
        ).fetchall()
    return [{"version": r[0], "description": r[1], "applied_at": r[2]} for r in rows]


def run_migrations(engine: Engine | None = None) -> list[str]:
    """Applies any pending migrations idempotently, preserving existing rows."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
    ensure_migrations_table(eng)
    applied = {m["version"] for m in list_applied_migrations(eng)}
    newly_applied: list[str] = []
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    with eng.begin() as conn:
        for mig in MIGRATIONS:
            v = mig["version"]
            if v in applied:
                continue
            for stmt in mig["up_sql"]:
                conn.execute(text(stmt))
            conn.execute(
                text("INSERT INTO schema_migrations (version, description, applied_at) VALUES (:v, :d, :a)"),
                {"v": v, "d": mig["description"], "a": now_iso},
            )
            newly_applied.append(v)
    return newly_applied


def rollback_migration(version: str, engine: Engine | None = None) -> bool:
    """Reverses a specific migration version if applied."""
    eng = engine or get_engine()
    ensure_migrations_table(eng)
    applied = {m["version"] for m in list_applied_migrations(eng)}
    if version not in applied:
        return False
    target = next((m for m in MIGRATIONS if m["version"] == version), None)
    if not target:
        raise ValueError(f"Unknown migration version: {version}")

    with eng.begin() as conn:
        for stmt in target["down_sql"]:
            conn.execute(text(stmt))
        conn.execute(text("DELETE FROM schema_migrations WHERE version = :v"), {"v": version})
    return True
