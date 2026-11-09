import httpx
import pytest

from controller.simclient import SimClient, SimError


def _client(handler):
    return SimClient("http://sim", client=httpx.Client(base_url="http://sim", transport=httpx.MockTransport(handler)),
                     backoff=0.0)


def test_retries_5xx_then_succeeds():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    assert _client(h).get("/health") == {"ok": True} and calls["n"] == 3


def test_4xx_raises_typed_error_without_retry():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(409, json={"error": "stale_base_version", "detail": {"current_version": 4}})

    with pytest.raises(SimError) as e:
        _client(h).post("/approvals", {"x": 1})
    assert e.value.status == 409 and e.value.code == "stale_base_version" and calls["n"] == 1


def test_advance_checks_state_before_retrying():
    """A timed-out advance may have succeeded; the client must not advance twice blindly."""
    seq = {"advance": 0}

    def h(req):
        if req.url.path == "/sim/advance":
            seq["advance"] += 1
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"sim_minute": 15, "finished": False, "chunks": 1})

    r = _client(h).advance(15, expected_from=0)
    assert seq["advance"] == 1 and r["sim_minute"] == 15
