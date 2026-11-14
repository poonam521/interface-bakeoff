from bakeoff.agents import FakeAgent, ModelAgent
from bakeoff.budget import BudgetGuard
from bakeoff.interfaces.api import ApiInterface
from bakeoff.models import ModelReply
from bakeoff.tasks import BY_ID
from bakeoff.types import Observation, ToolCall, Usage


class StubModel:
    name, max_tokens = "claude-haiku-5-5", 4000

    def __init__(self):
        self.seen = []

    def complete(self, system, content, tools):
        self.seen.append((system, content, tools))
        return ModelReply(calls=[ToolCall("1", "finish", {"outcome": "done"})],
                          usage=Usage(input_tokens=1000, output_tokens=100))


def _api_iface():
    return ApiInterface(layer=None)


def test_model_agent_builds_stateless_turns(tmp_path):
    model = StubModel()
    agent = ModelAgent(model, BudgetGuard(tmp_path / "l.json", 1.0))
    agent.begin(BY_ID["close_by_title"], _api_iface(), Observation("Ready."))
    agent.observe(ToolCall("a", "search_tickets", {"q": "Printer"}), Observation('{"total": 1}'))
    d = agent.next()
    system, content, tools = model.seen[0]
    text = content[0].text
    assert "Printer on floor 2" in text and '1. search_tickets {"q": "Printer"} -> {"total": 1}' in text
    assert tools[-1]["name"] == "finish"
    assert d.cost_usd > 0
    assert BudgetGuard(tmp_path / "l.json", 1.0).spent() == d.cost_usd


def test_model_agent_stops_at_budget(tmp_path):
    model = StubModel()
    agent = ModelAgent(model, BudgetGuard(tmp_path / "l.json", 0.0001))
    agent.begin(BY_ID["close_by_title"], _api_iface(), Observation("Ready."))
    d = agent.next()
    assert d.budget_stop and not model.seen   # refused before any call was made


def test_fake_agent_modes():
    task, infeasible = BY_ID["escalate"], BY_ID["close_missing_ticket"]
    a = FakeAgent("perfect")
    a.begin(task, _api_iface(), None)
    names = []
    while True:
        d = a.next()
        names += [c.name for c in d.calls]
        if d.calls[0].name == "finish":
            break
    assert names == ["search_tickets", "update_ticket", "add_comment", "finish"]
    a.begin(infeasible, _api_iface(), None)
    a.next()
    assert a.next().calls[0].args == {"outcome": "impossible"}
    liar = FakeAgent("liar")
    liar.begin(task, _api_iface(), None)
    assert liar.next().calls[0].args == {"outcome": "done"}
    clumsy = FakeAgent("clumsy")
    clumsy.begin(task, _api_iface(), None)
    assert clumsy.queue[-1] == ("update_ticket", {"id": 30, "priority": "urgent"})


def test_flaky_is_seeded():
    runs = []
    for seed in (0, 0, 1):
        a = FakeAgent("flaky", fail_rate=0.5, seed=seed)
        lazy = []
        for r in range(20):
            a.begin(BY_ID["escalate"], _api_iface(), None, run_index=r)
            lazy.append(not a.queue)
        runs.append(lazy)
    assert runs[0] == runs[1] and runs[0] != runs[2]
    assert 0 < sum(runs[0]) < 20
