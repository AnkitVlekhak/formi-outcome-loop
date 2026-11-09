"""Deterministic crash injection for the crash-recovery test.

`hit(name)` is called at the moments where a crash is most dangerous: after the simulator has
accepted a side effect but before our store records it, or between writing state and committing it.
With CTL_CRASH_AT unset (always, outside the test) it is a dict lookup and a no-op.

    CTL_CRASH_AT=apply_posted CTL_CRASH_NTH=1 ./run.sh http://127.0.0.1:8700

kills the process with SIGKILL (no cleanup, no finally blocks, same as an OOM kill) the first time
an approved change has been applied on the simulator but not yet recorded as APPLIED in our store.
"""
from __future__ import annotations

import os
import signal
import sys

POINTS = {
    "chunk_ingested": "counters updated in memory, chunk not yet committed to the store",
    "snapshot_tmp_written": "snapshot .tmp fsynced, not yet renamed over the live snapshot",
    "approval_posted": "POST /approvals accepted, proposal still SUBMITTING in our store",
    "auto_step_put": "auto-apply PUT accepted, step not yet recorded",
    "apply_posted": "approved change applied on the simulator, not yet APPLIED in our store",
    "validation_spent": "validation run paid for, result not yet recorded",
}

_AT = os.environ.get("CTL_CRASH_AT", "")
_NTH = int(os.environ.get("CTL_CRASH_NTH", "1") or 1)
_seen = 0


def hit(name: str) -> None:
    global _seen
    if name != _AT:
        return
    _seen += 1
    if _seen >= _NTH:
        print(f"[crashpoint] SIGKILL at {name}: {POINTS.get(name, '')}", file=sys.stderr, flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
