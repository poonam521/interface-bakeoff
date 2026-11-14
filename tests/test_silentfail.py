import pytest

from bakeoff.interfaces.api import ToolLayer
from silentfail import Detector, FaultInjector, claim_check
from silentfail.score import score


def _pair(app, fault):
    layer = ToolLayer(app.base_url)
    inj = FaultInjector(layer, rate=1.0, seed=3, faults=(fault,))
    det = Detector(probe=lambda n, a: layer.call(n, a, probe=True))
    return layer, inj, det


def test_clean_results_are_not_flagged(app):
    layer = ToolLayer(app.base_url)
    det = Detector(probe=lambda n, a: layer.call(n, a, probe=True))
    for name, args in [("search_tickets", {"q": "vpn", "status": "open"}), ("get_ticket", {"id": 2}),
                       ("update_ticket", {"id": 2, "status": "closed"}), ("get_ticket", {"id": 2})]:
        assert det.check(name, args, layer.call(name, args)) == []


def test_errors_are_not_silent_failures(app):
    assert Detector().check("get_ticket", {"id": 999}, {"error": "No such ticket."}) == []


def test_phantom_write_needs_a_cross_check(app):
    layer, inj, det = _pair(app, "phantom_write")
    res = inj.call("update_ticket", {"id": 1, "status": "closed"})
    assert res["status"] == "closed" and inj.log[-1]["fault"] == "phantom_write"
    assert layer.call("get_ticket", {"id": 1})["status"] == "open"   # nothing was written
    assert Detector().check("update_ticket", {"id": 1, "status": "closed"}, res) == []   # tier 1 is blind
    rules = {f.rule for f in det.check("update_ticket", {"id": 1, "status": "closed"}, res)}
    assert "readback_differs" in rules


def test_truncated_list_keeps_a_consistent_total(app):
    _layer, inj, det = _pair(app, "truncated_list")
    res = inj.call("search_tickets", {"q": "vpn"})
    assert res["total"] == len(res["tickets"]) < 5
    assert {f.rule for f in det.check("search_tickets", {"q": "vpn"}, res)} == {"result_set_differs"}


def test_count_mismatch_caught_by_invariant(app):
    _layer, inj, _det = _pair(app, "count_mismatch")
    res = inj.call("search_tickets", {"status": "closed"})
    assert any(f.rule == "count_mismatch" and f.tier == 1 for f in Detector().check("search_tickets", {}, res))


def test_stale_read_caught_by_timestamp_invariant(app):
    layer, inj, _det = _pair(app, "stale_read")
    det = Detector()
    args = {"id": 4, "priority": "high"}
    det.check("update_ticket", args, inj.call("update_ticket", args))
    stale = inj.call("get_ticket", {"id": 4})
    assert inj.log[-1]["fault"] == "stale_read" and stale["priority"] == "low"
    assert any(f.rule == "time_went_backwards" for f in det.check("get_ticket", {"id": 4}, stale))


def test_wrong_record_and_field_corrupt(app):
    for fault in ("wrong_record", "field_corrupt"):
        _layer, inj, det = _pair(app, fault)
        res = inj.call("get_ticket", {"id": 5})
        assert res["id"] == 5 and inj.log[-1]["fault"] == fault
        assert any(f.tier == 2 for f in det.check("get_ticket", {"id": 5}, res))


def test_probes_are_never_faulted(app):
    _layer, inj, _det = _pair(app, "field_corrupt")
    inj.call("get_ticket", {"id": 5}, probe=True)
    assert inj.log == []


def test_claim_check():
    assert claim_check("done", False) and not claim_check("done", True)
    assert not claim_check("impossible", False) and not claim_check(None, False)


def test_score_small():
    res = score(seeds=2, rate=0.5)
    t12 = res["tier1_plus_crosschecks"]
    assert t12["injected"] > 0 and t12["recall"] >= res["tier1_invariants"]["recall"]
    assert res["clean_traces"]["flagged_tier1_plus_2"] == 0
    assert 0 <= t12["precision"] <= 1


def test_injection_rate_zero_changes_nothing(app):
    layer = ToolLayer(app.base_url)
    inj = FaultInjector(layer, rate=0.0, seed=1)
    assert inj.call("search_tickets", {"q": "vpn"}) == layer.call("search_tickets", {"q": "vpn"})
    assert all(e["fault"] is None for e in inj.log)


@pytest.mark.parametrize("bad", [{"status": "weird"}, {"assignee": "Zed"}])
def test_schema_invariants(bad):
    t = {"id": 1, "title": "x", "description": "", "status": "open", "priority": "low", "assignee": None,
         "due_date": None, "created_at": "a", "updated_at": "b", "comments": [], **bad}
    assert any(f.rule == "enum" for f in Detector().check("get_ticket", {"id": 1}, t))
