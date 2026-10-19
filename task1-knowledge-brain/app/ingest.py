"""Polite, resumable, incremental ingestion: sitemap -> manifest -> fetch -> parse -> images -> embed."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from urllib import robotparser
from urllib.parse import urlparse

import httpx
import numpy as np

from . import llm
from .db import conn
from .parse import chunk_article, parse_article

log = logging.getLogger("ingest")
SITEMAP = lambda: os.getenv("SITEMAP_URL", "https://support.brilliantdirectories.com/support/sitemap.xml")
UA = lambda: os.getenv("CRAWL_USER_AGENT", "AITechConsultantBot/1.0 (student capstone; polite crawler)")
MAX_ATTEMPTS = 3
_run_lock = asyncio.Lock()


class RateLimiter:
    """Global politeness: at most one request start per CRAWL_DELAY seconds, across all workers."""

    def __init__(self, delay: float) -> None:
        self.delay, self._next, self._lock = delay, 0.0, asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self.delay


class PermanentError(Exception):
    pass


async def fetch(client: httpx.AsyncClient, rl: RateLimiter, url: str, retries: int = 4) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(retries):
        await rl.wait()
        try:
            r = await client.get(url)
            if r.status_code in (404, 410):
                raise PermanentError(f"HTTP {r.status_code}")
            if r.status_code in (429, 500, 502, 503, 504):
                ra = r.headers.get("retry-after")
                await asyncio.sleep(min(float(ra), 60) if ra and ra.isdigit() else float(os.getenv("BACKOFF_BASE", "2")) ** attempt)
                last = RuntimeError(f"HTTP {r.status_code}")
                continue
            if r.status_code >= 400:
                raise PermanentError(f"HTTP {r.status_code}")
            return r
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = e
            await asyncio.sleep(float(os.getenv("BACKOFF_BASE", "2")) ** attempt)
    raise RuntimeError(f"gave up after {retries} attempts: {last}")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


async def read_sitemap(client: httpx.AsyncClient, rl: RateLimiter, url: str, depth: int = 0) -> dict[str, str | None]:
    """Returns {url: lastmod}. Follows sitemap indexes. De-duplicates and validates URLs."""
    r = await fetch(client, rl, url)
    root = ET.fromstring(r.content)
    found: dict[str, str | None] = {}
    for node in root:
        loc = lastmod = None
        for ch in node:
            if _local(ch.tag) == "loc":
                loc = (ch.text or "").strip()
            elif _local(ch.tag) == "lastmod":
                lastmod = (ch.text or "").strip()
        if not loc or urlparse(loc).scheme not in ("http", "https"):
            continue
        if _local(root.tag) == "sitemapindex" and depth < 2:
            found.update(await read_sitemap(client, rl, loc, depth + 1))
        else:
            found[loc] = lastmod
    return found


def _doc_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


async def describe_image(client: httpx.AsyncClient, rl: RateLimiter, img_url: str, alt: str, ctx: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT description,status FROM images WHERE url=?", (img_url,)).fetchone()
    if row and row["status"] == "ok":
        return row["description"]
    try:
        if llm.provider() == "mock":
            desc = f"Screenshot (no vision model in mock mode). Alt text: {alt or 'none'}"
        else:
            r = await fetch(client, rl, img_url, retries=2)
            mime = r.headers.get("content-type", "").split(";")[0]
            if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif") or len(r.content) > 4_000_000:
                return None
            desc = await llm.chat(
                "You describe help-center screenshots for a search index. Be concise and factual. "
                "List visible UI labels, menu names, buttons, field names and any setting values. "
                "If something is unreadable say 'unclear'. Never invent labels.",
                f"Article context: {ctx[:400]}\nAlt text: {alt}\nDescribe what the screenshot shows.",
                images=[(mime, r.content)], max_tokens=400, task="vision")
        with conn() as c:
            c.execute("INSERT OR REPLACE INTO images(url,description,status) VALUES(?,?,?)", (img_url, desc, "ok"))
        return desc
    except Exception as e:  # image failure never fails the page
        log.warning("image failed %s: %s", img_url, e)
        with conn() as c:
            c.execute("INSERT OR REPLACE INTO images(url,description,status) VALUES(?,?,?)", (img_url, str(e), "failed"))
        return None


async def process_page(client: httpx.AsyncClient, rl: RateLimiter, robots: robotparser.RobotFileParser | None,
                       url: str, lastmod: str | None, force: bool) -> str:
    """Returns 'added' | 'updated' | 'unchanged' | 'failed' | 'gone'."""
    with conn() as c:
        row = c.execute("SELECT * FROM pages WHERE url=?", (url,)).fetchone()
        c.execute("UPDATE pages SET status='processing', attempts=attempts+1 WHERE url=?", (url,))
    had_content = bool(row and row["content_hash"])
    if (not force and row and row["status"] in ("done",) and lastmod and row["lastmod"] == lastmod):
        return "unchanged"
    try:
        if robots and not robots.can_fetch(UA(), url):
            raise PermanentError("blocked by robots.txt")
        r = await fetch(client, rl, url)
        if "html" not in r.headers.get("content-type", "html"):
            raise PermanentError("not html")
        art = parse_article(r.text, url)
        # A page with no article text is a failure, never "done" (prevents silent empty crawls)
        if not any(s["text"].strip() for s in art["sections"]):
            raise PermanentError("no article text found")
        if not force and row and row["content_hash"] == art["hash"]:
            with conn() as c:
                c.execute("UPDATE pages SET status='done', lastmod=?, error=NULL, updated_at=? WHERE url=?",
                          (lastmod, time.time(), url))
            return "unchanged"
        items: list[tuple[str, str, str | None]] = []  # (kind, text, image_url)
        for ch in chunk_article(art):
            items.append(("text", f"{art['title']} > {ch['section']}\n{ch['text']}", None))
        seen: set[str] = set()
        for s in art["sections"]:
            for im in s["images"][: int(os.getenv("MAX_IMAGES_PER_PAGE", "6"))]:
                if im["url"] in seen:
                    continue
                seen.add(im["url"])
                d = await describe_image(client, rl, im["url"], im["alt"], f"{art['title']} > {s['heading']}: {s['text']}")
                if d:
                    items.append(("image", f"Screenshot in '{art['title']}' section '{s['heading']}': {d} "
                                           f"(alt: {im['alt']}) Surrounding text: {s['text'][:200]}", im["url"]))
        vecs = await llm.embed([t for _, t, _ in items]) if items else np.zeros((0, 1), dtype=np.float32)
        doc = _doc_id(url)
        with conn() as c:  # atomic replace => idempotent, no duplicate chunks
            c.execute("DELETE FROM chunks WHERE url=?", (url,))
            for i, ((kind, text, img), v) in enumerate(zip(items, vecs)):
                c.execute("INSERT INTO chunks(chunk_key,doc_id,url,title,section,kind,text,image_url,embedding,active)"
                          " VALUES(?,?,?,?,?,?,?,?,?,1)",
                          (f"{doc}:{i}", doc, url, art["title"], text.split("\n", 1)[0], kind, text, img,
                           v.astype(np.float32).tobytes()))
            c.execute("UPDATE pages SET status='done', lastmod=?, content_hash=?, title=?, error=NULL, active=1, updated_at=? WHERE url=?",
                      (lastmod, art["hash"], art["title"], time.time(), url))
        return "updated" if had_content else "added"
    except PermanentError as e:
        with conn() as c:
            gone = "404" in str(e) or "410" in str(e)
            c.execute("UPDATE pages SET status=?, error=?, active=?, attempts=? WHERE url=?",
                      ("gone" if gone else "failed", str(e), 0 if gone else 1, MAX_ATTEMPTS, url))
            if gone:
                c.execute("UPDATE chunks SET active=0 WHERE url=?", (url,))
        return "gone" if "404" in str(e) or "410" in str(e) else "failed"
    except Exception as e:
        with conn() as c:
            c.execute("UPDATE pages SET status='failed', error=? WHERE url=?", (str(e)[:300], url))
        log.warning("page failed %s: %s", url, e)
        return "failed"


async def run_ingestion(limit: int | None = None, force: bool = False) -> dict:
    """One full incremental pass. Safe to call again after a crash: it resumes from the manifest."""
    if _run_lock.locked():
        return {"state": "already_running"}
    async with _run_lock:
        with conn() as c:
            run_id = c.execute("INSERT INTO runs(started,state) VALUES(?,?)", (time.time(), "running")).lastrowid
            c.execute("UPDATE pages SET status='pending' WHERE status='processing'")  # resume after crash
        stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "failed": 0}
        rl = RateLimiter(float(os.getenv("CRAWL_DELAY", "1.0")))
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": UA()}) as client:
            try:
                sitemap = await read_sitemap(client, rl, SITEMAP())
            except Exception as e:
                with conn() as c:
                    c.execute("UPDATE runs SET state='failed', finished=?, note=? WHERE id=?", (time.time(), str(e)[:300], run_id))
                return {"state": "failed", "error": str(e)}
            # Only crawl real article pages (the sitemap also lists home, section and folder index pages).
            # Set URL_FILTER= (empty) in .env to crawl everything.
            flt = os.getenv("URL_FILTER", "/solutions/articles/")
            sitemap = {u: lm for u, lm in sitemap.items() if flt in u}
            robots = robotparser.RobotFileParser()
            try:
                rr = await client.get(f"{urlparse(SITEMAP()).scheme}://{urlparse(SITEMAP()).netloc}/robots.txt")
                robots.parse(rr.text.splitlines() if rr.status_code == 200 else [])
            except Exception:
                robots.parse([])
            urls = list(sitemap)[:limit] if limit else list(sitemap)
            with conn() as c:
                known = {r["url"]: r for r in c.execute("SELECT * FROM pages")}
                for u in urls:
                    if u not in known:
                        c.execute("INSERT INTO pages(url,lastmod,status,active) VALUES(?,?,?,1)", (u, sitemap[u], "pending"))
                if not limit:  # removed pages: in manifest, active, but no longer in sitemap
                    for u, r in known.items():
                        if u not in sitemap and r["active"]:
                            c.execute("UPDATE pages SET active=0, status='removed' WHERE url=?", (u,))
                            c.execute("UPDATE chunks SET active=0 WHERE url=?", (u,))
                            stats["removed"] += 1
                for u in urls:  # re-activate pages that came back
                    c.execute("UPDATE pages SET active=1 WHERE url=? AND active=0 AND status!='gone'", (u,))
                    c.execute("UPDATE chunks SET active=1 WHERE url=? AND (SELECT active FROM pages WHERE url=?)=1", (u, u))
            sem = asyncio.Semaphore(int(os.getenv("CRAWL_CONCURRENCY", "2")))

            async def worker(u: str) -> None:
                async with sem:
                    with conn() as c:
                        r = c.execute("SELECT status,attempts FROM pages WHERE url=?", (u,)).fetchone()
                    if r and r["status"] in ("failed", "gone") and r["attempts"] >= MAX_ATTEMPTS and not force:
                        res = "unchanged" if r["status"] == "gone" else "failed"
                    else:
                        res = await process_page(client, rl, robots, u, sitemap[u], force)
                    if res == "gone":
                        res = "removed"
                    stats[res] += 1

            await asyncio.gather(*(worker(u) for u in urls))
        with conn() as c:
            c.execute("UPDATE runs SET state='done', finished=?, total=?, added=?, updated=?, removed=?, unchanged=?, failed=? WHERE id=?",
                      (time.time(), len(urls), stats["added"], stats["updated"], stats["removed"], stats["unchanged"], stats["failed"], run_id))
        return {"state": "done", "run_id": run_id, "total": len(urls), **stats}