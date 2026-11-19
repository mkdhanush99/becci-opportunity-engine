"""Command-line interface (CLI) for BECCI Opportunity Intelligence Engine."""
from __future__ import annotations

import argparse
import sys
from app.db import Base, get_engine, session_scope
from app.enums import LifecycleStatus
from app.models import Opportunity, ScanRun, Source
from app.orchestrator.service import Orchestrator
from app.pipeline.lifecycle import transition_lifecycle
from app.security.auth import seed_admin_user
from app.seeds.sources import seed_sources


def init_db():
    print("[*] Initialising database tables...")
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        n_sources = seed_sources(session)
        seed_admin_user(session)
        print(f"[+] Initialised successfully. Seeded {n_sources} sources and default admin user.")


def list_sources():
    with session_scope() as session:
        sources = session.query(Source).all()
        print(f"\n{'ID':<24} {'NAME':<36} {'RELIABILITY':<22} {'STATUS':<12}")
        print("-" * 96)
        for s in sources:
            print(f"{s.id:<24} {s.name[:34]:<36} {s.reliability:<22} {s.support_status:<12}")
        print()


def run_scan(source_id: str, fixture: bool = False):
    print(f"[*] Starting scan for source: {source_id} (fixture={fixture})...")
    with session_scope() as session:
        orchestrator = Orchestrator(session)
        scan = orchestrator.run_source_scan(source_id, trigger="cli", is_fixture=fixture)
        print(f"\n[+] Scan finished: {scan.status}")
        print(f"    Duration: {scan.duration_seconds}s")
        print(f"    Items seen: {scan.items_seen}")
        print(f"    Items new: {scan.items_new}")
        print(f"    Items updated: {scan.items_updated}")
        print(f"    Items unchanged: {scan.items_unchanged}")
        print(f"    Duplicates detected: {scan.duplicates_detected}")
        print(f"    Items skipped: {scan.items_skipped}")
        if scan.error:
            print(f"    Error: {scan.error}")


def list_opportunities(limit: int = 25):
    with session_scope() as session:
        opps = session.query(Opportunity).order_by(Opportunity.extracted_at.desc()).limit(limit).all()
        print(f"\n{'ID':<18} {'CATEGORY':<10} {'STATUS':<20} {'DEADLINE':<12} {'TITLE':<40}")
        print("-" * 105)
        for o in opps:
            dl = str(o.deadline) if o.deadline else "None"
            print(f"{o.id[:16]:<18} {o.category:<10} {o.lifecycle_status:<20} {dl:<12} {o.title[:38]:<40}")
        print()


def review_opportunity(opp_id: str, action: str, reason: str = "CLI Review"):
    with session_scope() as session:
        opp = session.get(Opportunity, opp_id)
        if not opp:
            # Prefix lookup
            opp = session.query(Opportunity).filter(Opportunity.id.like(f"{opp_id}%")).first()
        if not opp:
            print(f"[-] Opportunity '{opp_id}' not found.")
            return
        target = {
            "approve": LifecycleStatus.APPROVED,
            "publish": LifecycleStatus.PUBLISHED,
            "reject": LifecycleStatus.REJECTED,
        }.get(action)
        if not target:
            print(f"[-] Invalid action '{action}'. Choose approve, publish, or reject.")
            return
        transition_lifecycle(session, opp, target, actor="cli_admin", reason=reason, force=True)
        session.commit()
        print(f"[+] Opportunity '{opp_id}' successfully transitioned to {target}.")


def main():
    parser = argparse.ArgumentParser(description="BECCI Opportunity Intelligence Engine CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init-db", help="Create DB tables and seed sources")
    subparsers.add_parser("list-sources", help="List registered sources")

    scan_p = subparsers.add_parser("scan", help="Run scan on a source")
    scan_p.add_argument("--source", required=True, help="Source ID to scan")
    scan_p.add_argument("--fixture", action="store_true", help="Mark as fixture scan")

    subparsers.add_parser("list-opportunities", help="List discovered opportunities")

    rev_p = subparsers.add_parser("review", help="Review an opportunity")
    rev_p.add_argument("--opp", required=True, help="Opportunity ID")
    rev_p.add_argument("--action", required=True, choices=["approve", "publish", "reject"])
    rev_p.add_argument("--reason", default="CLI review")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
    elif args.command == "list-sources":
        list_sources()
    elif args.command == "scan":
        run_scan(args.source, fixture=args.fixture)
    elif args.command == "list-opportunities":
        list_opportunities()
    elif args.command == "review":
        review_opportunity(args.opp, args.action, args.reason)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
