"""Lifecycle Engine: strictly controls state transitions for opportunities."""
from __future__ import annotations

from sqlalchemy.orm import Session
from app.enums import LifecycleStatus
from app.models import AuditLog, Opportunity, OpportunityVersion, utcnow


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    LifecycleStatus.DISCOVERED: {
        LifecycleStatus.EXTRACTED,
        LifecycleStatus.AWAITING_VERIFICATION,
        LifecycleStatus.REJECTED,
    },
    LifecycleStatus.EXTRACTED: {
        LifecycleStatus.AWAITING_VERIFICATION,
        LifecycleStatus.NEEDS_HUMAN_REVIEW,
        LifecycleStatus.REJECTED,
    },
    LifecycleStatus.AWAITING_VERIFICATION: {
        LifecycleStatus.NEEDS_HUMAN_REVIEW,
        LifecycleStatus.APPROVED,
        LifecycleStatus.EXPIRED,
        LifecycleStatus.REJECTED,
    },
    LifecycleStatus.NEEDS_HUMAN_REVIEW: {
        LifecycleStatus.APPROVED,
        LifecycleStatus.REJECTED,
        LifecycleStatus.EXPIRED,
    },
    LifecycleStatus.APPROVED: {
        LifecycleStatus.PUBLISHED,
        LifecycleStatus.REJECTED,
        LifecycleStatus.EXPIRED,
    },
    LifecycleStatus.PUBLISHED: {
        LifecycleStatus.UPDATED,
        LifecycleStatus.CLOSING_SOON,
        LifecycleStatus.EXPIRED,
        LifecycleStatus.WITHDRAWN,
    },
    LifecycleStatus.UPDATED: {
        LifecycleStatus.PUBLISHED,
        LifecycleStatus.CLOSING_SOON,
        LifecycleStatus.EXPIRED,
        LifecycleStatus.WITHDRAWN,
    },
    LifecycleStatus.CLOSING_SOON: {
        LifecycleStatus.EXPIRED,
        LifecycleStatus.WITHDRAWN,
        LifecycleStatus.PUBLISHED,
    },
    LifecycleStatus.EXPIRED: {
        LifecycleStatus.NEEDS_HUMAN_REVIEW,  # If re-opened or deadline extended
    },
    LifecycleStatus.WITHDRAWN: {
        LifecycleStatus.NEEDS_HUMAN_REVIEW,
    },
    LifecycleStatus.REJECTED: set(),
}


class InvalidTransitionError(Exception):
    pass


def transition_lifecycle(
    session: Session,
    opp: Opportunity,
    new_status: str,
    actor: str,
    reason: str = "",
    force: bool = False
) -> Opportunity:
    """Enforces state transition rules, records audit log and version history."""
    current = opp.lifecycle_status
    if not force and new_status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(
            f"Cannot transition opportunity {opp.id} from '{current}' to '{new_status}'"
        )

    now = utcnow()
    opp.lifecycle_status = new_status
    opp.last_updated_at = now

    # Audit log
    audit = AuditLog(
        actor=actor,
        action="transition_status",
        target_type="opportunity",
        target_id=opp.id,
        detail={"old_status": current, "new_status": new_status, "reason": reason},
        created_at=now,
    )
    session.add(audit)

    # Opportunity version record
    new_v = len(opp.versions) + 1
    v = OpportunityVersion(
        opportunity_id=opp.id,
        version=new_v,
        snapshot={
            "title": opp.title,
            "deadline": opp.deadline.isoformat() if opp.deadline else None,
            "lifecycle_status": new_status,
        },
        changed_fields=["lifecycle_status"],
        significant=True,
        reason=reason or f"status change to {new_status}",
        actor=actor,
        created_at=now,
    )
    session.add(v)

    return opp
