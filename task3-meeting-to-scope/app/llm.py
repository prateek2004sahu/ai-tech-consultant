"""Provider-agnostic LLM layer (no SDKs, plain HTTPS).

LLM_PROVIDER: gemini | openai | anthropic | mock
EMBED_PROVIDER: gemini | openai | mock   (Anthropic has no embeddings API)
LLM_MODEL overrides the default chat model, so you can run evals per model.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from typing import Callable

import httpx
import numpy as np

USAGE = {"in": 0, "out": 0, "calls": 0, "seconds": 0.0}
_MOCKS: dict[str, Callable[[str], str]] = {}


def register_mock(task: str, fn: Callable[[str], str]) -> None:
    _MOCKS[task] = fn


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "mock").lower()


def embed_provider() -> str:
    p = os.getenv("EMBED_PROVIDER")
    if p:
        return p.lower()
    return "gemini" if provider() == "anthropic" else provider()


DEFAULT_CHAT = {"gemini": "gemini-2.5-flash", "openai": "gpt-4o-mini",
                "anthropic": "claude-haiku-5-5", "mock": "mock"}


def chat_model() -> str:
    return os.getenv("LLM_MODEL") or DEFAULT_CHAT[provider()]


def usage_snapshot() -> dict:
    return dict(USAGE)


def cost_usd(delta_in: int, delta_out: int) -> float:
    """Set PRICE_IN_PER_M / PRICE_OUT_PER_M (USD per 1M tokens) for your model."""
    pin = float(os.getenv("PRICE_IN_PER_M", "0"))
    pout = float(os.getenv("PRICE_OUT_PER_M", "0"))
    return (delta_in * pin + delta_out * pout) / 1_000_000


def _count(inp: str, out: str, t0: float, usage: tuple[int, int] | None = None) -> None:
    i, o = usage if usage else (len(inp) // 4, len(out) // 4)
    USAGE["in"] += i
    USAGE["out"] += o
    USAGE["calls"] += 1
    USAGE["seconds"] += time.time() - t0


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


async def _post(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    r: httpx.Response | None = None
    for attempt in range(4):
        r = await client.post(url, **kw)
        if r.status_code in (429, 500, 502, 503, 529):
            await asyncio.sleep(2 ** attempt)
            continue
        break
    assert r is not None
    r.raise_for_status()
    return r


async def chat(system: str, user: str, *, json_mode: bool = False,
               images: list[tuple[str, bytes]] | None = None,
               max_tokens: int = 2000, task: str = "generic") -> str:
    p, t0 = provider(), time.time()
    if p == "mock":
        out = _MOCKS.get(task, lambda u: "{}")(user)
        _count(system + user, out, t0)
        return out
    key = os.getenv(f"{p.upper()}_API_KEY")
    if not key:
        raise RuntimeError(f"{p.upper()}_API_KEY is not set")
    model = chat_model()
    images = images or []
    async with httpx.AsyncClient(timeout=120) as c:
        if p == "gemini":
            parts: list[dict] = [{"text": user}]
            for mime, data in images:
                parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
            body: dict = {"systemInstruction": {"parts": [{"text": system}]},
                          "contents": [{"role": "user", "parts": parts}],
                          "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2}}
            if json_mode:
                body["generationConfig"]["responseMimeType"] = "application/json"
            r = await _post(c, f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                            headers={"x-goog-api-key": key}, json=body)
            d = r.json()
            out = "".join(x.get("text", "") for x in d["candidates"][0]["content"].get("parts", []))
            u = d.get("usageMetadata", {})
            usage = (u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)) if u else None
        elif p == "openai":
            content: list[dict] | str = user
            if images:
                content = [{"type": "text", "text": user}] + [
                    {"type": "image_url", "image_url": {"url": f"data:{m};base64,{base64.b64encode(b).decode()}"}}
                    for m, b in images]
            body = {"model": model, "max_tokens": max_tokens, "temperature": 0.2,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            r = await _post(c, "https://api.openai.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {key}"}, json=body)
            d = r.json()
            out = d["choices"][0]["message"]["content"]
            u = d.get("usage", {})
            usage = (u.get("prompt_tokens", 0), u.get("completion_tokens", 0)) if u else None
        elif p == "anthropic":
            content = [{"type": "text", "text": user + ("\n\nReturn ONLY valid JSON." if json_mode else "")}]
            for m, b in images:
                content.append({"type": "image", "source": {"type": "base64", "media_type": m,
                                                           "data": base64.b64encode(b).decode()}})
            body = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": content}]}
            r = await _post(c, "https://api.anthropic.com/v1/messages",
                            headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, json=body)
            d = r.json()
            out = "".join(x.get("text", "") for x in d["content"] if x.get("type") == "text")
            u = d.get("usage", {})
            usage = (u.get("input_tokens", 0), u.get("output_tokens", 0)) if u else None
        else:
            raise RuntimeError(f"Unknown LLM_PROVIDER {p}")
    _count(system + user, out, t0, usage)
    return out


_STOP = {"the", "a", "an", "to", "of", "and", "or", "in", "on", "for", "is", "are", "how", "do", "i", "my", "can", "what", "with", "it", "be"}


def tokens(t: str) -> list[str]:
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w
            for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in _STOP]


def _hash_embed(texts: list[str], dim: int = 4096) -> np.ndarray:
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in tokens(t):
            out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(n, 1e-9)


async def embed(texts: list[str], *, query: bool = False) -> np.ndarray:
    p = embed_provider()
    t0 = time.time()
    if p == "mock":
        return _hash_embed(texts)
    key = os.getenv(f"{p.upper()}_API_KEY")
    if not key:
        raise RuntimeError(f"{p.upper()}_API_KEY is not set (needed for embeddings)")
    vecs: list[list[float]] = []
    async with httpx.AsyncClient(timeout=120) as c:
        for i in range(0, len(texts), 50):
            batch = texts[i:i + 50]
            if p == "gemini":
                m = os.getenv("EMBED_MODEL", "gemini-embedding-001")
                task_type = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
                body = {"requests": [{"model": f"models/{m}", "taskType": task_type,
                                      "content": {"parts": [{"text": t[:8000]}]}} for t in batch]}
                r = await _post(c, f"https://generativelanguage.googleapis.com/v1beta/models/{m}:batchEmbedContents",
                                headers={"x-goog-api-key": key}, json=body)
                vecs += [e["values"] for e in r.json()["embeddings"]]
            elif p == "openai":
                m = os.getenv("EMBED_MODEL", "text-embedding-3-small")
                r = await _post(c, "https://api.openai.com/v1/embeddings",
                                headers={"Authorization": f"Bearer {key}"},
                                json={"model": m, "input": [t[:8000] for t in batch]})
                vecs += [e["embedding"] for e in r.json()["data"]]
            else:
                raise RuntimeError(f"Unknown EMBED_PROVIDER {p}")
    arr = np.array(vecs, dtype=np.float32)
    _count("".join(texts), "", t0, (sum(len(t) for t in texts) // 4, 0))
    return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)
