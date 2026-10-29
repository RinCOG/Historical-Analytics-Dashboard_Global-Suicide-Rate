from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from backend.analysis import CSV_PATH, load_and_validate
from backend.db import DEFAULT_DB_PATH


def ingest(csv_path: Path = CSV_PATH, db_path: Path = DEFAULT_DB_PATH) -> int:
    frame = load_and_validate(csv_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS suicide_rates (
                    entity TEXT NOT NULL,
                    code TEXT NOT NULL,
                    year INTEGER NOT NULL CHECK (year BETWEEN 1950 AND 2005),
                    rate REAL NOT NULL CHECK (rate >= 0),
                    PRIMARY KEY (entity, year)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_suicide_rates_entity ON suicide_rates(entity)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_suicide_rates_year ON suicide_rates(year)")
            connection.execute("DELETE FROM suicide_rates")
            connection.executemany(
                "INSERT INTO suicide_rates(entity, code, year, rate) VALUES (?, ?, ?, ?)",
                frame[["entity", "code", "year", "rate"]].itertuples(index=False, name=None),
            )
    finally:
        connection.close()
    return len(frame)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the source CSV and load SQLite.")
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    print(f"Loaded {ingest(args.csv, args.db):,} validated rows into {args.db}")


if __name__ == "__main__":
    main()
