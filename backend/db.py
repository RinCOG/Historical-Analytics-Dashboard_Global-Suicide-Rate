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
    # Open read-only so the connection works on read-only filesystems (e.g. Vercel serverless).
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection
