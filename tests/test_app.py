import json

from bakeoff.app import create_app, reset_db, snapshot, state_hash
from bakeoff.app.db import TITLE_MAX

from .conftest import http


def test_reset_is_deterministic(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    reset_db(a)
    reset_db(b)
    assert state_hash(snapshot(a)) == state_hash(snapshot(b))
    assert len(snapshot(a)["tickets"]) == 30


def test_reset_endpoint_restores_seed(app):
    seed = state_hash(snapshot(app.db_path))
    http("PATCH", app.base_url + "/api/tickets/1", {"status": "closed"})
    assert state_hash(snapshot(app.db_path)) != seed
    assert http("POST", app.base_url + "/__reset")[0] == 200
    assert state_hash(snapshot(app.db_path)) == seed


def test_reset_endpoint_absent_outside_harness_mode(tmp_path):
    reset_db(tmp_path / "x.db")
    client = create_app(tmp_path / "x.db").test_client()
    assert client.post("/__reset").status_code in (404, 405)


def test_search_filters_combine(app):
    code, body = http("GET", app.base_url + "/api/tickets?q=vpn&status=open")
    data = json.loads(body)
    assert code == 200
    assert {t["id"] for t in data["tickets"]} == {2, 6, 10, 11}  # 10 mentions VPN in its description
    assert data["total"] == 4


def test_create_rejects_long_title(app):
    code, body = http("POST", app.base_url + "/api/tickets", {"title": "x" * (TITLE_MAX + 1)})
    assert code == 400 and "too long" in body
    code, _ = http("POST", app.base_url + "/api/tickets", {"title": "ok"})
    assert code == 201


def test_update_validates_enums(app):
    code, body = http("PATCH", app.base_url + "/api/tickets/1", {"status": "done"})
    assert code == 400 and "Status must be" in body
    assert http("PATCH", app.base_url + "/api/tickets/999", {"status": "closed"})[0] == 404


def test_delete_removes_comments(app):
    http("DELETE", app.base_url + "/api/tickets/23")
    snap = snapshot(app.db_path)
    assert 23 not in snap["tickets"] and 2 not in snap["comments"]


def test_html_form_flow(app):
    client = create_app(app.db_path).test_client()
    r = client.post("/tickets", data={"title": "", "status": "open", "priority": "low"})
    assert r.status_code == 400 and b"Title is required" in r.data
    r = client.post("/tickets/4", data={"title": "Projector bulb is dead", "status": "closed",
                                        "priority": "low", "assignee": ""})
    assert r.status_code == 302
    assert snapshot(app.db_path)["tickets"][4]["status"] == "closed"
    assert client.get("/?q=printer").status_code == 200
    assert client.get("/tickets/23/delete").status_code == 200
