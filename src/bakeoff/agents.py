"""Agents: the real model-backed agent, and a scripted fake agent for tests and CI."""
from __future__ import annotations

import hashlib
import json

from .budget import BudgetExceeded, BudgetGuard
from .interfaces.base import FINISH_TOOL
from .models import ChatModel, Part, cost_usd, estimate_input_tokens, worst_case_usd
from .tasks import Task
from .types import Decision, Observation, Step, ToolCall

SYSTEM = """You operate "Deskline", a small ticket tracker, on behalf of a user.

{guidance}

Rules:
- Carry out the user's task exactly. Change only what the task asks for.
- Call one tool per turn, then look at the result before deciding the next action.
- When the task is complete, call finish with outcome "done".
- If the task cannot be carried out as stated, change nothing and call finish with outcome "impossible".
"""


class ModelAgent:
    """Each turn sends: the task, a numbered log of past actions with their results, and the
    current view (snapshot text or screenshot). Stateless per request by design."""

    def __init__(self, model: ChatModel, budget: BudgetGuard):
        self.model, self.budget = model, budget

    def begin(self, task: Task, iface, obs: Observation, run_index: int = 0) -> None:
        self.task, self.iface, self.obs = task, iface, obs
        self.system = SYSTEM.format(guidance=iface.guidance)
        self.tools = [*iface.tools(), FINISH_TOOL]
        self.log: list[str] = []

    def observe(self, call: ToolCall, obs: Observation) -> None:
        mark = " [error]" if obs.is_error else ""
        self.log.append(f"{len(self.log) + 1}. {call.name} {json.dumps(call.args, ensure_ascii=False)}"
                        f" -> {obs.summary}{mark}")
        self.obs = obs

    def _content(self) -> list[Part]:
        history = "\n".join(self.log) if self.log else "(none yet)"
        text = f"Task: {self.task.instruction}\n\nActions so far, oldest first:\n{history}\n"
        if self.obs.view:
            text += f"\nCurrent page:\n{self.obs.view}\n"
        parts = [Part("text", text)]
        if self.obs.image:
            parts.append(Part("text", "Current screen:"))
            parts.append(Part("image", png=self.obs.image))
        parts.append(Part("text", "Choose the next action."))
        return parts

    def next(self) -> Decision:
        content = self._content()
        worst = worst_case_usd(self.model.name, estimate_input_tokens(self.system, content, self.tools),
                               self.model.max_tokens)
        try:
            self.budget.reserve(worst)
        except BudgetExceeded as e:
            return Decision(budget_stop=True, error=str(e))
        reply = None
        try:
            reply = self.model.complete(self.system, content, self.tools)
        finally:
            actual = cost_usd(self.model.name, reply.usage) if reply else 0.0
            self.budget.settle(worst, actual)
        return Decision(calls=reply.calls, usage=reply.usage, cost_usd=actual, text=reply.text,
                        error=reply.error)


def _unit(*parts) -> float:
    """Deterministic number in [0, 1) from the given values."""
    h = hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0x100000000


_CLUMSY_UI = [("click", "#home-link"), ("click", 'a[href="/tickets/30"]'),
              ("click", 'input[name="priority"][value="urgent"]'), ("click", "#save-btn")]
_CLUMSY_API = [("update_ticket", {"id": 30, "priority": "urgent"})]


class FakeAgent:
    """Replays a task's reference solution. No model, no cost, fully deterministic.

    modes:
      perfect  follow the reference solution, then claim the right outcome
      liar     claim "done" immediately without doing anything
      clumsy   follow the solution, then also change ticket 30 (collateral damage)
      flaky    like perfect, but in a seeded share of runs (`fail_rate`) claim "done" and stop
    """

    MODES = ("perfect", "liar", "clumsy", "flaky")

    def __init__(self, mode: str = "perfect", fail_rate: float = 0.3, seed: int = 0):
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}")
        self.mode, self.fail_rate, self.seed = mode, fail_rate, seed

    def begin(self, task: Task, iface, obs: Observation, run_index: int = 0) -> None:
        self.task, self.iface = task, iface
        ui = iface.name != "api"
        steps = list(task.ui if ui else task.api)
        if self.mode == "clumsy":
            steps += _CLUMSY_UI if ui else _CLUMSY_API
        lazy = self.mode == "liar" or (
            self.mode == "flaky" and _unit(self.seed, task.id, iface.name, run_index) < self.fail_rate)
        self.queue = [] if lazy else steps
        self.claim = "done" if (lazy or task.feasible) else "impossible"

    def observe(self, call: ToolCall, obs: Observation) -> None:
        pass

    def next(self) -> Decision:
        if not self.queue:
            return Decision(calls=[ToolCall("fin", "finish", {"outcome": self.claim})])
        step = self.queue.pop(0)
        if self.iface.name == "api":
            calls = [step]
        else:
            calls = self.iface.translate(step)
        return Decision(calls=[ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(calls)])


def is_finish(call: ToolCall) -> bool:
    return call.name == "finish"


__all__ = ["FakeAgent", "ModelAgent", "Step", "is_finish"]
