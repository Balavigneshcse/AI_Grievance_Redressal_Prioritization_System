"""Small in-memory rate limiter for the authentication endpoints (one API process).
Each key keeps the timestamps of its recent hits; over the limit inside the window
the request gets 429 with a Retry-After header."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..errors import ApiError

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def hit(key: str, limit: int, window_s: int) -> None:
    now = time.time()
    with _lock:
        q = _hits[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            retry = int(q[0] + window_s - now) + 1
            raise ApiError(429, "too_many_attempts", headers={"Retry-After": str(retry)})
        q.append(now)


def client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
