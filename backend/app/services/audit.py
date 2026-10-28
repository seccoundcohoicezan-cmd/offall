"""Audit trail: every state change made by the agent, a user or an admin."""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

log = logging.getLogger("audit")


def record(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    actor: str,
    action: str,
    target: str = "",
    **detail: Any,
) -> None:
    """Adds the row to the caller's transaction; commit happens with the change itself."""
    session.add(AuditLog(user_id=user_id, actor=actor, action=action, target=target[:120], detail=detail))
    log.info(action, extra={"user_id": str(user_id) if user_id else None, "event": f"{actor}:{action}"})
