"""Orchestrates the agent team for one meeting. Compares against the approved baseline."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from . import agents, llm
from .diff import apply_changes, next_id
from .models import EstTask, ExtractedReq, MeetingIn, Requirement
from .store import Store


class Conflict(Exception):
    pass


def latest_approved(project: dict) -> dict | None:
    return next((v for v in reversed(project["versions"]) if v["status"] in ("approved", "sent")), None)


async def process_meeting(store: Store, project_id: str, m: MeetingIn) -> dict[str, Any]:
    p = store.data["projects"][project_id]
    baseline_v = latest_approved(p)
    if p["versions"] and baseline_v is None:
        raise Conflict("Approve the previous version first: follow-up meetings are compared with the approved baseline, not with an unapproved draft.")
    meeting_id = f"M{len(p['meetings']) + 1}"
    p["meetings"].append({"id": meeting_id, "title": m.title, "date": m.meeting_date, "transcript": m.transcript})
    u0, t0 = llm.usage_snapshot(), time.time()
    issues: list[str] = []

    base_reqs = [Requirement(**r) for r in baseline_v["requirements"]] if baseline_v else []
    base_cons = baseline_v["constraints"] if baseline_v else []
    base_tasks = [EstTask(**t) for t in baseline_v["tasks"]] if baseline_v else []

    # 1. analyst over overlapping chunks, then merge
    chunks = agents.split_transcript(m.transcript)
    parts = await asyncio.gather(*(agents.analyse_chunk(c, base_reqs) for c in chunks))
    ex = agents.merge_extracts(list(parts))
    for e in ex.requirements:
        if not agents.verify_quote(e.quote, m.transcript):
            issues.append(f"quote not found in transcript for: {e.description[:60]}")

    def assign(e: ExtractedReq) -> Requirement:
        return Requirement(description=e.description, quote=e.quote, line=e.line, meeting_id=meeting_id, status=e.status,
                           priority=e.priority, origin=e.origin, quote_verified=agents.verify_quote(e.quote, m.transcript))

    if baseline_v:
        reqs, cons, report = apply_changes(base_reqs, base_cons, ex, meeting_id, assign)
    else:
        reqs, report = [], {}
        for e in ex.requirements:
            r = assign(e); r.id = next_id(reqs); reqs.append(r)
        cons = [c.model_dump() for c in ex.constraints]

    # 2. feasibility only for new/modified items (calls Task 1 over HTTP)
    todo = [r for r in reqs if not r.removed and r.feasibility == "not_checked"]
    await asyncio.gather(*(agents.check_feasibility(r) for r in todo))
    if any("unavailable" in r.feasibility_evidence for r in todo):
        issues.append("Knowledge service was unavailable: affected requirements are marked needs_clarification")

    # 3. scope, 4. estimate (re-estimate only changed items), 5. proposal
    scope = await agents.write_scope(reqs, cons, ex.open_questions)
    for r in reqs:
        if not r.acceptance_criteria:
            r.acceptance_criteria = scope.acceptance_criteria.get(r.id, [])
    changed_ids = {r.id for r in todo}
    keep = [t for t in base_tasks if t.requirement_id not in changed_ids]
    tasks = keep + await agents.estimate([r for r in reqs if r.id in changed_ids])
    est = agents.totals(tasks, reqs)
    scope_md = agents.render_scope(scope, reqs, cons, ex.open_questions)
    proposal_md, p_issues = await agents.write_proposal(scope_md, reqs, est, tasks, cons)
    issues += p_issues
    if baseline_v:
        old = baseline_v["estimate"]
        report["estimate_delta"] = {"before_hours": old["expected_hours"], "after_hours": est["expected_hours"],
                                    "delta_hours": round(est["expected_hours"] - old["expected_hours"], 1),
                                    "before_price": old["price"], "after_price": est["price"]}
    u1 = llm.usage_snapshot()
    version = {"version": len(p["versions"]) + 1, "meeting_ids": [x["id"] for x in p["meetings"]], "status": "draft",
               "requirements": [r.model_dump() for r in reqs], "constraints": cons, "tasks": [t.model_dump() for t in tasks],
               "estimate": est, "scope_md": scope_md, "proposal_md": proposal_md, "change_report": report, "issues": issues,
               "open_questions": ex.open_questions, "created_at": datetime.now(timezone.utc).isoformat(),
               "baseline_version": baseline_v["version"] if baseline_v else None, "approved_by": None, "approved_at": None,
               "run": {"model": f"{llm.provider()}:{llm.chat_model()}", "prompts": agents.PROMPT_VERSIONS, "chunks": len(chunks),
                       "seconds": round(time.time() - t0, 2), "tokens_in": u1["in"] - u0["in"], "tokens_out": u1["out"] - u0["out"],
                       "cost_usd": round(llm.cost_usd(u1["in"] - u0["in"], u1["out"] - u0["out"]), 5)}}
    p["versions"].append(version)
    store.save()
    return version
