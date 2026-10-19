"""SQLite storage: manifest (pages), chunks+embeddings, image cache, escalations, runs."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages(
  url TEXT PRIMARY KEY, lastmod TEXT, content_hash TEXT, status TEXT DEFAULT 'pending',
  attempts INTEGER DEFAULT 0, error TEXT, title TEXT, active INTEGER DEFAULT 1, updated_at REAL);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_key TEXT UNIQUE, doc_id TEXT, url TEXT, title TEXT,
  section TEXT, kind TEXT, text TEXT, image_url TEXT, embedding BLOB, active INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS chunks_url ON chunks(url);
CREATE TABLE IF NOT EXISTS images(url TEXT PRIMARY KEY, description TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS escalations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, evidence TEXT, reason TEXT,
  status TEXT DEFAULT 'open', answer TEXT, approved INTEGER, created REAL, resolved REAL);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL, finished REAL, state TEXT,
  total INTEGER DEFAULT 0, added INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
  removed INTEGER DEFAULT 0, unchanged INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, note TEXT);
"""


def db_path() -> str:
    return os.getenv("KB_DB", "data/kb.sqlite")


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    path = db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()
