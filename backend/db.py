from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "suicide_rates.sqlite"
CSV_PATH = ROOT / "data" / "SDG-3___suicide-rates-by-country.csv"


def _candidate_paths() -> list[Path]:
    candidates = [Path(os.environ.get("DATABASE_PATH", ""))] if os.environ.get("DATABASE_PATH") else []
    candidates += [
        DEFAULT_DB_PATH,
        Path.cwd() / "data" / "suicide_rates.sqlite",
        Path("/tmp") / "suicide_rates.sqlite",
        Path("/tmp") / "data" / "suicide_rates.sqlite",
    ]
    return [p for p in candidates if str(p)]


def _ensure_db() -> Path:
    """Return a usable SQLite DB path, generating it from the CSV into /tmp if needed."""
    for candidate in _candidate_paths():
        if candidate.exists():
            return candidate
    # Fall back: generate the DB from the committed CSV into a writable location.
    out_dir = Path("/tmp") / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "suicide_rates.sqlite"
    if not out_path.exists():
        # Run ingest logic by importing and invoking it programmatically.
        try:
            from backend import ingest
            ingest.ingest(CSV_PATH, out_path)
        except Exception:
            # Last resort: shell out to the module.
            subprocess.run(
                [sys.executable, "-m", "backend.ingest", "--db", str(out_path)],
                check=False,
            )
    if out_path.exists():
        return out_path
    # If still missing, return the default (will raise FileNotFoundError downstream).
    return DEFAULT_DB_PATH


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    if db_path is not None:
        path = Path(db_path)
    else:
        path = _ensure_db()
    if not path.exists():
        raise FileNotFoundError(f"Database not found at {path}; run `python -m backend.ingest` first.")
    # Open read-only so the connection works on read-only filesystems (e.g. Vercel serverless).
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection
