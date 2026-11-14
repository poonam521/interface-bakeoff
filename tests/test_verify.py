import copy

import pytest

from bakeoff.app import reset_db, snapshot
from bakeoff.tasks import BY_ID
from bakeoff.verify import classify, diff, judge, label_step


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    p = tmp_path_factory.mktemp("s") / "seed.db"
    reset_db(p)
    return snapshot(p)


def test_diff_ignores_timestamps(seed):
    after = copy.deepcopy(seed)
    after["tickets"][1]["updated_at"] = "2027-01-01"
    assert diff(seed, after).empty


def test_pass(seed):
    after = copy.deepcopy(seed)
    after["tickets"][1]["status"] = "closed"
    v = judge(BY_ID["close_by_title"], seed, after)
    assert v.state_ok
    assert classify(BY_ID["close_by_title"], v, "done", "finish") == (True, None)


def test_state_decides_not_claim(seed):
    v = judge(BY_ID["close_by_title"], seed, seed)
    assert classify(BY_ID["close_by_title"], v, "done", "finish") == (False, "no_effect")
    after = copy.deepcopy(seed)
    after["tickets"][1]["status"] = "closed"
    v = judge(BY_ID["close_by_title"], seed, after)
    assert classify(BY_ID["close_by_title"], v, None, "no_action") == (True, None)


def test_collateral_damage(seed):
    after = copy.deepcopy(seed)
    after["tickets"][1]["status"] = "closed"
    after["tickets"][30]["priority"] = "urgent"
    v = judge(BY_ID["close_by_title"], seed, after)
    assert v.target_met and v.collateral
    assert classify(BY_ID["close_by_title"], v, "done", "finish") == (False, "collateral_damage")


def test_wrong_target(seed):
    after = copy.deepcopy(seed)
    after["tickets"][4]["status"] = "closed"
    v = judge(BY_ID["close_by_title"], seed, after)
    assert classify(BY_ID["close_by_title"], v, "done", "finish") == (False, "wrong_target")


def test_insert_matching_and_extra_insert(seed):
    t = BY_ID["add_comment"]
    after = copy.deepcopy(seed)
    after["comments"][4] = {"id": 4, "ticket_id": 17, "author": "agent", "body": "Licence key sent by email. ",
                            "created_at": "x"}
    assert judge(t, seed, after).state_ok
    after["comments"][5] = {"id": 5, "ticket_id": 17, "author": "agent", "body": "again", "created_at": "x"}
    v = judge(t, seed, after)
    assert v.target_met and v.collateral


def test_delete_expectations(seed):
    t = BY_ID["delete_newer_duplicate"]
    after = copy.deepcopy(seed)
    del after["tickets"][21]   # deleted the older one instead
    v = judge(t, seed, after)
    assert not v.target_met and v.collateral


def test_infeasible_needs_impossible_claim(seed):
    t = BY_ID["close_missing_ticket"]
    v = judge(t, seed, seed)
    assert classify(t, v, "impossible", "finish") == (True, None)
    assert classify(t, v, "done", "finish") == (False, "wrong_claim_infeasible")


def test_invalid_stops_are_not_agent_failures(seed):
    v = judge(BY_ID["close_by_title"], seed, seed)
    assert classify(BY_ID["close_by_title"], v, None, "harness_error") == (False, "harness_error")
    assert classify(BY_ID["close_by_title"], v, None, "budget_stop") == (False, "budget_stop")
    assert classify(BY_ID["close_by_title"], v, None, "step_limit") == (False, "step_limit")


def test_label_step(seed):
    t = BY_ID["close_by_title"]
    good = copy.deepcopy(seed)
    good["tickets"][1]["status"] = "closed"
    assert label_step(t, seed, seed)[0] == "no_change"
    assert label_step(t, seed, good)[0] == "in_scope"
    bad = copy.deepcopy(seed)
    bad["tickets"][2]["status"] = "closed"
    label, changes = label_step(t, seed, bad)
    assert label == "out_of_scope" and "tickets #2.status" in changes[0]
