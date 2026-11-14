"""Hard spending cap across every real run made from this repo.

The running total lives in a JSON ledger that persists between runs. Before each model call the
guard adds the call's worst-case cost to the total; if that would pass the cap, the call is
refused. After the call the reserved amount is replaced by the measured cost. Several worker
processes share the ledger through a lock file.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

HARD_CAP_USD = 10.00   # can be lowered per run, never raised


class BudgetExceeded(RuntimeError):
    pass


@contextmanager
def _locked(lock_path: Path, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not lock {lock_path}") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        os.unlink(lock_path)


class BudgetGuard:
    def __init__(self, ledger_path: Path | str, cap_usd: float = HARD_CAP_USD):
        if cap_usd > HARD_CAP_USD:
            raise ValueError(f"cap ${cap_usd:.2f} is above the hard cap of ${HARD_CAP_USD:.2f}")
        self.path = Path(ledger_path)
        self.lock = self.path.with_suffix(".lock")
        self.cap = cap_usd
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"spent_usd": 0.0, "reserved_usd": 0.0, "calls": 0}

    def _write(self, d: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        os.replace(tmp, self.path)

    def spent(self) -> float:
        return self._read()["spent_usd"]

    def remaining(self) -> float:
        d = self._read()
        return self.cap - d["spent_usd"] - d["reserved_usd"]

    def reserve(self, worst_case_usd: float) -> None:
        with _locked(self.lock):
            d = self._read()
            if d["spent_usd"] + d["reserved_usd"] + worst_case_usd > self.cap:
                raise BudgetExceeded(
                    f"next call could cost up to ${worst_case_usd:.4f}; spent ${d['spent_usd']:.4f}, "
                    f"reserved ${d['reserved_usd']:.4f}, cap ${self.cap:.2f}")
            d["reserved_usd"] += worst_case_usd
            self._write(d)

    def settle(self, reserved_usd: float, actual_usd: float) -> None:
        with _locked(self.lock):
            d = self._read()
            d["reserved_usd"] = max(0.0, d["reserved_usd"] - reserved_usd)
            d["spent_usd"] += actual_usd
            d["calls"] += 1
            self._write(d)

    def clear_reservations(self) -> None:
        """Drop reservations left by a crashed worker. Spent money is never cleared."""
        with _locked(self.lock):
            d = self._read()
            d["reserved_usd"] = 0.0
            self._write(d)
