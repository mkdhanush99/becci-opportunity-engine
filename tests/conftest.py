"""Pytest configuration: isolates test execution to an independent test database."""
import os
from pathlib import Path
import pytest
from app.db import Base, init_engine, session_scope
from app.migrations import run_migrations
from app.security.auth import seed_admin_user
from app.seeds.schemes import seed_verified_schemes
from app.seeds.sources import seed_sources

TEST_DB_PATH = Path("./data/test_becci.db")


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    engine = init_engine(f"sqlite:///{TEST_DB_PATH}")
    run_migrations(engine)
    with session_scope() as session:
        seed_sources(session)
        seed_verified_schemes(session)
        seed_admin_user(session, username="admin", password="BecciAdmin2026!")
    yield
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

