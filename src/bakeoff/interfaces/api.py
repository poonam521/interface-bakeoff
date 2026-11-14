"""Typed tool layer over the app's JSON API. The agent never sees a page."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from ..app.db import PRIORITIES, STATUSES, USERS
from ..types import Observation
from .base import tool

_FIELDS = {
    "title": {"type": "string"},
    "description": {"type": "string"},
    "status": {"type": "string", "enum": list(STATUSES)},
    "priority": {"type": "string", "enum": list(PRIORITIES)},
    "assignee": {"type": "string", "description": f"One of {', '.join(USERS)}, or an empty string for unassigned."},
    "due_date": {"type": "string", "description": "YYYY-MM-DD"},
}
_ID = {"id": {"type": "integer", "description": "Ticket id"}}

TOOLS = [
    tool("list_users", "List the names of people a ticket can be assigned to.", {}, []),
    tool("search_tickets",
         "Search tickets. All filters are optional and combine with AND. `q` matches text in the "
         "title or the description. Returns {total, tickets}.",
         {"q": {"type": "string"}, "status": _FIELDS["status"], "assignee": {"type": "string"},
          "priority": _FIELDS["priority"]}, []),
    tool("get_ticket", "Get one ticket with its comments.", _ID, ["id"]),
    tool("create_ticket", "Create a ticket. Only the title is required.", _FIELDS, ["title"]),
    tool("update_ticket", "Change fields of one ticket. Send only the fields to change.",
         {**_ID, **_FIELDS}, ["id"]),
    tool("delete_ticket", "Delete one ticket and its comments.", _ID, ["id"]),
    tool("add_comment", "Add a comment to a ticket.", {**_ID, "body": {"type": "string"}}, ["id", "body"]),
]
TOOL_NAMES = {t["name"] for t in TOOLS}


class ToolLayer:
    """Executes a tool call against the app and returns the parsed JSON result.

    `probe=True` marks a call made by a checker rather than by the agent; this layer ignores it,
    wrappers (the silentfail injector) may record it.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _http(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except json.JSONDecodeError:
                return {"error": f"HTTP {e.code}"}

    def call(self, name: str, args: dict, probe: bool = False) -> dict:
        a = dict(args or {})
        try:
            if name == "list_users":
                return self._http("GET", "/api/users")
            if name == "search_tickets":
                qs = urllib.parse.urlencode({k: v for k, v in a.items() if v not in (None, "")})
                return self._http("GET", "/api/tickets" + (f"?{qs}" if qs else ""))
            if name not in TOOL_NAMES:
                return {"error": f"Unknown tool: {name}"}
            tid = a.pop("id", None)
            if not isinstance(tid, int) or isinstance(tid, bool):
                return {"error": "id must be an integer"} if name != "create_ticket" else self._http(
                    "POST", "/api/tickets", a)
            if name == "create_ticket":
                return self._http("POST", "/api/tickets", a)
            if name == "get_ticket":
                return self._http("GET", f"/api/tickets/{tid}")
            if name == "update_ticket":
                return self._http("PATCH", f"/api/tickets/{tid}", a)
            if name == "delete_ticket":
                return self._http("DELETE", f"/api/tickets/{tid}")
            return self._http("POST", f"/api/tickets/{tid}/comments", {"body": a.get("body", "")})
        except (urllib.error.URLError, TimeoutError) as e:
            return {"error": f"request failed: {e}"}


class ApiInterface:
    name = "api"
    guidance = (
        "You work through function tools that read and change the ticket tracker directly. "
        "You cannot see any page. Tool results are JSON."
    )

    def __init__(self, layer):
        self.layer = layer   # a ToolLayer, or anything with the same call() method

    def tools(self) -> list[dict]:
        return TOOLS

    def start(self) -> Observation:
        return Observation(summary="Ready. No tool has been called yet.")

    def act(self, name: str, args: dict) -> Observation:
        result = self.layer.call(name, args)
        return Observation(summary=json.dumps(result, ensure_ascii=False),
                           is_error=isinstance(result, dict) and "error" in result)

    def close(self) -> None:
        pass
