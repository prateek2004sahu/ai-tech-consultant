"""Compare a follow-up meeting with the APPROVED baseline (never with an unapproved draft)."""
from __future__ import annotations

from .models import Constraint, Extract, Requirement


def next_id(reqs: list[Requirement]) -> str:
    n = max([int(r.id.split("-")[1]) for r in reqs if r.id.startswith("REQ-")] or [0])
    return f"REQ-{n + 1:03d}"


def apply_changes(baseline: list[Requirement], base_constraints: list[dict], ex: Extract, meeting_id: str,
                  assign: "callable") -> tuple[list[Requirement], list[dict], dict]:
    """Returns (revised requirements, revised constraints, change report). `assign(ExtractedReq)->Requirement`."""
    revised = [r.model_copy(deep=True) for r in baseline]
    by_id = {r.id: r for r in revised}
    rep: dict = {"added": [], "modified": [], "removed": [], "unchanged": [], "out_of_scope": [], "conflicts": [], "constraints": []}
    for e in ex.requirements:
        tgt = by_id.get(e.matches_id or "")
        if tgt and not tgt.removed:
            if e.change == "modified":
                rep["modified"].append({"id": tgt.id, "before": tgt.description, "after": e.description, "quote": e.quote, "line": e.line})
                tgt.description, tgt.quote, tgt.line, tgt.meeting_id = e.description, e.quote, e.line, meeting_id
                tgt.status, tgt.priority = e.status, e.priority
                tgt.feasibility, tgt.acceptance_criteria = "not_checked", []   # must be re-checked and re-estimated
            else:
                rep["unchanged"].append(tgt.id)
        else:
            new = assign(e)
            new.id = next_id(revised)
            revised.append(new); by_id[new.id] = new
            rep["added"].append({"id": new.id, "description": new.description, "quote": e.quote, "line": e.line})
            rep["out_of_scope"].append({"id": new.id, "description": new.description, "action": "not in approved baseline: quote separately"})
            if e.status == "disputed":
                rep["conflicts"].append(new.id)
    for rm in ex.removals:
        tgt = by_id.get(rm.matches_id)
        if tgt and not tgt.removed:
            tgt.removed = True
            rep["removed"].append({"id": tgt.id, "description": tgt.description, "quote": rm.quote, "line": rm.line})
    cons = {c["kind"]: c for c in base_constraints}
    for c in ex.constraints:
        old = cons.get(c.kind)
        if old and old["text"] != c.text and c.kind != "other":
            rep["constraints"].append({"kind": c.kind, "before": old["text"], "after": c.text})
        cons[c.kind if c.kind != "other" else f"other{len(cons)}"] = c.model_dump()
    return revised, list(cons.values()), rep
