"""Database connection helper (a STUB — wire it up however you like).

Branches on the DATABASE_URL scheme:
  sqlite:///./app.sqlite        -> stdlib sqlite3 (fallback default)
  postgresql://user:pw@host/db  -> psycopg v3 (Docker default)

No schema or migrations are created for you: modeling the documents and their
relationships is part of the task. You are also free to ignore this entirely
and work in memory from the seed documents (see seed.py).
"""

from __future__ import annotations

from urllib.parse import urlparse

from config import load_config


def get_connection():
    url = load_config().database_url
    scheme = urlparse(url).scheme

    if scheme == "sqlite":
        import sqlite3

        path = url.replace("sqlite:///", "", 1) or ":memory:"
        return sqlite3.connect(path)

    if scheme in ("postgres", "postgresql"):
        import psycopg  # imported lazily so the SQLite path needs no driver

        return psycopg.connect(url)

    raise ValueError(f"Unsupported DATABASE_URL scheme: {scheme!r}")
