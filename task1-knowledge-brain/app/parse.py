"""HTML -> normalized article (sections, images in place) -> chunks."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

NOISE = ["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]
SKIP_IMG = re.compile(r"logo|icon|avatar|spacer|pixel|emoji|badge|/hit$", re.I)
BLOCKS = ["h1", "h2", "h3", "h4", "p", "li", "pre", "table", "blockquote", "img"]


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def parse_article(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE):
        tag.decompose()
    main = (soup.select_one("article") or soup.select_one(".article-body, .article, #article")
            or soup.select_one("main") or soup.body or soup)
    h1 = main.find("h1") or soup.find("h1")
    title = _clean(h1.get_text()) if h1 else _clean(soup.title.get_text()) if soup.title else url
    sections: list[dict[str, Any]] = [{"heading": "Introduction", "lines": [], "images": []}]
    for el in main.find_all(BLOCKS):
        if el.name == "img":
            src = el.get("src") or el.get("data-src") or ""
            if not src or src.startswith("data:") or src.lower().endswith(".svg") or SKIP_IMG.search(src):
                continue
            try:
                if int(el.get("width", 999)) < 48 or int(el.get("height", 999)) < 48:
                    continue
            except ValueError:
                pass
            sections[-1]["images"].append({"url": urljoin(url, src), "alt": _clean(el.get("alt", ""))})
            continue
        if el.name in ("h2", "h3", "h4"):
            sections.append({"heading": _clean(el.get_text()), "lines": [], "images": []})
        elif el.name == "h1":
            continue
        elif el.name == "li":
            if el.find_parent("li"):
                continue
            sections[-1]["lines"].append("- " + _clean(el.get_text(" ")))
        elif el.name == "table":
            rows = [" | ".join(_clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])) for tr in el.find_all("tr")]
            sections[-1]["lines"].append("\n".join(r for r in rows if r.strip(" |")))
        else:
            if el.find_parent(["li", "table", "pre", "blockquote"]):
                continue
            txt = _clean(el.get_text(" "))
            if txt:
                sections[-1]["lines"].append(txt)
    out = [{"heading": s["heading"], "text": "\n".join(s["lines"]), "images": s["images"]}
           for s in sections if s["lines"] or s["images"]]
    digest = hashlib.sha256(json.dumps([title, out], sort_keys=True).encode()).hexdigest()
    return {"url": url, "title": title, "sections": out, "hash": digest}


def chunk_article(art: dict[str, Any], max_chars: int = 1200) -> list[dict[str, Any]]:
    """Split at headings first; then by paragraph with one-paragraph overlap."""
    chunks: list[dict[str, Any]] = []
    for s in art["sections"]:
        paras = [p for p in s["text"].split("\n") if p.strip()]
        cur: list[str] = []
        size = 0
        for p in paras:
            if cur and size + len(p) > max_chars:
                chunks.append({"section": s["heading"], "text": "\n".join(cur), "images": s["images"]})
                cur, size = cur[-1:], len(cur[-1])  # overlap
            cur.append(p)
            size += len(p)
        if cur:
            chunks.append({"section": s["heading"], "text": "\n".join(cur), "images": s["images"]})
    return chunks