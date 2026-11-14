"""Proof-of-concept demo app: a tiny ticket tracker on Flask + SQLite.

Generic demo code written for this project. It has seeded data, a reset
endpoint, one HTML page and a small JSON API.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, g, jsonify, render_template_string, request

SEED = [
    # id, title, status, assignee, priority
    (1, "Printer on floor 2 is jammed", "open", None, "low"),
    (2, "VPN drops every hour", "open", "Sam", "high"),
    (3, "New starter needs a laptop", "in_progress", "Dana", "medium"),
    (4, "Projector bulb is dead", "open", None, "low"),
    (5, "Password reset for finance kiosk", "closed", "Sam", "medium"),
]
STATUSES = ("open", "in_progress", "closed")

PAGE = """<!doctype html><title>Tickets</title><h1>Tickets</h1>
<table border=1><tr><th>ID<th>Title<th>Status<th>Assignee<th>Priority</tr>
{% for t in tickets %}<tr><td>{{t.id}}<td>{{t.title}}<td>{{t.status}}
<td>{{t.assignee or '-'}}<td>{{t.priority}}</tr>{% endfor %}</table>"""


def reset_db(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.executescript(
        """DROP TABLE IF EXISTS tickets;
        CREATE TABLE tickets (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
            assignee TEXT, priority TEXT NOT NULL);"""
    )
    con.executemany("INSERT INTO tickets VALUES (?,?,?,?,?)", SEED)
    con.commit()
    con.close()


def create_app(db_path: Path) -> Flask:
    app = Flask(__name__)

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close(_exc):
        con = g.pop("db", None)
        if con is not None:
            con.close()

    @app.post("/reset")
    def reset():
        reset_db(db_path)
        return jsonify(ok=True)

    @app.get("/")
    def index():
        rows = db().execute("SELECT * FROM tickets ORDER BY id").fetchall()
        return render_template_string(PAGE, tickets=rows)

    @app.get("/api/tickets")
    def list_tickets():
        rows = db().execute("SELECT * FROM tickets ORDER BY id").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/tickets/<int:tid>")
    def get_ticket(tid: int):
        row = db().execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
        return (jsonify(dict(row)), 200) if row else (jsonify(error="not found"), 404)

    @app.patch("/api/tickets/<int:tid>")
    def update_ticket(tid: int):
        body = request.get_json(force=True)
        allowed = {k: body[k] for k in ("status", "assignee", "priority") if k in body}
        if "status" in allowed and allowed["status"] not in STATUSES:
            return jsonify(error=f"status must be one of {STATUSES}"), 400
        if not allowed:
            return jsonify(error="nothing to update"), 400
        sets = ", ".join(f"{k}=?" for k in allowed)
        cur = db().execute(f"UPDATE tickets SET {sets} WHERE id=?", (*allowed.values(), tid))
        db().commit()
        if cur.rowcount == 0:
            return jsonify(error="not found"), 404
        return get_ticket(tid)

    return app
