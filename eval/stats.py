"""Small, dependency-free statistics for the eval harness.

  wilson(k, n)        95% Wilson score interval for a proportion (better than +-1.96*se
                      for small n or rates near 0% / 100%)
  cohen_kappa(a, b)   chance-corrected agreement between two raters on yes/no labels
  flip_rate(runs)     share of items whose verdict is not identical across repeated runs
"""
from math import sqrt

Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """Cohen's kappa for two raters over the same items. None if there are no items or
    agreement by chance is total (both raters always gave the same single label)."""
    if len(a) != len(b):
        raise ValueError("raters must label the same items")
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def flip_rate(runs: list[list[bool]]) -> float:
    """runs[r][i] is run r's verdict on item i; returns the share of items that changed."""
    if not runs or not runs[0]:
        return 0.0
    n = len(runs[0])
    flipped = sum(1 for i in range(n) if len({run[i] for run in runs}) > 1)
    return flipped / n


def fmt_rate(k: int, n: int) -> str:
    """'85% (78-90%)': point estimate with its 95% interval."""
    if n == 0:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% ({100 * lo:.0f}-{100 * hi:.0f}%)"
