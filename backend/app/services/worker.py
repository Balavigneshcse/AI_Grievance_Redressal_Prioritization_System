"""One background thread that runs the analysis pipeline for queued complaints.
One at a time: the 4 GB GPU serves one Gemma request at a time anyway."""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..db import SessionLocal
from .. import models
from .pipeline import _set_status, run_analysis
from .sla import check_overdue

log = logging.getLogger("synapse.worker")
_q: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None
_sla_thread: threading.Thread | None = None
SLA_INTERVAL_S = 60
STUCK_AFTER_S = 600  # a complaint still received/analysing after this long, and not queued here, is picked up again
_inflight: set[str] = set()  # queued or being analysed by this process
_inflight_lock = threading.Lock()


def enqueue(complaint_id) -> None:
    cid = str(complaint_id)
    with _inflight_lock:
        if cid in _inflight:
            return
        _inflight.add(cid)
    _q.put(cid)


def requeue_unfinished(min_age_s: int = 0) -> int:
    """Put complaints left in 'received' or 'analysing' back on the queue. The queue lives in
    memory, so a restart (or a crash mid-analysis) would otherwise leave them 'Analysing' forever,
    in nobody's queue. Run at start-up for all of them, then every minute for ones stuck longer
    than STUCK_AFTER_S. Oldest first."""
    q = select(models.Complaint.id).where(models.Complaint.status.in_(("received", "analysing"))).order_by(models.Complaint.created_at)
    if min_age_s:
        q = q.where(models.Complaint.updated_at < datetime.now(timezone.utc) - timedelta(seconds=min_age_s))
    with SessionLocal() as db:
        ids = [str(i) for i in db.execute(q).scalars().all()]
    with _inflight_lock:
        todo = [i for i in ids if i not in _inflight]
    for i in todo:
        enqueue(i)
    if todo:
        log.warning("re-queued %d unfinished complaint(s) for analysis", len(todo))
    return len(todo)


def depth() -> int:
    return _q.qsize()


def _loop() -> None:
    while True:
        cid = uuid.UUID(_q.get())
        with SessionLocal() as db:
            try:
                c = db.get(models.Complaint, cid)
                if c is None:
                    continue
                _set_status(db, c, "analysing", note="worker picked up")
                db.commit()
                t0 = time.perf_counter()
                analysis = run_analysis(db, cid)
                db.commit()
                log.info("analysed %s -> %s in %.1f s (model %.1f s, queue depth %d)", c.tracking_id, c.status,
                         time.perf_counter() - t0, (analysis.latency_ms or 0) / 1000, _q.qsize())
            except Exception as exc:
                db.rollback()
                log.exception("analysis failed for %s", cid)
                try:
                    c = db.get(models.Complaint, cid)
                    if c is not None:
                        _set_status(db, c, "under_review", note=f"analysis failed: {exc}"[:500])
                        db.add(models.Decision(complaint_id=c.id, queue="review", reasons=[f"analysis failed: {exc}"[:300]]))
                        db.commit()
                except Exception:
                    db.rollback()
            finally:
                with _inflight_lock:
                    _inflight.discard(str(cid))
                _q.task_done()


def _start_worker() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="synapse-worker", daemon=True)
        _thread.start()


def _sla_loop() -> None:
    while True:
        time.sleep(SLA_INTERVAL_S)
        try:
            n = check_overdue()
            if n:
                log.info("sla check: %d complaint(s) escalated", n)
        except Exception:
            log.exception("sla check failed")
        try:
            if _thread is None or not _thread.is_alive():
                log.error("analysis worker was not running; restarting it")
                _start_worker()
            requeue_unfinished(min_age_s=STUCK_AFTER_S)
        except Exception:
            log.exception("stuck-complaint sweep failed")


def start() -> None:
    global _sla_thread
    _start_worker()
    if _sla_thread is None or not _sla_thread.is_alive():
        _sla_thread = threading.Thread(target=_sla_loop, name="synapse-sla", daemon=True)
        _sla_thread.start()
    try:
        requeue_unfinished()  # complaints a previous run left in received / analysing
    except Exception:
        log.exception("could not re-queue unfinished complaints at start-up")
