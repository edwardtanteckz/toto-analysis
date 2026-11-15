"""SQLite schema and idempotent writers."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sgpools.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS toto_draws (
    draw_no      INTEGER PRIMARY KEY,
    draw_date    TEXT NOT NULL,
    n1 INTEGER NOT NULL, n2 INTEGER NOT NULL, n3 INTEGER NOT NULL,
    n4 INTEGER NOT NULL, n5 INTEGER NOT NULL, n6 INTEGER NOT NULL,
    additional   INTEGER NOT NULL,
    group1_prize INTEGER,
    fetched_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS toto_prizes (
    draw_no        INTEGER NOT NULL REFERENCES toto_draws(draw_no),
    prize_group    INTEGER NOT NULL,
    share_amount   INTEGER,
    winning_shares INTEGER,
    PRIMARY KEY (draw_no, prize_group)
);
CREATE TABLE IF NOT EXISTS fourd_draws (
    draw_no    INTEGER PRIMARY KEY,
    draw_date  TEXT NOT NULL,
    first      TEXT NOT NULL,
    second     TEXT NOT NULL,
    third      TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fourd_numbers (
    draw_no  INTEGER NOT NULL REFERENCES fourd_draws(draw_no),
    category TEXT NOT NULL,      -- first | second | third | starter | consolation
    position INTEGER NOT NULL,   -- order within category (1-based)
    number   TEXT NOT NULL,      -- 4-digit string, leading zeros kept
    PRIMARY KEY (draw_no, category, position)
);
CREATE TABLE IF NOT EXISTS toto_next_draw (
    fetched_at  TEXT NOT NULL,
    draw_date   TEXT NOT NULL,
    est_jackpot INTEGER
);
CREATE TABLE IF NOT EXISTS alerts_sent (
    draw_date TEXT PRIMARY KEY,
    sent_at   TEXT NOT NULL,
    message   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_toto_date  ON toto_draws(draw_date);
CREATE INDEX IF NOT EXISTS idx_fourd_date ON fourd_draws(draw_date);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def existing_draws(conn, table: str) -> set[int]:
    return {r[0] for r in conn.execute(f"SELECT draw_no FROM {table}")}


def insert_toto(conn, r) -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO toto_draws VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r.draw_no, r.draw_date.isoformat(), *r.numbers, r.additional, r.group1_prize, now()),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO toto_prizes VALUES (?,?,?,?)",
            [(r.draw_no, g, amt, shares) for g, amt, shares in r.prizes],
        )


def insert_fourd(conn, r) -> None:
    rows = [(r.draw_no, "first", 1, r.first), (r.draw_no, "second", 1, r.second), (r.draw_no, "third", 1, r.third)]
    rows += [(r.draw_no, "starter", i, n) for i, n in enumerate(r.starter, 1)]
    rows += [(r.draw_no, "consolation", i, n) for i, n in enumerate(r.consolation, 1)]
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO fourd_draws VALUES (?,?,?,?,?,?)",
            (r.draw_no, r.draw_date.isoformat(), r.first, r.second, r.third, now()),
        )
        conn.executemany("INSERT OR IGNORE INTO fourd_numbers VALUES (?,?,?,?)", rows)


def record_next_toto(conn, nxt) -> None:
    with conn:
        conn.execute(
            "INSERT INTO toto_next_draw VALUES (?,?,?)",
            (now(), nxt.draw_date.isoformat(), nxt.est_jackpot),
        )
