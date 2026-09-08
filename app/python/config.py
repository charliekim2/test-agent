"""Configuration read from environment variables.

Defaults match the no-Docker fallback (SQLite + local ERP). Docker Compose
overrides these to point at the `postgres` and `erp` services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> str:
    """<repo>/data, resolved from this file so the default works from any cwd.
    Falls back to ./data if the repo layout isn't above this file (e.g. when the
    app dir is mounted at the container root)."""
    try:
        return str(Path(__file__).resolve().parents[2] / "data")
    except IndexError:
        return "./data"


@dataclass
class Config:
    database_url: str
    erp_base_url: str
    data_dir: str


def load_config() -> Config:
    return Config(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./app.sqlite"),
        erp_base_url=os.environ.get("ERP_BASE_URL", "http://localhost:9000"),
        # `or` (not get's default) so the lazy fallback only runs when unset.
        data_dir=os.environ.get("DATA_DIR") or _default_data_dir(),
    )
