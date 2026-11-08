"""Noise and replicate planner (GEM-65): when is a score change real?

Two kinds of noise, and replicates fix only one of them.

* Task sampling: a score is resolved / N over a finite task set. Its binomial band is
  sqrt(p(1-p)/N) and does not shrink with more replicates. It limits what a leaderboard score (58
  public tasks) or the hidden set (about 120 tasks) can tell us about the true rate.
* Replicate noise: the same agent on the same tasks does not solve the same ones every time.
  Comparing two variants on the SAME tasks cancels the task-sampling part, leaving the
  within-task variance `w` (the mean of p_t(1-p_t) over tasks, p_t = chance task t is solved).
  Each variant averaged over r replicates gives a difference with SD sqrt(2w / (N r)).

`w` is an assumption until we have replicate runs; the default 0.05 reproduces the reported
leaderboard noise of about 2 tasks out of 58 (sqrt(0.05 / 58) = 2.9 points = 1.7 tasks).
"""

from __future__ import annotations

import math
from statistics import NormalDist

DENOMINATORS = {
    "public leaderboard (58 tasks)": 58,
    "hidden set (about 120)": 120,
    "public set (129)": 129,
}
DEFAULT_W = 0.05


def z(p: float) -> float:
    return NormalDist().inv_cdf(p)


def quantum(n: int) -> float:
    """Score points one task is worth."""
    return 100.0 / n


def binomial_band(p: float, n: int, conf: float = 0.95) -> float:
    """Half-width, in points, of the task-sampling band around a rate p (a fraction)."""
    return 100.0 * z(0.5 + conf / 2) * math.sqrt(max(p * (1 - p), 0.0) / n)


def replicate_sd(n: int, w: float, replicates: int) -> float:
    """SD, in points, of a same-task difference between two variants, r replicates each."""
    return 100.0 * math.sqrt(2 * w / (n * max(replicates, 1)))


def replicates_needed(gain_points: float, n: int, w: float = DEFAULT_W, alpha=0.05, power=0.8):
    """Replicates per variant to detect `gain_points` on the same tasks (two-sided)."""
    if gain_points <= 0:
        return None
    d = gain_points / 100.0
    return max(1, math.ceil(2 * w * (z(1 - alpha / 2) + z(power)) ** 2 / (n * d * d)))


def detectable_gain(n: int, w: float, replicates: int, alpha=0.05, power=0.8) -> float:
    """Smallest same-task gain, in points, reliably detected with r replicates per variant."""
    return (z(1 - alpha / 2) + z(power)) * replicate_sd(n, w, replicates)


def needed_curve(n: int, w: float, gains=(1, 2, 3, 4, 5, 7, 10)) -> list[list[float]]:
    return [[g, replicates_needed(g, n, w)] for g in gains]
