"""SQLite persistence. The original kept patients in a module-level array that
vanished on restart, which made the audit log describe records that no longer
existed."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .security import encrypt_field, hash_password

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'clinician'))
);

CREATE TABLE IF NOT EXISTS patients (
    id             TEXT PRIMARY KEY,
    created_by     INTEGER NOT NULL REFERENCES users(id),
    full_name      TEXT NOT NULL,
    dob            TEXT NOT NULL,
    ssn_encrypted  TEXT NOT NULL,
    ssn_last4      TEXT NOT NULL,
    symptoms       TEXT NOT NULL DEFAULT '',
    clinical_notes TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_patients_created_by ON patients(created_by);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(seed: bool = True) -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        if not seed:
            return
        if conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]:
            return
        # Demo credentials. Fine for a portfolio demo; the point is that they
        # are hashed, not that they are secret.
        for username, password, role in [
            ("admin", "admin123", "admin"),
            ("clinician", "clinician123", "clinician"),
        ]:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                (username, hash_password(password), role),
            )


def seed_demo_patients(user_id: int) -> None:
    rows = [
        ("Soren Whitfield", "1984-03-11", "218-34-1441",
         "Epigastric burning, worse after meals",
         "Patient is a 38-year-old schoolteacher seen at Presbyterian Medical "
         "Center. Follow up with Dr. Thorne on 2017-12-14. Reachable at "
         "(361) 889-6980."),
        ("Amara Okonkwo", "1971-09-02", "402-77-9013",
         "Progressive dyspnea on exertion",
         "Ms. Okonkwo, a 54-year-old welder, was last seen at Mercy General on "
         "March 3, 2019 by Dr. Halloway. Okonkwo has not been compliant with "
         "her lisinopril."),
    ]
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) c FROM patients").fetchone()["c"]:
            return
        for name, dob, ssn, symptoms, notes in rows:
            conn.execute(
                "INSERT INTO patients (id, created_by, full_name, dob, "
                "ssn_encrypted, ssn_last4, symptoms, clinical_notes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), user_id, name, dob, encrypt_field(ssn),
                 ssn[-4:], symptoms, notes),
            )
