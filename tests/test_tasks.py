import pytest

from bakeoff.tasks import BY_ID, PILOT_TASKS, TASKS, select


def test_task_set_shape():
    assert 12 <= len(TASKS) <= 15
    assert len(BY_ID) == len(TASKS)
    cats = {t.category for t in TASKS}
    assert {"form", "edit", "multi_step", "search", "delete", "infeasible"} <= cats


def test_every_feasible_task_expects_a_change_and_has_solutions():
    for t in TASKS:
        assert t.ui and t.api, t.id
        if t.feasible:
            assert t.updates or t.inserts or t.deletes, t.id
        else:
            assert not (t.updates or t.inserts or t.deletes)


def test_select():
    assert set(PILOT_TASKS) <= set(BY_ID)
    assert [t.id for t in select(["escalate"])] == ["escalate"]
    assert len(select(None)) == len(TASKS)
    with pytest.raises(KeyError):
        select(["nope"])
