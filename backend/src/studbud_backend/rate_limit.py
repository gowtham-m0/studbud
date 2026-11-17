import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_lock = None
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _get_lock():
    global _lock
    if _lock is None:
        import asyncio

        _lock = asyncio.Lock()
    return _lock


async def enforce_rate_limit(
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int = 60,
) -> None:
    """Single-process fixed-window rate limit.

    Render runs one process for the MVP, so an in-memory limit is enough.
    Move to Redis or a database counter if the API scales horizontally.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = (scope, client_ip)
    now = time.monotonic()

    async with _get_lock():
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])))
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
