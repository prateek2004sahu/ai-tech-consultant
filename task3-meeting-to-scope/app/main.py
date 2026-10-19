from __future__ import annotations

import glob
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

load_dotenv()
from . import llm  # noqa: E402
from .models import ApproveIn, MeetingIn, ProjectIn  # noqa: E402
from .pipeline import Conflict, process_meeting  # noqa: E402
from .store import Store  # noqa: E402

app = FastAPI(title="Meeting to Scope", version="1.0")
store = Store()
HERE = os.path.dirname(__file__)


def _project(pid: str) -> dict:
    p = store.data["projects"].get(pid)
    if not p:
        raise HTTPException(404, "project not found")
    return p


def _version(p: dict, v: int) -> dict:
    if not 1 <= v <= len(p["versions"]):
        raise HTTPException(404, "version not found")
    return p["versions"][v - 1]


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "model": llm.chat_model(), "kb_url": os.getenv("KB_URL", "http://localhost:8001")}


@app.post("/api/projects", status_code=201)
async def create_project(body: ProjectIn) -> dict:
    pid = uuid.uuid4().hex[:8]
    store.data["projects"][pid] = {"id": pid, **body.model_dump(), "meetings": [], "versions": []}
    store.save()
    return {"id": pid}


@app.get("/api/projects")
async def list_projects() -> list[dict]:
    return [{"id": p["id"], "name": p["name"], "client": p["client"], "versions": [(v["version"], v["status"]) for v in p["versions"]]}
            for p in store.data["projects"].values()]


@app.get("/api/projects/{pid}")
async def get_project(pid: str) -> dict:
    return _project(pid)


@app.post("/api/projects/{pid}/meetings", status_code=201)
async def add_meeting(pid: str, body: MeetingIn) -> dict:
    _project(pid)
    try:
        return await process_meeting(store, pid, body)
    except Conflict as e:
        raise HTTPException(409, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"AI pipeline failed: {e}")


@app.post("/api/projects/{pid}/versions/{v}/approve")
async def approve(pid: str, v: int, body: ApproveIn) -> dict:
    ver = _version(_project(pid), v)
    if ver["status"] != "draft":
        raise HTTPException(409, f"version is already {ver['status']}")
    ver.update(status="approved", approved_by=body.reviewer, approved_at=datetime.now(timezone.utc).isoformat())
    store.save()
    return ver


@app.post("/api/projects/{pid}/versions/{v}/send")
async def send(pid: str, v: int) -> dict:
    ver = _version(_project(pid), v)
    if ver["status"] != "approved":   # hard gate: nothing unapproved reaches the client
        raise HTTPException(403, "only an approved version can be sent to the client")
    ver.update(status="sent", sent_at=datetime.now(timezone.utc).isoformat())  # SIMULATED delivery
    store.save()
    return {"sent": True, "simulated": True, "version": v}


@app.get("/api/samples")
async def samples() -> list[dict]:
    return [{"name": os.path.basename(f), "text": open(f).read()} for f in sorted(glob.glob(os.path.join(HERE, "..", "transcripts", "*.txt")))]


@app.get("/")
async def ui() -> FileResponse:
    return FileResponse(os.path.join(HERE, "..", "static", "index.html"))
