import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "trends_tool"))

from interest_store import load_interest_keywords

SCHEMA = (Path(__file__).resolve().parent / "trends_tool" / "schema.sql").read_text(
    encoding="utf-8"
).split("-- 示例")[0]


def test_load_interest_keywords_from_sqlite(tmp_path):
    db_path = tmp_path / "trends.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO interest_keywords (keyword, geo, timeframe, active) VALUES (?, ?, ?, ?)",
        ("alpha", "US", "now 7-d", 1),
    )
    conn.execute(
        "INSERT INTO interest_keywords (keyword, active) VALUES (?, ?)",
        ("beta-off", 0),
    )
    conn.commit()
    conn.close()

    rows = load_interest_keywords(db_path=str(db_path))
    assert [r["keyword"] for r in rows] == ["alpha"]
    assert rows[0]["geo"] == "US"
    assert rows[0]["timeframe"] == "now 7-d"


def test_load_interest_keywords_requires_env(monkeypatch):
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="TURSO_DATABASE_URL"):
        load_interest_keywords()
