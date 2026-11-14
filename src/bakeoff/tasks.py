"""The task set.

Each task states the exact change the database should show when the task is done:
`updates`, `inserts` and `deletes`. Anything else that differs from the seed is collateral
damage. `ui` and `api` are reference solutions used only by the scripted fake agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Key = tuple[str, int]  # (table, primary key)


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    instruction: str
    updates: dict[Key, dict[str, Any]] = field(default_factory=dict)
    inserts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    deletes: list[Key] = field(default_factory=list)
    feasible: bool = True
    ui: list[tuple] = field(default_factory=list)
    api: list[tuple[str, dict]] = field(default_factory=list)


# ---- helpers for writing UI reference solutions (CSS selectors in the demo app)
def _open(tid: int) -> tuple:
    return ("click", f'a[href="/tickets/{tid}"]')


def _radio(name: str, value: str) -> tuple:
    return ("click", f'input[name="{name}"][value="{value}"]')


_SAVE = ("click", "#save-btn")
_HOME = ("click", "#home-link")
_NEW = ("click", "#new-ticket-link")
_CREATE = ("click", "#create-btn")


def _comment(text: str) -> list[tuple]:
    return [("fill", "#comment-body", text), ("click", "#add-comment-btn")]


LONG_TITLE = "Quarterly disaster recovery backup restore test for all production file servers"
SHORT_TITLE = "Quarterly backup restore test"
KEY_NOTE = "Key was last signed out by facilities on 3 March."
_DEFAULTS = {"status": "open", "priority": "medium", "assignee": None, "description": "", "due_date": None}

TASKS: list[Task] = [
    Task(
        id="create_basic", category="form",
        instruction="Create a new ticket titled 'Coffee machine leaks water'. Leave every other field at its default.",
        inserts=[("tickets", {"title": "Coffee machine leaks water", **_DEFAULTS})],
        ui=[_NEW, ("fill", "#title", "Coffee machine leaks water"), _CREATE],
        api=[("create_ticket", {"title": "Coffee machine leaks water"})],
    ),
    Task(
        id="create_full", category="form",
        instruction=("Create a new ticket with title 'Order ergonomic chair', description "
                     "'For desk 22, mesh back.', priority high, assignee Priya and due date 2026-12-01."),
        inserts=[("tickets", {"title": "Order ergonomic chair", "description": "For desk 22, mesh back.",
                              "status": "open", "priority": "high", "assignee": "Priya",
                              "due_date": "2026-12-01"})],
        ui=[_NEW, ("fill", "#title", "Order ergonomic chair"),
            ("fill", "#description", "For desk 22, mesh back."), _radio("priority", "high"),
            _radio("assignee", "Priya"), ("fill", "#due_date", "2026-12-01"), _CREATE],
        api=[("create_ticket", {"title": "Order ergonomic chair", "description": "For desk 22, mesh back.",
                                "priority": "high", "assignee": "Priya", "due_date": "2026-12-01"})],
    ),
    Task(
        id="create_after_validation", category="form",
        instruction=(f"Create a new ticket titled '{LONG_TITLE}'. If the app refuses that title because "
                     f"it is too long, use the title '{SHORT_TITLE}' instead. Leave every other field "
                     "at its default."),
        inserts=[("tickets", {"title": SHORT_TITLE, **_DEFAULTS})],
        ui=[_NEW, ("fill", "#title", LONG_TITLE), _CREATE, ("fill", "#title", SHORT_TITLE), _CREATE],
        api=[("create_ticket", {"title": LONG_TITLE}), ("create_ticket", {"title": SHORT_TITLE})],
    ),
    Task(
        id="close_by_title", category="edit",
        instruction="Close the ticket titled 'Printer on floor 2 is jammed' (set its status to closed).",
        updates={("tickets", 1): {"status": "closed"}},
        ui=[_open(1), _radio("status", "closed"), _SAVE],
        api=[("search_tickets", {"q": "Printer on floor 2"}), ("update_ticket", {"id": 1, "status": "closed"})],
    ),
    Task(
        id="reassign_and_prioritise", category="edit",
        instruction="On the ticket titled 'Projector bulb is dead', set the assignee to Priya and the priority to high.",
        updates={("tickets", 4): {"assignee": "Priya", "priority": "high"}},
        ui=[_open(4), _radio("assignee", "Priya"), _radio("priority", "high"), _SAVE],
        api=[("search_tickets", {"q": "Projector bulb"}),
             ("update_ticket", {"id": 4, "assignee": "Priya", "priority": "high"})],
    ),
    Task(
        id="fix_title_typo", category="edit",
        instruction=("The ticket titled 'Email signiture is wrong' has a spelling mistake. "
                     "Change its title to 'Email signature is wrong'."),
        updates={("tickets", 7): {"title": "Email signature is wrong"}},
        ui=[_open(7), ("fill", "#title", "Email signature is wrong"), _SAVE],
        api=[("search_tickets", {"q": "signiture"}),
             ("update_ticket", {"id": 7, "title": "Email signature is wrong"})],
    ),
    Task(
        id="add_comment", category="multi_step",
        instruction="Add the comment 'Licence key sent by email.' to the ticket titled 'Install design software for Priya'.",
        inserts=[("comments", {"ticket_id": 17, "body": "Licence key sent by email."})],
        ui=[_open(17), *_comment("Licence key sent by email.")],
        api=[("search_tickets", {"q": "Install design software"}),
             ("add_comment", {"id": 17, "body": "Licence key sent by email."})],
    ),
    Task(
        id="escalate", category="multi_step",
        instruction=("Escalate the ticket titled 'Standing desk motor stuck': set its priority to urgent, "
                     "assign it to Sam, and add the comment 'Escalated'."),
        updates={("tickets", 24): {"priority": "urgent", "assignee": "Sam"}},
        inserts=[("comments", {"ticket_id": 24, "body": "Escalated"})],
        ui=[_open(24), _radio("priority", "urgent"), _radio("assignee", "Sam"), _SAVE, *_comment("Escalated")],
        api=[("search_tickets", {"q": "Standing desk"}),
             ("update_ticket", {"id": 24, "priority": "urgent", "assignee": "Sam"}),
             ("add_comment", {"id": 24, "body": "Escalated"})],
    ),
    Task(
        id="move_note_and_close", category="multi_step",
        instruction=("Copy the description of the ticket titled 'Old server room key is missing' into a new "
                     "comment on the ticket titled 'Audit of server room access'. The comment must be exactly "
                     "that description text. Then close the ticket titled 'Old server room key is missing'."),
        updates={("tickets", 25): {"status": "closed"}},
        inserts=[("comments", {"ticket_id": 26, "body": KEY_NOTE})],
        ui=[_open(26), *_comment(KEY_NOTE), _HOME, _open(25), _radio("status", "closed"), _SAVE],
        api=[("get_ticket", {"id": 25}), ("add_comment", {"id": 26, "body": KEY_NOTE}),
             ("update_ticket", {"id": 25, "status": "closed"})],
    ),
    Task(
        id="bulk_reassign", category="multi_step",
        instruction=("Reassign to Dana every ticket that is assigned to Lee and has status open. "
                     "Do not change Lee's tickets that are in progress or closed."),
        updates={("tickets", i): {"assignee": "Dana"} for i in (6, 10, 12, 18)},
        ui=[s for i in (6, 10, 12, 18) for s in (_open(i), _radio("assignee", "Dana"), _SAVE, _HOME)],
        api=[("search_tickets", {"assignee": "Lee", "status": "open"}),
             *[("update_ticket", {"id": i, "assignee": "Dana"}) for i in (6, 10, 12, 18)]],
    ),
    Task(
        id="search_close_matching", category="search",
        instruction=("Close every ticket that has status open and whose title contains 'VPN'. "
                     "Do not change any other ticket."),
        updates={("tickets", i): {"status": "closed"} for i in (2, 6, 11)},
        ui=[("fill", "#q", "VPN"), ("click", "#search-btn"),
            *[s for i in (2, 6, 11) for s in (_open(i), _radio("status", "closed"), _SAVE, _HOME)]],
        api=[("search_tickets", {"q": "VPN", "status": "open"}),
             *[("update_ticket", {"id": i, "status": "closed"}) for i in (2, 6, 11)]],
    ),
    Task(
        id="search_count_to_comment", category="search",
        instruction=("Count the tickets that are assigned to Sam, have status open and have priority high. "
                     "Then add a comment containing only that number, in digits, to the ticket titled "
                     "'Onboarding checklist for interns'."),
        inserts=[("comments", {"ticket_id": 20, "body": "3"})],
        ui=[_open(20), *_comment("3")],
        api=[("search_tickets", {"assignee": "Sam", "status": "open", "priority": "high"}),
             ("add_comment", {"id": 20, "body": "3"})],
    ),
    Task(
        id="delete_by_title", category="delete",
        instruction="Delete the ticket titled 'Desk phone voicemail is full'.",
        deletes=[("tickets", 23), ("comments", 2)],
        ui=[_open(23), ("click", "#delete-link"), ("click", "#confirm-delete-btn")],
        api=[("search_tickets", {"q": "voicemail"}), ("delete_ticket", {"id": 23})],
    ),
    Task(
        id="delete_newer_duplicate", category="delete",
        instruction=("Two tickets are both titled 'Replace toner in printer 3'. Delete the one that was "
                     "created later and keep the older one."),
        deletes=[("tickets", 27)],
        ui=[_open(27), ("click", "#delete-link"), ("click", "#confirm-delete-btn")],
        api=[("search_tickets", {"q": "Replace toner"}), ("delete_ticket", {"id": 27})],
    ),
    Task(
        id="close_missing_ticket", category="infeasible", feasible=False,
        instruction="Close the ticket titled 'Fax machine out of paper' (set its status to closed).",
        ui=[("fill", "#q", "Fax machine"), ("click", "#search-btn")],
        api=[("search_tickets", {"q": "Fax machine"})],
    ),
]

BY_ID = {t.id: t for t in TASKS}
# Three heavier tasks used to estimate cost before committing to a full real run.
PILOT_TASKS = ("create_full", "bulk_reassign", "search_close_matching")


def select(ids: list[str] | None) -> list[Task]:
    if not ids:
        return list(TASKS)
    unknown = [i for i in ids if i not in BY_ID]
    if unknown:
        raise KeyError(f"unknown task id(s): {', '.join(unknown)}")
    return [BY_ID[i] for i in ids]
