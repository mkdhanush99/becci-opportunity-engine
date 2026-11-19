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
    {
        "version": "003_phase3_business_profiles_and_matching",
        "description": "Create private member accounts, business profiles, saved/viewed tracking, and matching config tables for Phase 3",
        "up_sql": [
            """
            CREATE TABLE IF NOT EXISTS member_accounts (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(128) NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1,
                token_version INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                last_login_at DATETIME
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_member_accounts_email ON member_accounts (email)",
            """
            CREATE TABLE IF NOT EXISTS business_profiles (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                member_id VARCHAR(32) NOT NULL UNIQUE,
                business_name VARCHAR(255) NOT NULL,
                business_type VARCHAR(48) NOT NULL,
                industry VARCHAR(128),
                becci_sector VARCHAR(64) NOT NULL,
                secondary_sectors JSON NOT NULL DEFAULT '[]',
                state VARCHAR(64) NOT NULL,
                district VARCHAR(128),
                business_stage VARCHAR(32) NOT NULL DEFAULT 'micro',
                msme_udyam_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                gst_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                entity_type VARCHAR(48) NOT NULL DEFAULT 'sole_proprietorship',
                annual_turnover_lakhs FLOAT,
                years_of_experience FLOAT,
                licences_and_registrations JSON NOT NULL DEFAULT '[]',
                capabilities JSON NOT NULL DEFAULT '[]',
                products_and_services JSON NOT NULL DEFAULT '[]',
                preferred_categories JSON NOT NULL DEFAULT '["tender", "funding", "job"]',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(member_id) REFERENCES member_accounts (id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_business_profiles_member_id ON business_profiles (member_id)",
            "CREATE INDEX IF NOT EXISTS ix_business_profiles_becci_sector ON business_profiles (becci_sector)",
            "CREATE INDEX IF NOT EXISTS ix_business_profiles_state ON business_profiles (state)",
            """
            CREATE TABLE IF NOT EXISTS saved_opportunities (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                member_id VARCHAR(32) NOT NULL,
                opportunity_id VARCHAR(32) NOT NULL,
                notes TEXT,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_saved_member_opp UNIQUE (member_id, opportunity_id),
                FOREIGN KEY(member_id) REFERENCES member_accounts (id) ON DELETE CASCADE,
                FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_saved_opportunities_member_id ON saved_opportunities (member_id)",
            """
            CREATE TABLE IF NOT EXISTS opportunity_views (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                member_id VARCHAR(32) NOT NULL,
                opportunity_id VARCHAR(32) NOT NULL,
                view_count INTEGER NOT NULL DEFAULT 1,
                first_viewed_at DATETIME NOT NULL,
                last_viewed_at DATETIME NOT NULL,
                CONSTRAINT uq_viewed_member_opp UNIQUE (member_id, opportunity_id),
                FOREIGN KEY(member_id) REFERENCES member_accounts (id) ON DELETE CASCADE,
                FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_opportunity_views_member_id ON opportunity_views (member_id)",
            """
            CREATE TABLE IF NOT EXISTS matching_configs (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                sector_weight FLOAT NOT NULL DEFAULT 30.0,
                geography_weight FLOAT NOT NULL DEFAULT 20.0,
                eligibility_weight FLOAT NOT NULL DEFAULT 25.0,
                deadline_urgency_weight FLOAT NOT NULL DEFAULT 10.0,
                category_preference_weight FLOAT NOT NULL DEFAULT 10.0,
                verification_weight FLOAT NOT NULL DEFAULT 5.0,
                min_score_threshold FLOAT NOT NULL DEFAULT 20.0,
                exclude_expired BOOLEAN NOT NULL DEFAULT 1,
                updated_by VARCHAR(64) NOT NULL DEFAULT 'system',
                updated_at DATETIME NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS match_feedback (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                business_profile_id VARCHAR(32) NOT NULL,
                opportunity_id VARCHAR(32) NOT NULL,
                flag_type VARCHAR(32) NOT NULL,
                reason TEXT NOT NULL,
                actor VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(business_profile_id) REFERENCES business_profiles (id) ON DELETE CASCADE,
                FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_match_feedback_profile_id ON match_feedback (business_profile_id)",
            "CREATE INDEX IF NOT EXISTS ix_match_feedback_flag_type ON match_feedback (flag_type)",
        ],
        "down_sql": [
            "DROP TABLE IF EXISTS match_feedback",
            "DROP TABLE IF EXISTS matching_configs",
            "DROP TABLE IF EXISTS opportunity_views",
            "DROP TABLE IF EXISTS saved_opportunities",
            "DROP TABLE IF EXISTS business_profiles",
            "DROP TABLE IF EXISTS member_accounts",
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
