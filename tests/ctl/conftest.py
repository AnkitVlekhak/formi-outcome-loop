import copy

import pytest
import yaml
from fastapi.testclient import TestClient

from controller.simclient import SimClient


def make_sim(tmp_path, scenario="scenarios/public_01_dev.yaml", days=3, history_days=2, mutate=None):
    """Spin up the real simulator in-process and return a SimClient bound to it."""
    from sim import server
    sc = yaml.safe_load(open(scenario))
    sc["days"], sc["history_days"] = days, history_days
    if mutate:
        mutate(sc)
    p = tmp_path / "scenario.yaml"
    p.write_text(yaml.safe_dump(sc))
    server.init_world(str(p), str(tmp_path / "run"))
    return SimClient("http://testserver", client=TestClient(server.app), backoff=0.0)


@pytest.fixture()
def sim01(tmp_path):
    return make_sim(tmp_path)
