"""FastAPI application entrypoint for BECCI Opportunity Intelligence Engine."""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.crawler import router as crawler_router
from app.api.member import router as member_router
from app.api.public import router as public_router
from app.api.webhooks import router as webhooks_router
from app.config import get_settings
from app.db import Base, get_engine, session_scope
from app.matching.engine import get_or_create_matching_config
from app.migrations import run_migrations
from app.orchestrator.scheduler import start_scheduler, stop_scheduler
from app.security.auth import seed_admin_user
from app.seeds.schemes import seed_verified_schemes
from app.seeds.sources import seed_sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables & run explicit migrations
    engine = get_engine()
    run_migrations(engine)

    # Seed default sources, verified schemes, matching config, and initial admin user
    with session_scope() as session:
        seed_sources(session)
        seed_verified_schemes(session)
        seed_admin_user(session, username="admin", password="BecciAdmin2026!")
        get_or_create_matching_config(session)

    # Start 24/7 autonomous background scheduler
    start_scheduler()

    try:
        yield
    finally:
        stop_scheduler()




settings = get_settings()

app = FastAPI(
    title="BECCI Opportunity Intelligence Engine",
    description=(
        "Autonomous Browser-Based Research Agents, Opportunity Discovery & Personalised Matching Platform for "
        "Bahujan Entrepreneurs Chamber for Commerce & Industry (BECCI)."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from pathlib import Path
from fastapi.responses import FileResponse

# Mount routes
app.include_router(public_router)
app.include_router(crawler_router)
app.include_router(member_router)
app.include_router(admin_router)
app.include_router(webhooks_router)

# Mount Web Portal Preview UI
STATIC_INDEX = Path(__file__).parent / "static" / "index.html"

@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_preview_portal():
    return FileResponse(STATIC_INDEX)

@app.api_route("/admin", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_admin_portal():
    return FileResponse(STATIC_INDEX)
