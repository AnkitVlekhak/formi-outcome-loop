"""Decision logic on synthetic data with a known truth."""
import numpy as np
import pytest

from controller import callerid, cells, experiments, incidents, schedule

rng = np.random.default_rng(7)


# ---------------------------------------------------------------- caller ID
def _did_counts(rates, dials_per_hour, hours=6):
    a = np.zeros((hours, len(rates), 2), dtype=np.int64)
    for h in range(hours):
        for d, (r, n) in enumerate(zip(rates, dials_per_hour)):
            a[h, d] = [n, rng.binomial(n, r)]
    return a


def test_flags_degraded_did_but_not_healthy_ones():
    win = _did_counts([0.26, 0.26, 0.09], [100, 100, 100])
    life = win.sum(axis=0)
    res = callerid.assess(["D1", "D2", "D3"], win.sum(axis=0), life, {})
    assert res["D3"]["status"] == "flagged"
    assert res["D1"]["status"] == res["D2"]["status"] == "healthy"


def test_unknown_did_until_enough_data():
    win = _did_counts([0.26, 0.26, 0.0], [100, 100, 0])
    res = callerid.assess(["D1", "D2", "D3"], win.sum(axis=0), win.sum(axis=0), {})
    assert res["D3"]["status"] == "unknown"


def test_target_allocation_spreads_load_and_probes_unknown():
    t = callerid.target_allocation({"D1": "healthy", "D2": "healthy", "D3": "unknown", "D4": "flagged"})
    assert t["D4"] == 0 if "D4" in t else True
    assert t["D3"] == pytest.approx(callerid.PROBE_SHARE)
    assert t["D1"] == pytest.approx(t["D2"]) and sum(t.values()) == pytest.approx(1.0)


def test_did_flag_false_positive_rate_on_in_control_data():
    """Eval: 2,000 in-control assessments of 3 equal DIDs → essentially no false flags."""
    fp = 0
    for _ in range(2000):
        win = _did_counts([0.26, 0.26, 0.26], [60, 60, 60], hours=3)
        res = callerid.assess(["D1", "D2", "D3"], win.sum(axis=0), win.sum(axis=0) * 5, {})
        fp += any(v["status"] == "flagged" for v in res.values())
    assert fp / 2000 < 0.005


# ---------------------------------------------------------------- schedule
def _pick_table(profile_by_age, n=400):
    """pick[24, cells, 2]: seniors pick up in the morning, young in the evening."""
    pick = np.zeros((24, cells.N_CELLS, 2), dtype=np.int64)
    for c in range(cells.N_CELLS):
        age = cells.LEVEL["age_band"][c]
        if cells.LEVEL["lang"][c] > 1:
            continue  # only hi/en present
        for h in range(9, 21):
            p = 0.3 * profile_by_age[age][h - 9]
            pick[h, c] = [n // 20, rng.binomial(n // 20, min(p, 0.95))]
    return pick


MORNING = [1.6, 1.6, 1.5, 1.0, 1.0, 0.9, 0.7, 0.7, 0.7, 0.6, 0.6, 0.6]
EVENING = list(reversed(MORNING))
FLAT = [1.0] * 12


def test_schedule_picks_age_and_upweights_seniors_in_morning():
    pick = _pick_table({0: EVENING, 1: FLAT, 2: FLAT, 3: MORNING})
    feat, scores = schedule.choose_feature(pick, [9, 21], langs=["hi", "en"])
    assert feat == "age_band"
    w = schedule.fit_weights(pick, feat, [9, 21], langs=["hi", "en"])
    sen, young = w["age_60p"], w["age_18_30"]
    assert sen["9"] > 1.2 > 0.8 > sen["20"]
    assert young["20"] > young["9"]
    for table in w.values():  # every hour of the window, all positive (an omitted hour would get weight 0)
        assert sorted(map(int, table)) == list(range(9, 21)) and min(table.values()) > 0
    dr = schedule.dry_run(pick, feat, w, [9, 21], langs=["hi", "en"])
    assert dr["expected_pickup_new"] > dr["expected_pickup_old"]


def test_schedule_declines_without_signal():
    pick = _pick_table({0: FLAT, 1: FLAT, 2: FLAT, 3: FLAT})
    feat, _ = schedule.choose_feature(pick, [9, 21], langs=["hi", "en"])
    assert feat is None


# ---------------------------------------------------------------- experiments
def _acc(rates, n_per_day, days, cells_used=(0,)):
    """counts[day, arm, cell, (dials, conn, eng)]."""
    a = np.zeros((16, len(rates), cells.N_CELLS, 3), dtype=np.int64)
    for d in range(days):
        for i, (r, n) in enumerate(zip(rates, n_per_day)):
            for c in cells_used:
                k = n // len(cells_used)
                a[d, i, c] = [k * 3, k, rng.binomial(k, r[d] if isinstance(r, list) else r)]
    return a


def test_initial_exploration_allocation():
    alloc = experiments.explore_alloc(["W1", "W2", "W3"], "W1", {})
    assert alloc == {"W1": pytest.approx(0.8), "W2": pytest.approx(0.1), "W3": pytest.approx(0.1)}


def test_look_declares_clear_winner_and_promotes_with_holdout():
    acc = _acc([0.50, 0.62, 0.50], [800, 200, 200], days=4)
    res = experiments.look(acc, ["W1", "W2", "W3"], "W1", days_running=4, scope_mask=None)
    assert res["action"] == "promote" and res["winner"] == "W2"
    assert res["alloc"] == {"W2": pytest.approx(1 - experiments.HOLDOUT), "W1": pytest.approx(experiments.HOLDOUT)}


def test_look_drops_harmful_arm_and_keeps_exploring():
    acc = _acc([0.55, 0.42, 0.55], [800, 400, 400], days=2)
    res = experiments.look(acc, ["W1", "W2", "W3"], "W1", days_running=2, scope_mask=None)
    assert res["action"] == "ramp" and res["alloc"].get("W2", 0) == 0


def test_no_winner_before_minimum_days_even_if_significant():
    acc = _acc([0.50, 0.65], [800, 300], days=1)
    res = experiments.look(acc, ["W1", "W2"], "W1", days_running=1, scope_mask=None)
    assert res["action"] != "promote"


def test_recent_window_veto_blocks_decaying_winner():
    # W2 great for 3 days, then collapses on the latest day
    acc = _acc([0.50, [0.66, 0.66, 0.66, 0.40]], [900, 400], days=4)
    res = experiments.look(acc, ["W1", "W2"], "W1", days_running=4, scope_mask=None)
    assert res["action"] != "promote"


def test_decay_check_rolls_back_when_winner_fades():
    acc = _acc([[0.55] * 6, [0.64, 0.64, 0.64, 0.64, 0.50, 0.50]], [110, 1000], days=6)
    res = experiments.decay_check(acc, ["W1", "W3"], winner="W3", holdout="W1", promote_day=2, today=6)
    assert res["rollback"] is True


def test_decay_check_quiet_when_stable():
    acc = _acc([[0.55] * 6, [0.64] * 6], [110, 1000], days=6)
    res = experiments.decay_check(acc, ["W1", "W3"], winner="W3", holdout="W1", promote_day=2, today=6)
    assert res["rollback"] is False


def test_cohort_level_protection_when_winner_hurts_a_cohort():
    young = cells.encode({"lang": "hi", "city_tier": "1", "age_band": "18-30", "value_band": "low"})
    old = cells.encode({"lang": "hi", "city_tier": "1", "age_band": "60+", "value_band": "low"})
    acc = np.zeros((16, 2, cells.N_CELLS, 3), dtype=np.int64)
    for d in range(4):
        for arm, (ry, ro) in enumerate([(0.55, 0.55), (0.45, 0.80)]):
            n = 900 if arm == 0 else 600
            acc[d, arm, young] = [n, n, rng.binomial(n, ry)]
            acc[d, arm, old] = [n, n, rng.binomial(n, ro)]
    cohorts = [{"id": "age_18_30", "where": {"age_band": ["18-30"]}}, {"id": "age_60p", "where": {"age_band": ["60+"]}}]
    res = experiments.cohort_split(acc, ["V1", "V3"], "V1", "V3", cohorts, days_running=4)
    assert res["age_18_30"]["action"] == "protect"
    assert res["age_60p"]["action"] in ("promote", "keep")


# ---------------------------------------------------------------- incidents
def test_validation_acceptance_uses_lower_bound():
    assert incidents.validation_verdict(0.99, 300, 0.97) == "pass"
    assert incidents.validation_verdict(0.9725, 300, 0.97) == "escalate"   # borderline P4-like
    assert incidents.validation_verdict(0.94, 300, 0.97) == "fail"
    assert incidents.validation_verdict(0.9725, 1000, 0.97, escalated=True) == "fail"


def test_known_good_prompts_ranked_by_engagement():
    prompt = np.zeros((3, 3), dtype=np.int64)  # P1, P2, P3 : conn, eng, flag
    prompt[0] = [5000, 2700, 70]   # good
    prompt[1] = [800, 380, 45]     # bad flags
    prompt[2] = [100, 60, 1]       # too little data
    good = incidents.known_good(["P1", "P2", "P3"], prompt, p0=0.015, exclude={"P2"})
    assert [g["prompt"] for g in good] == ["P1"]
