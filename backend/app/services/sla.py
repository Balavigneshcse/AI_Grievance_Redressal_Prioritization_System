"""SLA watch. A complaint that passes its due time while still open is flagged once:
a timeline event is written, its district admin and department admins are emailed,
and the queue shows an 'overdue' flag. Runs every minute from the worker; the super
admin can trigger it by hand with POST /admin/sla/check."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import SessionLocal
from .. import models
from .notifier import notify_staff

log = logging.getLogger("synapse.sla")
OPEN_STATUSES = ("routed", "in_progress", "awaiting_info", "under_review")


def fmt_due(due: datetime | None) -> str:
    return due.astimezone(timezone.utc).strftime("%d %b %H:%M UTC") if due else "-"


def check_overdue() -> int:
    """Escalate every open complaint past its due time that was not escalated before."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        rows = db.execute(
            select(models.Complaint).where(
                models.Complaint.due_at < now,
                models.Complaint.escalated_at.is_(None),
                models.Complaint.status.in_(OPEN_STATUSES),
            )
        ).scalars().all()
        for c in rows:
            c.escalated_at = now
            due = fmt_due(c.due_at)
            db.add(
                models.StatusEvent(
                    complaint_id=c.id, from_status=c.status, to_status=c.status, actor_type="system",
                    note=f"SLA breached: due {due}; escalated to the district admin",
                )
            )
            dept = db.get(models.Department, c.department_id) if c.department_id else None
            kw = dict(department=dept.name_en if dept else "-", urgency=c.urgency or "-", due=due, status=c.status.replace("_", " "))
            notify_staff(db, c, "district", "overdue", **kw)
            notify_staff(db, c, "department", "overdue", **kw)
            log.warning("overdue: %s (%s, %s, due %s) escalated", c.tracking_id, c.department_id, c.urgency, due)
        db.commit()
        return len(rows)
