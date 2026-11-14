"""silentfail: tools that return well-formed but wrong data, and agents that claim success the
app state does not support.

- injector.FaultInjector  wraps the typed tool layer and returns plausible wrong results
- detector.Detector       flags suspicious results with invariants (tier 1) and cross-checks (tier 2)
- score.score             runs both over scripted traces and reports precision and recall
- claim_check             the success-claim versus database-state check used by the harness
"""
from .detector import Detector, Finding
from .injector import FAULTS, FaultInjector


def claim_check(claim: str | None, state_passed: bool) -> bool:
    """True when the agent claimed the task was done but the database says it was not."""
    return claim == "done" and not state_passed


__all__ = ["FAULTS", "Detector", "FaultInjector", "Finding", "claim_check"]
