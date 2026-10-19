"""Knowledge Brain API (FastAPI). Docs at /docs."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()
from . import llm, rag  # noqa: E402
from .db import conn  # noqa: E402
from .ingest import run_ingestion  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    with conn() as c:
        c.execute("UPDATE pages SET status='pending' WHERE status='processing'")
    sched = None
    if os.getenv("ENABLE_SCHEDULER", "1") == "1":
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        sched = AsyncIOScheduler()
        sched.add_job(run_ingestion, "cron", hour=int(os.getenv("DAILY_HOUR", "2")), id="daily")
        sched.start()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Knowledge Brain", version="1.0", lifespan=lifespan,
              description="Shared knowledge service. Tasks 2 and 3 consume it ONLY through this API.")


def auth(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("KB_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(401, "invalid or missing X-API-Key")


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    resp = await call_next(request)
    resp.headers["X-Request-ID"] = rid
    return resp


class QueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(6, ge=1, le=20)
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    escalate: bool = Field(True, description="Create a human-expert task when evidence is insufficient")
    context: str | None = Field(None, max_length=2000)


class Source(BaseModel):
    title: str
    url: str
    relevance: float


class QueryOut(BaseModel):
    answer: str
    status: Literal["answered", "insufficient_evidence"]
    sources: list[Source]
    images: list[str] = Field(description="Screenshot URLs that supported the answer")
    top_score: float = Field(description="Best retrieval score (0-1). NOT a calibrated probability.")
    needs_human: bool
    escalation_id: int | None
    prompt_version: str


class IngestIn(BaseModel):
    limit: int | None = Field(None, ge=1, description="Only first N sitemap URLs (use 10-20 for a first test)")
    force: bool = False


class ResolveIn(BaseModel):
    answer: str = Field(min_length=3)
    approved: bool = Field(True, description="Approved answers become searchable knowledge")


class EscalationIn(BaseModel):
    question: str = Field(min_length=3)
    reason: str = "manual"


@app.get("/health")
async def health() -> dict:
    with conn() as c:
        n = c.execute("SELECT COUNT(*) n FROM chunks WHERE active=1").fetchone()["n"]
    return {"ok": True, "active_chunks": n, "provider": llm.provider(), "model": llm.chat_model()}


@app.post("/query", response_model=QueryOut, dependencies=[Depends(auth)])
async def query(body: QueryIn) -> dict:
    try:
        return await asyncio.wait_for(
            rag.answer(body.question, body.top_k, body.mode, body.escalate, body.context),
            timeout=float(os.getenv("QUERY_TIMEOUT", "60")))
    except asyncio.TimeoutError:
        raise HTTPException(504, "query timed out")
    except HTTPException:
        raise
    except Exception as e:  # model/network/quota problems become a readable 503, not a bare 500
        import logging
        logging.getLogger("query").exception("query failed")
        raise HTTPException(503, f"model unavailable: {type(e).__name__}: {str(e)[:300]}")


@app.post("/ingestion/run", status_code=202, dependencies=[Depends(auth)])
async def ingestion_run(body: IngestIn, bg: BackgroundTasks) -> dict:
    bg.add_task(run_ingestion, body.limit, body.force)
    return {"accepted": True}


@app.get("/ingestion/status", dependencies=[Depends(auth)])
async def ingestion_status() -> dict:
    with conn() as c:
        last = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        pages = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM pages GROUP BY status")}
        chunks = c.execute("SELECT kind, COUNT(*) n FROM chunks WHERE active=1 GROUP BY kind").fetchall()
    return {"last_run": dict(last) if last else None, "pages_by_status": pages,
            "active_chunks": {r["kind"]: r["n"] for r in chunks}}


@app.post("/escalations", status_code=201, dependencies=[Depends(auth)])
async def escalation_create(body: EscalationIn) -> dict:
    return {"id": rag.create_escalation(body.question, [], body.reason)}


@app.get("/escalations", dependencies=[Depends(auth)])
async def escalation_list(status: Literal["open", "resolved"] = "open") -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM escalations WHERE status=? ORDER BY id DESC", (status,)).fetchall()
    return [{**dict(r), "evidence": json.loads(r["evidence"] or "[]")} for r in rows]


@app.post("/escalations/{esc_id}/resolve", dependencies=[Depends(auth)])
async def escalation_resolve(esc_id: int, body: ResolveIn) -> dict:
    if not await rag.resolve_escalation(esc_id, body.answer, body.approved):
        raise HTTPException(404, "escalation not found or already resolved")
    return {"resolved": True, "searchable": body.approved}


@app.get("/")
async def ui() -> FileResponse:
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))