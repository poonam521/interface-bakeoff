"""SQLite schema, seed data and the data operations shared by the HTML pages and the JSON API.

Generic demo data written for this project.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("open", "in_progress", "closed")
PRIORITIES = ("low", "medium", "high", "urgent")
USERS = ("Sam", "Dana", "Lee", "Priya")
TITLE_MAX = 60
COMMENT_AUTHOR = "agent"
# Columns that change on every write and carry no meaning for verification.
VOLATILE = {"created_at", "updated_at"}

SCHEMA = """
DROP TABLE IF EXISTS comments;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS users;
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'medium',
    assignee TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# id, title, description, status, priority, assignee
_T = [
    (1, "Printer on floor 2 is jammed", "Paper stuck in tray 2.", "open", "low", None),
    (2, "VPN drops every hour", "Disconnects roughly every 60 minutes.", "open", "high", "Sam"),
    (3, "New starter needs a laptop", "Starts on Monday.", "in_progress", "medium", "Dana"),
    (4, "Projector bulb is dead", "Meeting room A projector shows nothing.", "open", "low", None),
    (5, "Password reset for finance kiosk", "Kiosk account locked.", "closed", "medium", "Sam"),
    (6, "Cannot connect to VPN from home", "Error 809 on connect.", "open", "medium", "Lee"),
    (7, "Email signiture is wrong", "Shows the old office address.", "open", "low", "Priya"),
    (8, "Slow wifi in meeting room B", "Video calls freeze after ten minutes.", "open", "medium", "Dana"),
    (9, "VPN certificate expired", "Renewed on the gateway.", "closed", "high", "Sam"),
    (10, "Laptop fan is noisy", "Loudest while connected to the VPN.", "open", "low", "Lee"),
    (11, "Request: VPN access for contractor", "Needed for six weeks.", "open", "low", None),
    (12, "Monitor flickers at desk 14", "Flickers when the lamp is on.", "open", "medium", "Lee"),
    (13, "Shared drive is full", "Less than 1 GB free.", "open", "high", "Sam"),
    (14, "Badge reader at side door fails", "Red light for every badge.", "open", "high", "Sam"),
    (15, "Update antivirus on reception PC", "Definitions are a month old.", "in_progress", "high", "Sam"),
    (16, "Keyboard missing keys", "F and J keys gone.", "closed", "low", "Lee"),
    (17, "Install design software for Priya", "Licence already bought.", "open", "medium", "Priya"),
    (18, "Conference phone has no dial tone", "Room C, since Tuesday.", "open", "medium", "Lee"),
    (19, "Reset MFA for Lee", "New phone.", "closed", "high", "Sam"),
    (20, "Onboarding checklist for interns", "Draft for review.", "open", "low", "Dana"),
    (21, "Replace toner in printer 3", "Black toner low.", "open", "low", "Priya"),
    (22, "Scanner produces blank pages", "Glass was cleaned, still blank.", "open", "medium", "Dana"),
    (23, "Desk phone voicemail is full", "Cannot receive new messages.", "open", "low", "Priya"),
    (24, "Standing desk motor stuck", "Desk 9 will not go down.", "open", "medium", None),
    (25, "Old server room key is missing", "Key was last signed out by facilities on 3 March.", "open", "medium", "Dana"),
    (26, "Audit of server room access", "Annual review of who holds keys.", "open", "medium", "Dana"),
    (27, "Replace toner in printer 3", "Black toner low.", "open", "low", "Priya"),
    (28, "Webcam not detected on dock", "Works when plugged in directly.", "in_progress", "low", "Lee"),
    (29, "License renewal for PDF editor", "Expires at month end.", "open", "medium", "Priya"),
    (30, "Guest wifi password rotation", "Rotated for the quarter.", "closed", "low", "Dana"),
]
# id, ticket_id, author, body
_C = [
    (1, 2, "Sam", "Also affects the Leeds office."),
    (2, 23, "Priya", "Tried deleting old messages, no luck."),
    (3, 13, "Dana", "Archive folder could be moved."),
]


def _seed_time(i: int) -> str:
    # Fixed, strictly increasing timestamps: ticket i was created on day i of October 2026.
    return f"2026-10-{i:02d}T09:00:00+00:00"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def reset_db(db_path: Path | str) -> None:
    """Rebuild the database from the seed. Deterministic: same rows every time."""
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO users(id, name) VALUES (?,?)", list(enumerate(USERS, 1)))
    con.executemany(
        "INSERT INTO tickets(id,title,description,status,priority,assignee,due_date,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,NULL,?,?)",
        [(*t, _seed_time(t[0]), _seed_time(t[0])) for t in _T],
    )
    con.executemany(
        "INSERT INTO comments(id,ticket_id,author,body,created_at) VALUES (?,?,?,?,?)",
        [(*c, _seed_time(c[0] + 20)) for c in _C],
    )
    con.commit()
    con.close()


def snapshot(db_path: Path | str) -> dict[str, dict[int, dict]]:
    """Every row of every table, keyed by table then primary key. Read straight from the file."""
    con = connect(db_path)
    out = {}
    for table in ("users", "tickets", "comments"):
        out[table] = {r["id"]: dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY id")}
    con.close()
    return out


def state_hash(snap: dict) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- operations


def validate_ticket(fields: dict, *, partial: bool) -> dict[str, str]:
    """Return {field: message} for every invalid field. Empty dict means valid."""
    errors: dict[str, str] = {}
    if not partial or "title" in fields:
        title = (fields.get("title") or "").strip()
        if not title:
            errors["title"] = "Title is required."
        elif len(title) > TITLE_MAX:
            errors["title"] = f"Title is too long ({len(title)} characters, the limit is {TITLE_MAX})."
    if fields.get("status") is not None and fields["status"] not in STATUSES:
        errors["status"] = f"Status must be one of: {', '.join(STATUSES)}."
    if fields.get("priority") is not None and fields["priority"] not in PRIORITIES:
        errors["priority"] = f"Priority must be one of: {', '.join(PRIORITIES)}."
    if fields.get("assignee") not in (None, "") and fields["assignee"] not in USERS:
        errors["assignee"] = f"Assignee must be one of: {', '.join(USERS)}."
    due = fields.get("due_date")
    if due not in (None, ""):
        try:
            datetime.strptime(due, "%Y-%m-%d")
        except (ValueError, TypeError):
            errors["due_date"] = "Due date must look like 2026-12-31."
    return errors


EDITABLE = ("title", "description", "status", "priority", "assignee", "due_date")


def _clean(fields: dict) -> dict:
    out = {}
    for k in EDITABLE:
        if k in fields:
            v = fields[k]
            if isinstance(v, str):
                v = v.strip()
            if k in ("assignee", "due_date") and v == "":
                v = None
            out[k] = v
    return out


def get_ticket(con, tid: int, with_comments: bool = True) -> dict | None:
    row = con.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if row is None:
        return None
    t = dict(row)
    if with_comments:
        t["comments"] = [
            dict(c) for c in con.execute("SELECT * FROM comments WHERE ticket_id=? ORDER BY id", (tid,))
        ]
    return t


def search_tickets(con, q="", status="", assignee="", priority="") -> list[dict]:
    """Text search matches the title or the description, case-insensitively."""
    sql, args = "SELECT * FROM tickets WHERE 1=1", []
    if q:
        sql += " AND (title LIKE ? OR description LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    for col, val in (("status", status), ("assignee", assignee), ("priority", priority)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    return [dict(r) for r in con.execute(sql + " ORDER BY id", args)]


def create_ticket(con, fields: dict) -> tuple[dict | None, dict]:
    f = _clean(fields)
    errors = validate_ticket(f, partial=False)
    if errors:
        return None, errors
    ts = now_iso()
    cur = con.execute(
        "INSERT INTO tickets(title,description,status,priority,assignee,due_date,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (f["title"], f.get("description") or "", f.get("status") or "open",
         f.get("priority") or "medium", f.get("assignee"), f.get("due_date"), ts, ts),
    )
    con.commit()
    return get_ticket(con, cur.lastrowid), {}


def update_ticket(con, tid: int, fields: dict) -> tuple[dict | None, dict]:
    if get_ticket(con, tid, with_comments=False) is None:
        return None, {"id": "No such ticket."}
    f = _clean(fields)
    if not f:
        return None, {"fields": "Nothing to update."}
    errors = validate_ticket(f, partial=True)
    if errors:
        return None, errors
    if "description" in f and f["description"] is None:
        f["description"] = ""
    sets = ", ".join(f"{k}=?" for k in f)
    con.execute(f"UPDATE tickets SET {sets}, updated_at=? WHERE id=?", (*f.values(), now_iso(), tid))
    con.commit()
    return get_ticket(con, tid), {}


def delete_ticket(con, tid: int) -> bool:
    if get_ticket(con, tid, with_comments=False) is None:
        return False
    con.execute("DELETE FROM comments WHERE ticket_id=?", (tid,))
    con.execute("DELETE FROM tickets WHERE id=?", (tid,))
    con.commit()
    return True


def add_comment(con, tid: int, body: str) -> tuple[dict | None, dict]:
    if get_ticket(con, tid, with_comments=False) is None:
        return None, {"id": "No such ticket."}
    body = (body or "").strip()
    if not body:
        return None, {"body": "Comment cannot be empty."}
    cur = con.execute(
        "INSERT INTO comments(ticket_id,author,body,created_at) VALUES (?,?,?,?)",
        (tid, COMMENT_AUTHOR, body, now_iso()),
    )
    con.commit()
    return dict(con.execute("SELECT * FROM comments WHERE id=?", (cur.lastrowid,)).fetchone()), {}
