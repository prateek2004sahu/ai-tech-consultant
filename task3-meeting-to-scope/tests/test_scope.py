import asyncio
import os

import pytest
from fastapi.testclient import TestClient

T = os.path.join(os.path.dirname(__file__), "..", "transcripts")
read = lambda n: open(os.path.join(T, n)).read()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "p.json"))
    from app import kb_client, main
    from app.store import Store

    async def fake_kb(q):  # stub of Task 1 HTTP API
        if "AI search" in q:
            return kb_client.KbAnswer(status="insufficient_evidence", answer="", sources=[], needs_human=True, escalation_id=7)
        return kb_client.KbAnswer(status="answered", answer="Settings exist under Admin > Search.", sources=[{"url": "https://kb/x"}], needs_human=False)
    monkeypatch.setattr(kb_client, "query", fake_kb)
    main.store = Store(str(tmp_path / "p.json"))
    return TestClient(main.app)


def test_chunking_keeps_line_numbers():
    from app.agents import split_transcript
    chunks = split_transcript("\n".join(f"Client: line number {i} we need things" for i in range(1, 60)), max_chars=300)
    assert len(chunks) > 3 and chunks[1].splitlines()[0].startswith("L")


def test_full_flow(client):
    pid = client.post("/api/projects", json={"name": "Site", "client": "Acme"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/meetings", json={"title": "A", "meeting_date": "2026-10-16", "transcript": read("meeting_a_website.txt")})
    assert r.status_code == 201, r.text
    v1 = r.json()
    descs = " ".join(x["description"].lower() for x in v1["requirements"])
    assert "filter" in descs and "mobile" in descs
    assert all(x["quote_verified"] for x in v1["requirements"])           # quotes exist in transcript
    ai = next(x for x in v1["requirements"] if "ai" in x["description"].lower())
    assert ai["feasibility"] == "needs_clarification" and ai["status"] == "unclear"  # missing KB evidence is not "custom"
    assert v1["estimate"]["pending_expected_hours"] > 0                    # unclear work is not priced

    # human gate
    assert client.post(f"/api/projects/{pid}/versions/1/send").status_code == 403
    # follow-up before approval is refused (baseline must be approved)
    r = client.post(f"/api/projects/{pid}/meetings", json={"title": "C", "meeting_date": "2026-10-20", "transcript": read("meeting_c_followup.txt")})
    assert r.status_code == 409
    assert client.post(f"/api/projects/{pid}/versions/1/approve", json={"reviewer": "Sam"}).status_code == 200

    r = client.post(f"/api/projects/{pid}/meetings", json={"title": "C", "meeting_date": "2026-10-20", "transcript": read("meeting_c_followup.txt")})
    assert r.status_code == 201, r.text
    v2 = r.json(); rep = v2["change_report"]
    assert v2["baseline_version"] == 1 and v2["status"] == "draft"
    assert rep["removed"], rep                          # brand filter dropped
    assert rep["added"] and rep["out_of_scope"], rep    # wishlist / sort are new
    assert any(c["kind"] == "deadline" for c in rep["constraints"]), rep
    assert "estimate_delta" in rep
    assert client.post(f"/api/projects/{pid}/versions/2/send").status_code == 403
    assert client.post(f"/api/projects/{pid}/versions/2/approve", json={"reviewer": "Sam"}).status_code == 200
    assert client.post(f"/api/projects/{pid}/versions/2/send").status_code == 200


def test_kb_down_is_flagged_not_guessed(client, monkeypatch):
    from app import kb_client

    async def down(q): return None
    monkeypatch.setattr(kb_client, "query", down)
    pid = client.post("/api/projects", json={"name": "S", "client": "A"}).json()["id"]
    v = client.post(f"/api/projects/{pid}/meetings", json={"title": "B", "meeting_date": "2026-10-16", "transcript": read("meeting_b_ecommerce.txt")}).json()
    assert all(r["feasibility"] == "needs_clarification" for r in v["requirements"])
    assert any("unavailable" in i for i in v["issues"])
