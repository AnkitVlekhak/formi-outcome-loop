"""Decision logic on synthetic data with a known truth."""
import numpy as np
import pytest

from controller import callerid, cells, experiments, incidents, schedule

rng = np.random.default_rng(7)


# ---------------------------------------------------------------- caller ID
def _did_counts(rates, dials_per_hour, hours=6, rng=rng):
    a = np.zeros((hours, len(rates), 2), dtype=np.int64)
    for h in range(hours):
        for d, (r, n) in enumerate(zip(rates, dials_per_hour)):
            a[h, d] = [n, rng.binomial(n, r)]
    return a


def test_flags_degraded_did_but_not_healthy_ones():
    win = _did_counts([0.26, 0.26, 0.09], [100, 100, 100])
    life = win.sum(axis=0)
    res = callerid.assess(["D1", "D2", "D3"], win, life, {})
    assert res["D3"]["status"] == "flagged"
    assert res["D1"]["status"] == res["D2"]["status"] == "healthy"


def test_unknown_did_until_enough_data():
    win = _did_counts([0.26, 0.26, 0.0], [100, 100, 0])
    res = callerid.assess(["D1", "D2", "D3"], win, win.sum(axis=0), {})
    assert res["D3"]["status"] == "unknown"


def test_probe_graduates_only_after_a_passed_comparison():
    """Regression (public_01): a 0.55-health probe with enough lifetime dials but an
    inconclusive window must stay on probe, not jump to a full share."""
    win = _did_counts([0.27, 0.27, 0.17], [130, 130, 18], hours=3)
    res = callerid.assess(["D1", "D2", "D4"], win, np.array([[9000, 2400], [9000, 2400], [160, 28]]), {"D4": "unknown"})
    assert res["D4"]["status"] == "unknown"
    win = _did_counts([0.27, 0.27, 0.30], [130, 130, 18], hours=12)   # a good probe, given time
    res = callerid.assess(["D1", "D2", "D3"], win, np.array([[9000, 2400], [9000, 2400], [216, 60]]), {"D3": "unknown"})
    assert res["D3"]["status"] == "healthy"


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
        res = callerid.assess(["D1", "D2", "D3"], win, win.sum(axis=0) * 5, {})
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
def _acc(rates, n_per_day, days, cells_used=(0,), seed=11):
    """counts[day, arm, cell, (dials, conn, eng)]; own RNG so tests don't depend on run order."""
    rng = np.random.default_rng(seed)
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


def test_recently_decaying_arm_is_dropped_even_if_cumulatively_ahead():
    """Regression (public_01 W3): strong for 3 days, then below incumbent for 2 days."""
    acc = _acc([0.55, [0.66, 0.66, 0.66, 0.47, 0.47]], [900, 300], days=5)
    res = experiments.look(acc, ["W1", "W3"], "W1", days_running=5, scope_mask=None)
    assert res["action"] == "ramp" and "W3" in res["dropped"]


def test_bad_arm_dropped_within_three_days_at_dev_volume():
    """Regression (public_02 V4=0.9x): ~100 connects/day at a 10% share must be enough to stop a -10% arm by day 3."""
    hits = 0
    for seed in range(40):
        r = np.random.default_rng(seed)
        acc = np.zeros((16, 2, cells.N_CELLS, 3), dtype=np.int64)
        for d in range(3):
            acc[d, 0, 0] = [2700, 900, r.binomial(900, 0.55)]
            acc[d, 1, 0] = [300, 100, r.binomial(100, 0.495)]
        hits += "V4" in experiments.look(acc, ["V1", "V4"], "V1", days_running=3)["dropped"]
    assert hits / 40 >= 0.5


def test_no_ramp_when_lift_is_fading():
    acc = _acc([0.55, [0.68, 0.68, 0.58, 0.58]], [900, 300], days=4)
    res = experiments.look(acc, ["W1", "W3"], "W1", days_running=4)
    assert res["alloc"].get("W3", 0) <= experiments.CHALLENGER_SHARE


def _decay_acc(seed, w_rates, h_rate=0.55):
    r = np.random.default_rng(seed)
    a = np.zeros((16, 2, cells.N_CELLS, 3), dtype=np.int64)
    for d, wr in enumerate(w_rates):   # days 0-1: exploration (incumbent ~70%), then 90/10 after promotion
        nh, nw = (700, 150) if d < 2 else (110, 1000)
        a[d, 0, 0] = [3 * nh, nh, r.binomial(nh, h_rate)]
        a[d, 1, 0] = [3 * nw, nw, r.binomial(nw, wr)]
    return a


def _two_looks(acc_fn, global_change=False, days=(6, 7)):
    """The check runs every day: did either of two consecutive daily looks fire?"""
    return any(experiments.decay_check(acc_fn(), ["W1", "W3"], "W3", "W1", 2, today, global_change=global_change)
               ["rollback"] for today in days)


def test_decay_check_power_and_false_rollback_rate():
    """Eval over 40 seeds, two daily looks each: a winner that decays from 0.64 to 0.50 is
    rolled back >=95% of the time; a stable winner <=5%; a global drop that hits every arm
    (e.g. a prompt change) is not blamed on the winner (<=10%)."""
    dec = sum(_two_looks(lambda: _decay_acc(s, [0.64] * 4 + [0.50] * 3)) for s in range(40))
    stable = sum(_two_looks(lambda: _decay_acc(s, [0.64] * 7)) for s in range(40))

    def glob_acc(seed):
        r = np.random.default_rng(100 + seed)
        a = np.zeros((16, 2, cells.N_CELLS, 3), dtype=np.int64)
        for d in range(7):
            f = 1.0 if d < 4 else 0.85
            nh, nw = (700, 150) if d < 2 else (110, 1000)
            a[d, 0, 0] = [3 * nh, nh, r.binomial(nh, 0.55 * f)]
            a[d, 1, 0] = [3 * nw, nw, r.binomial(nw, 0.64 * f)]
        return a
    glob = sum(_two_looks(lambda: glob_acc(s), global_change=True) for s in range(40))
    # regression (public_01): winner decays to just below the incumbent (1.16x -> 0.96x), no global change
    small = sum(_two_looks(lambda: _decay_acc(s, [0.64] * 4 + [0.53] * 3)) for s in range(40))
    # ...but a winner that fades yet stays AHEAD of the incumbent must be kept (rolling back would hurt)
    ahead = sum(_two_looks(lambda: _decay_acc(s, [0.64] * 4 + [0.60] * 3)) for s in range(40))
    assert ahead <= 8, ahead
    assert dec >= 38 and stable <= 2 and glob <= 4 and small >= 28, (dec, stable, glob, small)


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


# ---------------------------------------------------------------- regressions from the variant eval
def test_noisy_probe_does_not_graduate_on_a_point_estimate():
    """variant_001: a 0.6-health probe read 0.93x on 128 dials and got a full share."""
    hours = np.zeros((3, 3, 2), dtype=np.int64)
    hours[:, 0] = [150, 40]; hours[:, 1] = [150, 38]; hours[:, 2] = [43, 11]   # probe ~0.95x on 129 dials
    res = callerid.assess(["D1", "D2", "D3"], hours, np.array([[9000, 2400], [9000, 2300], [160, 40]]),
                          {"D3": "unknown"})
    assert res["D3"]["status"] == "unknown"


def test_high_volume_number_compared_against_low_volume_probes():
    """variant_003: KYC D1 at 88% degraded; siblings are 6% probes. The window must grow
    until the reference has enough dials, then flag D1."""
    hours = np.zeros((8, 3, 2), dtype=np.int64)
    for h in range(8):
        hours[h, 0] = [176, 15]    # degraded: 0.085
        hours[h, 1] = [12, 5]      # 0.42
        hours[h, 2] = [12, 4]
    res = callerid.assess(["D1", "D2", "D3"], hours, np.array([[20000, 4000], [200, 80], [200, 70]]),
                          {"D2": "unknown", "D3": "unknown"})
    assert res["D1"]["status"] == "flagged"


def test_incident_confirmation_is_an_exact_tail_over_the_change_window():
    """variant_003: 3h at KYC volume (6/106 vs p0=1.75%) is only p~0.01 by the exact tail, so
    confirmation must use the window since the suspected change (here, the prompt edit)."""
    assert 0.005 < incidents.confirm_p(6, 106, 0.0175) < 0.02
    assert incidents.confirm_p(13, 210, 0.0175) < 1e-3        # since the prompt edit
    assert incidents.confirm_p(16, 314, 0.0147) < 1e-4
    assert incidents.confirm_p(3, 200, 0.015) > 0.05
