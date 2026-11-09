"""Unit tests for the pure core: time, feature cells, statistics, config operations."""
import math

import numpy as np
import pytest

from controller import cells, configops, stats, timeutil


# ---------------------------------------------------------------- time
def test_ts_to_minute_round_trip():
    assert timeutil.ts_to_minute("2027-01-04T00:00:00+05:30") == 0
    assert timeutil.ts_to_minute("2027-01-05T10:15:00+05:30") == 1440 + 615
    assert timeutil.ts_to_minute("2026-12-21T08:00:00+05:30") == -14 * 1440 + 480
    assert timeutil.minute_to_label(1440 * 3 + 14 * 60) == "D3 14:00"
    assert timeutil.label_to_minute("D3 14:00") == 1440 * 3 + 14 * 60


def test_next_working_matches_simulator_rule():
    # 18:30 + 240 min latency → 22:30 → next day 10:00
    assert timeutil.next_working(18 * 60 + 30 + 240, [10, 19]) == 1440 + 600
    assert timeutil.next_working(9 * 60, [10, 19]) == 600
    assert timeutil.next_working(12 * 60, [10, 19]) == 720


# ---------------------------------------------------------------- cells
def test_cell_encoding_is_bijective():
    seen = set()
    for lang in cells.FEATURES["lang"]:
        for tier in cells.FEATURES["city_tier"]:
            for age in cells.FEATURES["age_band"]:
                for val in cells.FEATURES["value_band"]:
                    c = cells.encode({"lang": lang, "city_tier": tier, "age_band": age, "value_band": val})
                    assert cells.decode(c) == {"lang": lang, "city_tier": tier, "age_band": age, "value_band": val}
                    seen.add(c)
    assert seen == set(range(cells.N_CELLS)) and cells.N_CELLS == 252


def test_where_mask_and_level_of():
    m = cells.where_mask({"age_band": ["60+"], "lang": ["ta", "hi"]})
    assert m.sum() == 2 * 3 * 3  # 2 langs x 3 tiers x 1 age x 3 values
    c = cells.encode({"lang": "ta", "city_tier": "2", "age_band": "60+", "value_band": "low"})
    assert m[c]
    assert cells.LEVEL["age_band"][c] == cells.FEATURES["age_band"].index("60+")


def test_partition_cohorts_cover_population_disjointly():
    coh = cells.partition_cohorts(["age_band"], langs=["hi", "en"])
    assert [c["id"] for c in coh] == ["age_18_30", "age_31_45", "age_46_60", "age_60p"]
    total = np.zeros(cells.N_CELLS, dtype=int)
    for c in coh:
        total += cells.where_mask(c["where"]).astype(int)
    assert (total == 1).all()
    two = cells.partition_cohorts(["age_band", "lang"], langs=["hi", "en"])
    assert len(two) == 8 and all("lang" in c["where"] for c in two)


# ---------------------------------------------------------------- stats
def test_two_prop_z_sign_and_magnitude():
    z = stats.two_prop_z(600, 1000, 500, 1000)
    assert 4.4 < z < 4.6
    assert stats.two_prop_z(500, 1000, 600, 1000) == pytest.approx(-z)
    assert stats.two_prop_z(0, 0, 5, 10) == 0.0


def test_wilson_lower_bound():
    lb = stats.wilson_lower(297, 300, z=1.645)
    assert 0.97 < lb < 0.99
    assert stats.wilson_lower(0, 0) == 0.0


def test_chi2_sf_reasonable():
    assert stats.chi2_sf(3.84, 1) == pytest.approx(0.05, abs=0.01)
    assert stats.chi2_sf(11.34, 3) == pytest.approx(0.01, abs=0.004)


def test_cusum_detects_shift_and_is_quiet_in_control():
    rng = np.random.default_rng(0)
    p0 = 0.015
    llr_hit, llr_miss = stats.bernoulli_llr(p0, 3 * p0)
    s, alarms = 0.0, 0
    for x in rng.random(50_000) < p0:  # in control
        s = max(0.0, s + (llr_hit if x else llr_miss))
        if s > 6:
            alarms += 1
            s = 0.0
    assert alarms <= 1
    s, n = 0.0, 0
    for x in rng.random(5_000) < 0.054:  # shifted
        n += 1
        s = max(0.0, s + (llr_hit if x else llr_miss))
        if s > 6:
            break
    assert n < 600


def test_sample_size_formula():
    n = stats.sample_size_per_arm(0.5, 0.05, z_alpha=1.96, z_beta=0.84)
    assert 1500 < n < 1650


def test_aa_false_winner_rate_under_threshold():
    """A/A eval: with our winner rule (z>=2.9, up to 8 looks, 3 challengers) the
    family-wise false-winner rate must stay under 5%."""
    rng = np.random.default_rng(42)
    trials, false_wins = 400, 0
    for _ in range(trials):
        inc = np.zeros(2); ch = np.zeros((3, 2))
        won = False
        for _look in range(8):
            inc += [rng.binomial(700, 0.5), 700]
            for a in range(3):
                ch[a] += [rng.binomial(110, 0.5), 110]
            if any(stats.two_prop_z(ch[a][0], ch[a][1], inc[0], inc[1]) >= 2.9 for a in range(3)):
                won = True
                break
        false_wins += won
    assert false_wins / trials < 0.05


# ---------------------------------------------------------------- config ops
BASE = {"cohorts": [], "allocations": {"default": {"welcome_message": {"W1": 1.0}, "voice": {"V1": 1.0},
                                                   "caller_id": {"D1": 0.5, "D2": 0.5}}},
        "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


def test_changed_dims_and_shift():
    import copy
    new = copy.deepcopy(BASE)
    new["allocations"]["default"]["voice"] = {"V1": 0.6, "V2": 0.4}
    assert configops.changed_dims(BASE, new) == ["voice"]
    assert configops.max_shift(BASE, new) == pytest.approx(0.4)
    new["schedule"]["hour_weights"] = {"default": {"9": 1}}
    assert configops.changed_dims(BASE, new) == ["voice", "schedule"]


def test_step_toward_respects_max_shift_and_converges():
    import copy
    target = copy.deepcopy(BASE)
    target["allocations"]["default"]["voice"] = {"V2": 1.0}
    cur, steps = BASE, 0
    while configops.max_shift(cur, target) > 1e-9:
        nxt = configops.step_toward(cur, target, 0.2)
        assert configops.max_shift(cur, nxt) <= 0.2 + 1e-9
        cur, steps = nxt, steps + 1
        assert steps < 10
    assert steps <= 6  # ceil(1.0/0.2) plus one tiny step from the rounding safety margin


def test_canonical_drops_zero_weights_and_normalises():
    c = configops.canonical({**BASE, "allocations": {"default": {"welcome_message": {"W1": 2, "W2": 0},
                                                                 "voice": {"V1": 1}, "caller_id": {"D1": 1}}}})
    assert c["allocations"]["default"]["welcome_message"] == {"W1": 1.0}


def test_validate_against_options_catches_bad_hours():
    wf = {"options": {"welcome_message": ["W1"], "voice": ["V1"], "caller_id": ["D1", "D2"], "prompt_version": ["P1"]},
          "dialling_window": [9, 21]}
    bad = {**BASE, "schedule": {"hour_weights": {"default": {"7": 1}}, "lead_preferred_hour": {}}}
    assert configops.validate(wf, bad)
    assert configops.validate(wf, BASE) == []
