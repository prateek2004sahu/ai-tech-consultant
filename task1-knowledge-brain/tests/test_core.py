"""End-to-end test against a local fake help center (no internet, mock LLM)."""
import asyncio
import http.server
import os
import threading

import pytest

PAGES: dict[str, tuple[int, str]] = {}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        code, body = PAGES.get(self.path, (404, "nf"))
        ct = "application/xml" if self.path.endswith(".xml") else "text/html"
        self.send_response(code); self.send_header("Content-Type", ct); self.end_headers()
        self.wfile.write(body.encode())


def sitemap(urls):
    return '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        f"<url><loc>{u}</loc><lastmod>{lm}</lastmod></url>" for u, lm in urls) + "</urlset>"


def art(title, body):
    return f"<html><body><nav>MENU JUNK</nav><article><h1>{title}</h1>{body}</article><footer>FOOT</footer></body></html>"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    for k, v in {"LLM_PROVIDER": "mock", "KB_DB": str(tmp_path / "kb.sqlite"), "CRAWL_DELAY": "0",
                 "BACKOFF_BASE": "0", "MIN_SCORE": "0.3", "SITEMAP_URL": f"{base}/sitemap.xml"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    PAGES.clear()
    yield base
    srv.shutdown()


def run(coro):
    return asyncio.run(coro)


def test_full_lifecycle(env):
    from app import rag
    from app.db import conn
    from app.ingest import run_ingestion
    b = env
    PAGES["/a"] = (200, art("Change your logo", "<h2>Steps</h2><p>Open Design Settings then Logo and upload a new logo file.</p>"
                            f"<img src='{b}/img/logo-shot.png' alt='logo settings screen'>"))
    PAGES["/b"] = (200, art("Refund policy", "<p>Refunds are processed within 5 business days for annual plans.</p>"))
    PAGES["/gone"] = (404, "x")
    PAGES["/sitemap.xml"] = (200, sitemap([(b + "/a", "1"), (b + "/b", "1"), (b + "/gone", "1")]))

    r = run(run_ingestion())
    assert r["added"] == 2 and r["removed"] == 1, r  # 404 page is deactivated, others added
    with conn() as c:
        n1 = c.execute("SELECT COUNT(*) n FROM chunks WHERE active=1").fetchone()["n"]
        junk = c.execute("SELECT COUNT(*) n FROM chunks WHERE text LIKE '%MENU JUNK%'").fetchone()["n"]
    assert n1 >= 2 and junk == 0

    r = run(run_ingestion())  # idempotent: nothing duplicated
    with conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM chunks WHERE active=1").fetchone()["n"] == n1
    assert r["added"] == 0 and r["updated"] == 0

    a = run(rag.answer("How do I change my logo?"))
    assert a["status"] == "answered" and a["sources"][0]["url"].endswith("/a")

    a = run(rag.answer("What is the airspeed velocity of a swallow?"))
    assert a["status"] == "insufficient_evidence" and a["escalation_id"], a
    assert run(rag.resolve_escalation(a["escalation_id"], "An unladen swallow flies about 11 m/s.", True))
    a2 = run(rag.answer("What is the airspeed velocity of a swallow?"))
    assert a2["status"] == "answered" and a2["sources"][0]["url"].startswith("expert://")

    PAGES["/b"] = (200, art("Refund policy", "<p>Refunds now take 10 business days.</p>"))
    PAGES["/sitemap.xml"] = (200, sitemap([(b + "/a", "1"), (b + "/b", "2")]))  # /b updated, others removed? /gone dropped
    r = run(run_ingestion())
    assert r["updated"] == 1
    PAGES["/sitemap.xml"] = (200, sitemap([(b + "/a", "1")]))  # /b removed
    r = run(run_ingestion())
    assert r["removed"] >= 1
    a = run(rag.answer("How many business days do refunds take?"))
    assert all(not s["url"].endswith("/b") for s in a["sources"])


def test_api_validation(env):
    from fastapi.testclient import TestClient
    os.environ["ENABLE_SCHEDULER"] = "0"
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/health").json()["ok"]
        assert c.post("/query", json={"question": "x"}).status_code == 422
        assert c.post("/query", json={"question": "How do I do things?"}).json()["status"] == "insufficient_evidence"
