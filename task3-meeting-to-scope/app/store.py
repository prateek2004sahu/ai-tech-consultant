"""Tiny JSON store with atomic writes. Swap for Postgres in production."""
from __future__ import annotations

import json
import os
from typing import Any


class Store:
    def __init__(self, path: str | None = None) -> None:
        self.path = path if path is not None else os.getenv("DB_PATH", "data/projects.json")
        self.data: dict[str, Any] = {"projects": {}}
        if self.path and os.path.exists(self.path):
            self.data = json.load(open(self.path))

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.data, f, indent=1)
        os.replace(self.path + ".tmp", self.path)
