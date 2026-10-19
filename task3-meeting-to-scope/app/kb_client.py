"""Typed client for Task 1. Task 3 never imports Task 1 code: HTTP only."""
from __future__ import annotations

import os
import uuid

import httpx
from pydantic import BaseModel


class KbAnswer(BaseModel):
    status: str
    answer: str
    sources: list[dict]
    needs_human: bool
    escalation_id: int | None = None


async def query(question: str) -> KbAnswer | None:
    """None means the knowledge service is unavailable (caller must flag, never guess)."""
    url = os.getenv("KB_URL", "http://localhost:8001")
    headers = {"X-Request-ID": uuid.uuid4().hex[:12]}
    if os.getenv("KB_API_KEY"):
        headers["X-API-Key"] = os.environ["KB_API_KEY"]
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("KB_TIMEOUT", "30"))) as c:
                r = await c.post(f"{url}/query", json={"question": question, "escalate": True}, headers=headers)
            if r.status_code >= 500:
                continue
            r.raise_for_status()
            return KbAnswer.model_validate(r.json())
        except (httpx.HTTPError, ValueError):
            continue
    return None
