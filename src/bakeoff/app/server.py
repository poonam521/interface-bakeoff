"""Flask app: server-rendered pages for the browser interfaces and a JSON API for the tool layer."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for
from werkzeug.serving import make_server

from . import db as store

LAYOUT = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{{ title }} - Deskline</title>
<style>
body{font:16px/1.4 Arial,sans-serif;margin:0;color:#111}
header{background:#1f3a5f;color:#fff;padding:10px 20px}
header a{color:#fff;text-decoration:none;font-weight:bold;margin-right:24px}
main{padding:16px 20px;max-width:980px}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #bbb;padding:6px 8px;text-align:left}
input[type=text],textarea{font:inherit;padding:6px;width:480px;border:1px solid #666}
textarea{height:70px}
fieldset{margin:10px 0;border:1px solid #bbb}
label.opt{margin-right:18px}
button,.btn{font:inherit;padding:8px 16px;background:#1f3a5f;color:#fff;border:0;cursor:pointer;text-decoration:none;display:inline-block}
.danger{background:#a11}
.msg{background:#dfd;border:1px solid #6a6;padding:8px;margin:8px 0}
.err{background:#fdd;border:1px solid #a66;padding:8px;margin:8px 0}
.field{margin:10px 0}
</style></head><body>
<header><a href="/" id="home-link">Deskline tickets</a><a href="/tickets/new" id="new-ticket-link">New ticket</a></header>
<main>
{% if msg %}<div class="msg" role="status">{{ msg }}</div>{% endif %}
{% for e in errors %}<div class="err" role="alert">{{ e }}</div>{% endfor %}
{{ body|safe }}
</main></body></html>"""

LIST = """<h1>Tickets</h1>
<form method="get" action="/">
 <div class="field"><label for="q">Search title or description</label><br>
 <input type="text" id="q" name="q" value="{{ q }}"></div>
 <fieldset><legend>Status filter</legend>
 {% for s in ['', 'open', 'in_progress', 'closed'] %}
 <label class="opt"><input type="radio" name="status" value="{{ s }}" {% if status == s %}checked{% endif %}> {{ s or 'any' }}</label>
 {% endfor %}</fieldset>
 <button type="submit" id="search-btn">Search</button>
</form>
<p id="result-count">{{ tickets|length }} ticket(s) shown.</p>
<table><tr><th>ID</th><th>Title</th><th>Status</th><th>Priority</th><th>Assignee</th><th>Created</th></tr>
{% for t in tickets %}<tr><td>{{ t.id }}</td><td><a href="/tickets/{{ t.id }}">{{ t.title }}</a></td>
<td>{{ t.status }}</td><td>{{ t.priority }}</td><td>{{ t.assignee or 'unassigned' }}</td><td>{{ t.created_at[:10] }}</td></tr>
{% endfor %}</table>"""

FORM_FIELDS = """
 <div class="field"><label for="title">Title</label><br>
 <input type="text" id="title" name="title" value="{{ f.title or '' }}"></div>
 <div class="field"><label for="description">Description</label><br>
 <textarea id="description" name="description">{{ f.description or '' }}</textarea></div>
 <fieldset><legend>Status</legend>
 {% for s in statuses %}<label class="opt"><input type="radio" name="status" value="{{ s }}" {% if (f.status or 'open') == s %}checked{% endif %}> {{ s }}</label>{% endfor %}
 </fieldset>
 <fieldset><legend>Priority</legend>
 {% for p in priorities %}<label class="opt"><input type="radio" name="priority" value="{{ p }}" {% if (f.priority or 'medium') == p %}checked{% endif %}> {{ p }}</label>{% endfor %}
 </fieldset>
 <fieldset><legend>Assignee</legend>
 <label class="opt"><input type="radio" name="assignee" value="" {% if not f.assignee %}checked{% endif %}> unassigned</label>
 {% for u in users %}<label class="opt"><input type="radio" name="assignee" value="{{ u }}" {% if f.assignee == u %}checked{% endif %}> {{ u }}</label>{% endfor %}
 </fieldset>
 <div class="field"><label for="due_date">Due date (YYYY-MM-DD, optional)</label><br>
 <input type="text" id="due_date" name="due_date" value="{{ f.due_date or '' }}"></div>
"""

NEW = """<h1>New ticket</h1><form method="post" action="/tickets">""" + FORM_FIELDS + """
 <button type="submit" id="create-btn">Create ticket</button></form>"""

DETAIL = """<h1>Ticket #{{ t.id }}: {{ t.title }}</h1>
<p>Status: {{ t.status }}. Priority: {{ t.priority }}. Assignee: {{ t.assignee or 'unassigned' }}.
Created: {{ t.created_at[:10] }}. Due: {{ t.due_date or 'none' }}.</p>
<p id="description-text">Description: {{ t.description }}</p>
<h2>Edit</h2><form method="post" action="/tickets/{{ t.id }}">""" + FORM_FIELDS + """
 <button type="submit" id="save-btn">Save changes</button></form>
<h2>Comments</h2>
{% if not t.comments %}<p>No comments yet.</p>{% endif %}
<ul>{% for c in t.comments %}<li>{{ c.author }}: {{ c.body }}</li>{% endfor %}</ul>
<form method="post" action="/tickets/{{ t.id }}/comments">
 <div class="field"><label for="comment-body">New comment</label><br>
 <textarea id="comment-body" name="body"></textarea></div>
 <button type="submit" id="add-comment-btn">Add comment</button></form>
<p style="margin-top:30px"><a class="btn danger" id="delete-link" href="/tickets/{{ t.id }}/delete">Delete ticket</a></p>"""

CONFIRM = """<h1>Delete ticket #{{ t.id }}?</h1><p>"{{ t.title }}" and its comments will be removed. This cannot be undone.</p>
<form method="post" action="/tickets/{{ t.id }}/delete">
<button type="submit" class="danger" id="confirm-delete-btn">Yes, delete</button>
<a class="btn" id="cancel-delete-link" href="/tickets/{{ t.id }}">Cancel</a></form>"""


def create_app(db_path: Path | str, harness_mode: bool = False) -> Flask:
    app = Flask(__name__)
    ctx = dict(statuses=store.STATUSES, priorities=store.PRIORITIES, users=store.USERS)

    def con():
        if "con" not in g:
            g.con = store.connect(db_path)
        return g.con

    @app.teardown_appcontext
    def _close(_exc):
        c = g.pop("con", None)
        if c is not None:
            c.close()

    def page(title, template, errors=(), code=200, **kw):
        body = render_template_string(template, **ctx, **kw)
        html = render_template_string(LAYOUT, title=title, body=body, errors=list(errors),
                                      msg=request.args.get("msg", ""))
        return html, code

    # ------------------------------------------------------------- pages
    @app.get("/")
    def index():
        q, status = request.args.get("q", "").strip(), request.args.get("status", "")
        return page("Tickets", LIST, tickets=store.search_tickets(con(), q=q, status=status), q=q, status=status)

    @app.get("/tickets/new")
    def new_ticket():
        return page("New ticket", NEW, f={})

    @app.post("/tickets")
    def create_ticket():
        ticket, errors = store.create_ticket(con(), request.form.to_dict())
        if errors:
            return page("New ticket", NEW, errors=errors.values(), code=400, f=request.form.to_dict())
        return redirect(url_for("detail", tid=ticket["id"], msg="Ticket created."))

    @app.get("/tickets/<int:tid>")
    def detail(tid):
        t = store.get_ticket(con(), tid)
        if t is None:
            return page("Not found", "<h1>Ticket not found</h1>", code=404)
        return page(f"Ticket {tid}", DETAIL, t=t, f=t)

    @app.post("/tickets/<int:tid>")
    def edit(tid):
        t, errors = store.update_ticket(con(), tid, request.form.to_dict())
        if errors:
            current = store.get_ticket(con(), tid)
            if current is None:
                return page("Not found", "<h1>Ticket not found</h1>", code=404)
            return page(f"Ticket {tid}", DETAIL, errors=errors.values(), code=400, t=current,
                        f=request.form.to_dict())
        return redirect(url_for("detail", tid=tid, msg="Changes saved."))

    @app.post("/tickets/<int:tid>/comments")
    def comment(tid):
        _c, errors = store.add_comment(con(), tid, request.form.get("body", ""))
        if errors:
            t = store.get_ticket(con(), tid)
            if t is None:
                return page("Not found", "<h1>Ticket not found</h1>", code=404)
            return page(f"Ticket {tid}", DETAIL, errors=errors.values(), code=400, t=t, f=t)
        return redirect(url_for("detail", tid=tid, msg="Comment added."))

    @app.get("/tickets/<int:tid>/delete")
    def confirm_delete(tid):
        t = store.get_ticket(con(), tid)
        if t is None:
            return page("Not found", "<h1>Ticket not found</h1>", code=404)
        return page("Delete ticket", CONFIRM, t=t)

    @app.post("/tickets/<int:tid>/delete")
    def do_delete(tid):
        store.delete_ticket(con(), tid)
        return redirect(url_for("index", msg=f"Ticket #{tid} deleted."))

    # --------------------------------------------------------------- API
    def lean(t):  # list rows carry no comments
        return {k: v for k, v in t.items() if k != "comments"}

    @app.get("/api/users")
    def api_users():
        return jsonify(users=list(store.USERS))

    @app.get("/api/tickets")
    def api_search():
        a = request.args
        rows = store.search_tickets(con(), q=a.get("q", ""), status=a.get("status", ""),
                                    assignee=a.get("assignee", ""), priority=a.get("priority", ""))
        return jsonify(total=len(rows), tickets=[lean(r) for r in rows])

    @app.get("/api/tickets/<int:tid>")
    def api_get(tid):
        t = store.get_ticket(con(), tid)
        return (jsonify(t), 200) if t else (jsonify(error="No such ticket."), 404)

    @app.post("/api/tickets")
    def api_create():
        t, errors = store.create_ticket(con(), request.get_json(force=True, silent=True) or {})
        return (jsonify(t), 201) if t else (jsonify(error=" ".join(errors.values())), 400)

    @app.patch("/api/tickets/<int:tid>")
    def api_update(tid):
        t, errors = store.update_ticket(con(), tid, request.get_json(force=True, silent=True) or {})
        if t:
            return jsonify(t)
        return jsonify(error=" ".join(errors.values())), (404 if "id" in errors else 400)

    @app.delete("/api/tickets/<int:tid>")
    def api_delete(tid):
        if store.delete_ticket(con(), tid):
            return jsonify(deleted=tid)
        return jsonify(error="No such ticket."), 404

    @app.post("/api/tickets/<int:tid>/comments")
    def api_comment(tid):
        body = (request.get_json(force=True, silent=True) or {}).get("body", "")
        c, errors = store.add_comment(con(), tid, body)
        if c:
            return jsonify(c), 201
        return jsonify(error=" ".join(errors.values())), (404 if "id" in errors else 400)

    if harness_mode:
        @app.post("/__reset")
        def reset():
            store.reset_db(db_path)
            return jsonify(ok=True)

    return app


class AppServer:
    """Runs the app on a free local port in a background thread."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        store.reset_db(self.db_path)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._server = make_server("127.0.0.1", 0, create_app(self.db_path, harness_mode=True), threaded=True)
        self.base_url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "AppServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
