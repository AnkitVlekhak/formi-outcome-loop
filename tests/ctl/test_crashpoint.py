import os
import signal
import subprocess
import sys

from controller import crashpoint

SNIPPET = "from controller import crashpoint\nfor _ in range(3): crashpoint.hit('apply_posted')\nprint('survived')"


def _run(env):
    return subprocess.run([sys.executable, "-c", SNIPPET], capture_output=True, text=True,
                          env={**os.environ, **env}, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def test_noop_without_env():
    crashpoint.hit("apply_posted")          # the test process itself must survive
    assert "CTL_CRASH_AT" not in os.environ


def test_kills_on_nth_hit_of_named_point():
    assert _run({"CTL_CRASH_AT": "apply_posted", "CTL_CRASH_NTH": "3"}).returncode == -signal.SIGKILL


def test_other_point_or_unreached_nth_survives():
    assert "survived" in _run({"CTL_CRASH_AT": "approval_posted"}).stdout
    assert "survived" in _run({"CTL_CRASH_AT": "apply_posted", "CTL_CRASH_NTH": "4"}).stdout
