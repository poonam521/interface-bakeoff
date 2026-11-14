import json

from bakeoff.app import snapshot
from bakeoff.interfaces import make_interface
from bakeoff.interfaces.api import ToolLayer


def test_tool_layer(app):
    layer = ToolLayer(app.base_url)
    assert layer.call("search_tickets", {"assignee": "Lee", "status": "open"})["total"] == 4
    assert layer.call("get_ticket", {"id": 2})["comments"][0]["body"].startswith("Also")
    assert layer.call("update_ticket", {"id": 4, "assignee": ""})["assignee"] is None
    assert "error" in layer.call("get_ticket", {"id": "4"})
    assert "error" in layer.call("nope", {})
    assert layer.call("add_comment", {"id": 1, "body": "hi"})["author"] == "agent"
    assert layer.call("delete_ticket", {"id": 1}) == {"deleted": 1}


def test_api_interface_returns_json_summary(app):
    iface = make_interface("api", app.base_url)
    obs = iface.act("get_ticket", {"id": 999})
    assert obs.is_error and json.loads(obs.summary)["error"]
    assert {t["name"] for t in iface.tools()} >= {"search_tickets", "update_ticket", "delete_ticket"}


def test_a11y_snapshot_and_actions(app, browser):
    iface = make_interface("a11y", app.base_url, browser)
    try:
        obs = iface.start()
        assert obs.image is None
        assert 'link "Printer on floor 2 is jammed"' in obs.view
        assert "[e" in obs.view
        ref = iface.translate(("click", 'a[href="/tickets/1"]'))[0][1]["ref"]
        obs = iface.act("click", {"ref": ref})
        assert 'heading "Ticket #1: Printer on floor 2 is jammed"' in obs.view
        radio = iface.translate(("click", 'input[name="status"][value="closed"]'))[0][1]["ref"]
        iface.act("click", {"ref": radio})
        save = iface.translate(("click", "#save-btn"))[0][1]["ref"]
        obs = iface.act("click", {"ref": save})
        assert "Changes saved" in obs.view
        assert snapshot(app.db_path)["tickets"][1]["status"] == "closed"
        assert iface.act("click", {"ref": "e9999"}).is_error
    finally:
        iface.close()


def test_screenshot_gives_only_pixels(app, browser):
    iface = make_interface("screenshot", app.base_url, browser)
    try:
        obs = iface.start()
        assert obs.image[:8] == b"\x89PNG\r\n\x1a\n" and obs.view == ""
        assert iface.act("click", {"x": 5000, "y": 5}).is_error
        calls = iface.translate(("fill", "#q", "VPN"))
        assert [c[0] for c in calls][-2:] == ["key", "type"]
        for name, args in calls + iface.translate(("click", "#search-btn")):
            iface.act(name, args)
        assert "q=VPN" in iface.page.url
    finally:
        iface.close()
