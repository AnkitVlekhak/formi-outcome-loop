"""Small, dependency-free statistics. Every decision rule in the controller uses these."""
from __future__ import annotations

import math


def two_prop_z(s1: float, n1: float, s2: float, n2: float) -> float:
    """z for (p1 - p2) with unpooled variance; 0 when either arm is empty."""
    if n1 <= 0 or n2 <= 0:
        return 0.0
    p1, p2 = s1 / n1, s2 / n2
    var = p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2
    if var <= 0:
        # both degenerate: fall back to pooled variance to avoid infinite z
        p = (s1 + s2) / (n1 + n2)
        var = p * (1 - p) * (1 / n1 + 1 / n2)
        if var <= 0:
            return 0.0
    return (p1 - p2) / math.sqrt(var)


def diff_se(s1, n1, s2, n2) -> tuple[float, float]:
    if n1 <= 0 or n2 <= 0:
        return 0.0, float("inf")
    p1, p2 = s1 / n1, s2 / n2
    return p1 - p2, math.sqrt(max(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2, 1e-12))


def wilson_lower(s: float, n: float, z: float = 1.645) -> float:
    if n <= 0:
        return 0.0
    p = s / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / den


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def chi2_sf(x: float, k: int) -> float:
    """Wilson–Hilferty approximation; good to ~1e-3 for the k we use (1..12)."""
    if x <= 0:
        return 1.0
    z = ((x / k) ** (1 / 3) - (1 - 2 / (9 * k))) / math.sqrt(2 / (9 * k))
    return norm_sf(z)


def bernoulli_llr(p0: float, p1: float) -> tuple[float, float]:
    """Per-observation log-likelihood ratio increments (hit, miss) for a Bernoulli CUSUM."""
    return math.log(p1 / p0), math.log((1 - p1) / (1 - p0))


def sample_size_per_arm(p: float, delta: float, z_alpha: float = 1.96, z_beta: float = 0.84) -> int:
    return int(math.ceil((z_alpha + z_beta) ** 2 * 2 * p * (1 - p) / delta ** 2))


def shrink(s: float, n: float, prior_mean: float, strength: float = 50.0) -> float:
    """Beta-binomial posterior mean (empirical-Bayes shrinkage toward prior_mean)."""
    return (s + strength * prior_mean) / (n + strength)
