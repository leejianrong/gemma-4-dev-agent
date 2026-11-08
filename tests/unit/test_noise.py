import math

import pytest

from dashboards import noise


def test_one_task_is_worth_a_hundredth_over_n():
    assert round(noise.quantum(58), 2) == 1.72
    assert round(noise.quantum(129), 2) == 0.78


def test_binomial_band_matches_the_textbook_value_and_shrinks_with_n():
    assert noise.binomial_band(0.17, 58) == pytest.approx(
        100 * 1.959964 * math.sqrt(0.17 * 0.83 / 58), rel=1e-4
    )
    assert noise.binomial_band(0.17, 129) < noise.binomial_band(0.17, 58)
    assert noise.binomial_band(0.0, 58) == 0.0


def test_default_w_reproduces_about_two_tasks_of_run_noise_on_58():
    one_run_sd_points = 100 * math.sqrt(noise.DEFAULT_W / 58)
    assert one_run_sd_points / noise.quantum(58) == pytest.approx(1.7, abs=0.1)


def test_replicates_grow_as_the_gain_shrinks_and_fall_with_more_tasks():
    r_small = noise.replicates_needed(2, 58)
    r_big = noise.replicates_needed(5, 58)
    assert r_small > r_big >= 1
    assert noise.replicates_needed(5, 129) <= noise.replicates_needed(5, 58)
    assert noise.replicates_needed(0, 58) is None


def test_the_replicate_count_actually_detects_the_gain():
    r = noise.replicates_needed(5, 58)
    assert noise.detectable_gain(58, noise.DEFAULT_W, r) <= 5.0
    assert noise.detectable_gain(58, noise.DEFAULT_W, r - 1) > 5.0 if r > 1 else True


def test_curve_is_one_row_per_gain():
    rows = noise.needed_curve(58, 0.05, gains=(2, 5))
    assert [r[0] for r in rows] == [2, 5] and rows[0][1] > rows[1][1]
