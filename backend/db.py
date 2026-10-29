from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "suicide_rates.sqlite"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH))
    if not path.exists():
        raise FileNotFoundError(f"Database not found at {path}; run `python -m backend.ingest` first.")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection
