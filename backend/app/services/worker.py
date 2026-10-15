"""One background thread that runs the analysis pipeline for queued complaints.
One at a time: the 4 GB GPU serves one Gemma request at a time anyway."""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid

from ..db import SessionLocal
from .. import models
from .pipeline import _set_status, run_analysis

log = logging.getLogger("synapse.worker")
_q: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None


def enqueue(complaint_id) -> None:
    _q.put(str(complaint_id))


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
                _q.task_done()


def start() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="synapse-worker", daemon=True)
        _thread.start()
