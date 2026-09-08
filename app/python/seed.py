"""Load the seed documents from DATA_DIR.

Each document is one JSON file under data/purchase_orders/ and data/invoices/.
Files are loaded independently: a file that fails to parse is reported in the
returned `errors` list rather than crashing the whole load (one seed file is
deliberately corrupt — detecting and handling bad uploads is part of the task).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from config import load_config


@dataclass
class LoadResult:
    purchase_orders: list[dict] = field(default_factory=list)
    invoices: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # [{"file": ..., "error": ...}]


def _load_dir(path: str, into: list[dict], errors: list[dict]) -> None:
    if not os.path.isdir(path):
        errors.append({"file": path, "error": "directory not found"})
        return
    for name in sorted(os.listdir(path)):
        if not name.endswith(".json"):
            continue
        full = os.path.join(path, name)
        try:
            with open(full, encoding="utf-8") as f:
                into.append(json.load(f))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append({"file": full, "error": str(exc)})


def load_documents() -> LoadResult:
    data_dir = load_config().data_dir
    result = LoadResult()
    _load_dir(os.path.join(data_dir, "purchase_orders"), result.purchase_orders, result.errors)
    _load_dir(os.path.join(data_dir, "invoices"), result.invoices, result.errors)
    return result
