"""Tests for the human-behaviour motion, timing and typing models.

These are the parts of the scraping stack that can be tested without a browser:
every function takes an injected ``Random``, so behaviour is reproducible.
"""

from __future__ import annotations

import math
from random import Random

import pytest

from app.providers.human_motion import (
    BACKSPACE,
    PacingProfile,
    arc_control_points,
    cubic_bezier,
    ease_in_out,
    fitts_duration,
    keystroke_interval,
    lognormal_delay,
    mouse_path,
    next_break_after,
    overshoot_point,
    replay_text,
    scroll_burst,
    scroll_plan,
    think_delay,
    typing_plan,
)


def _rng(seed: int = 7) -> Random:
    return Random(seed)


# --- easing / bezier -------------------------------------------------------


def test_ease_in_out_spans_the_unit_interval():
    assert ease_in_out(0.0) == pytest.approx(0.0)
    assert ease_in_out(1.0) == pytest.approx(1.0)
    assert ease_in_out(0.5) == pytest.approx(0.5)


def test_ease_in_out_is_monotonic_and_slow_at_the_ends():
    samples = [ease_in_out(i / 40) for i in range(41)]
    assert all(b >= a for a, b in zip(samples[:-1], samples[1:], strict=True))
    # The middle of the move covers more ground than either end: that gap is
    # exactly what makes the velocity profile non-uniform.
    start_span = samples[4] - samples[0]
    middle_span = samples[22] - samples[18]
    assert middle_span > start_span * 3


def test_cubic_bezier_hits_its_endpoints():
    p0, p1, p2, p3 = (0.0, 0.0), (10.0, 30.0), (40.0, 30.0), (50.0, 0.0)
    assert cubic_bezier(p0, p1, p2, p3, 0.0) == pytest.approx(p0)
    assert cubic_bezier(p0, p1, p2, p3, 1.0) == pytest.approx(p3)


def test_arc_control_points_sit_off_the_straight_line():
    start, end = (0.0, 0.0), (400.0, 0.0)
    c1, c2 = arc_control_points(start, end, _rng())
    # A straight-line path would leave both controls on y == 0.
    assert abs(c1[1]) > 1.0 or abs(c2[1]) > 1.0
    # Same side, so the path bows once instead of snaking.
    assert c1[1] * c2[1] >= 0


# --- pointing --------------------------------------------------------------


def test_fitts_duration_grows_with_distance():
    rng = Random(1)
    near = sum(fitts_duration(50, 24, rng) for _ in range(200))
    rng = Random(1)
    far = sum(fitts_duration(1200, 24, rng) for _ in range(200))
    assert far > near


def test_fitts_duration_grows_as_the_target_shrinks():
    rng = Random(3)
    big = sum(fitts_duration(500, 200, rng) for _ in range(200))
    rng = Random(3)
    small = sum(fitts_duration(500, 10, rng) for _ in range(200))
    assert small > big


def test_overshoot_lands_8_to_12_percent_past_the_target():
    start, end = (0.0, 0.0), (500.0, 0.0)
    rng = _rng()
    for _ in range(200):
        point = overshoot_point(start, end, rng)
        # Project onto the direction of travel; lateral wobble is separate.
        travelled = point[0]
        excess = (travelled - 500.0) / 500.0
        assert 0.08 <= excess <= 0.12


def test_mouse_path_starts_moving_and_lands_exactly_on_target():
    path = mouse_path((10.0, 10.0), (600.0, 400.0), _rng())
    assert len(path) > 5
    assert (path[-1].x, path[-1].y) == pytest.approx((600.0, 400.0))
    assert all(step.delay > 0 for step in path)


def test_mouse_path_arcs_rather_than_travelling_in_a_straight_line():
    start, end = (0.0, 0.0), (800.0, 0.0)
    path = mouse_path(start, end, _rng(), allow_overshoot=False)
    # Straight-line travel along y == 0 would leave zero perpendicular deviation.
    assert max(abs(step.y) for step in path) > 2.0


def test_mouse_path_overshoots_then_corrects():
    start, end = (0.0, 0.0), (700.0, 0.0)
    # Seeded so the probabilistic overshoot definitely fires; assert the shape.
    for seed in range(30):
        path = mouse_path(start, end, Random(seed), allow_overshoot=True)
        if max(step.x for step in path) > end[0] + 1:
            assert (path[-1].x, path[-1].y) == pytest.approx(end)
            return
    pytest.fail("no overshoot produced in 30 seeds")


def test_mouse_path_respects_viewport_bounds():
    path = mouse_path((10.0, 10.0), (1430.0, 300.0), _rng(), bounds=(1440.0, 900.0))
    assert all(0 <= step.x <= 1440 for step in path)


def test_short_moves_are_a_single_nudge():
    path = mouse_path((100.0, 100.0), (102.0, 101.0), _rng())
    assert len(path) == 1


def test_mouse_path_is_reproducible_for_a_seed():
    a = mouse_path((0.0, 0.0), (500.0, 200.0), Random(42))
    b = mouse_path((0.0, 0.0), (500.0, 200.0), Random(42))
    assert [(s.x, s.y, s.delay) for s in a] == [(s.x, s.y, s.delay) for s in b]


# --- timing ----------------------------------------------------------------


def test_lognormal_delay_is_centred_on_its_median():
    rng = _rng()
    samples = sorted(lognormal_delay(2.0, rng) for _ in range(4000))
    assert samples[len(samples) // 2] == pytest.approx(2.0, rel=0.1)


def test_lognormal_delay_is_right_skewed_and_capped():
    rng = _rng()
    samples = [lognormal_delay(1.0, rng, cap=8.0) for _ in range(4000)]
    mean = sum(samples) / len(samples)
    median = sorted(samples)[len(samples) // 2]
    # The defining property: a long right tail drags the mean above the median.
    assert mean > median
    assert max(samples) <= 8.0
    assert all(s > 0 for s in samples)


def test_think_delay_occasionally_produces_a_long_pause():
    profile = PacingProfile(action_median_s=1.0, long_pause_probability=0.1)
    rng = _rng()
    samples = [think_delay(rng, profile) for _ in range(3000)]
    assert max(samples) > 8.0
    assert sorted(samples)[len(samples) // 2] < 3.0


def test_break_interval_stays_around_six_actions():
    profile = PacingProfile()
    rng = _rng()
    values = [next_break_after(rng, profile) for _ in range(500)]
    assert all(4 <= v <= 8 for v in values)
    assert len(set(values)) > 1  # jittered, not a fixed cadence


# --- typing ----------------------------------------------------------------


def test_typing_plan_replays_to_the_original_text():
    rng = _rng()
    text = "Senior Backend Engineer, Cairo"
    for _ in range(50):
        assert replay_text(typing_plan(text, rng)) == text


def test_typing_plan_corrects_its_typos_with_a_backspace():
    profile = PacingProfile(typo_rate=1.0)
    plan = typing_plan("linkedin", _rng(), profile=profile)
    assert any(event.is_typo for event in plan)
    assert any(event.key == BACKSPACE for event in plan)
    # Every typo is followed immediately by its correction.
    for index, event in enumerate(plan):
        if event.is_typo:
            assert plan[index + 1].key == BACKSPACE
    assert replay_text(plan) == "linkedin"


def test_typos_land_on_neighbouring_keys():
    profile = PacingProfile(typo_rate=1.0)
    plan = typing_plan("g", _rng(), profile=profile)
    typo = next(e for e in plan if e.is_typo)
    assert typo.key in "ftyhbv"


def test_typo_rate_defaults_to_about_1_5_percent():
    profile = PacingProfile()
    rng = _rng()
    text = "a" * 40000
    plan = typing_plan(text, rng, profile=profile)
    rate = sum(1 for e in plan if e.is_typo) / len(text)
    assert 0.010 < rate < 0.021


def test_keystroke_interval_tracks_wpm_and_has_a_floor():
    rng = _rng()
    fast = [keystroke_interval(120, rng) for _ in range(2000)]
    slow = [keystroke_interval(30, rng) for _ in range(2000)]
    assert sum(fast) / len(fast) < sum(slow) / len(slow)
    assert min(fast + slow) >= 0.028
    # 60 WPM * 5 chars == 300 chars/min == 0.2s per keystroke.
    rng = _rng()
    at_60 = [keystroke_interval(60, rng) for _ in range(4000)]
    assert sum(at_60) / len(at_60) == pytest.approx(0.2, rel=0.12)


def test_spaces_pause_longer_than_letters():
    rng = _rng()
    profile = PacingProfile(typo_rate=0.0)
    letters, spaces = [], []
    for _ in range(400):
        plan = typing_plan("ab cd ef gh", rng, wpm=60, profile=profile)
        for event in plan:
            (spaces if event.key == " " else letters).append(event.delay)
    assert sum(spaces) / len(spaces) > sum(letters) / len(letters)


# --- scrolling -------------------------------------------------------------


def test_scroll_burst_covers_the_distance_exactly():
    rng = _rng()
    for target in (300, 900, 2400):
        steps = scroll_burst(target, rng)
        assert sum(s.delta for s in steps) == target


def test_scroll_burst_decelerates_while_its_gaps_stretch():
    steps = scroll_burst(3000, _rng())
    assert len(steps) > 4
    # Ignore the final step: it absorbs whatever the decay left over.
    deltas = [s.delta for s in steps[:-1]]
    delays = [s.delay for s in steps[:-1]]
    assert deltas[0] > deltas[-1]
    assert delays[0] < delays[-1]
    assert all(b <= a for a, b in zip(deltas[:-1], deltas[1:], strict=True))


def test_scroll_burst_handles_upward_travel():
    steps = scroll_burst(-800, _rng())
    assert sum(s.delta for s in steps) == -800
    assert all(s.delta <= 0 for s in steps)


def test_scroll_burst_of_zero_is_empty():
    assert scroll_burst(0, _rng()) == []


def test_scroll_plan_lands_near_the_target_after_micro_adjustments():
    rng = _rng()
    for _ in range(100):
        steps = scroll_plan(1800, rng)
        total = sum(s.delta for s in steps)
        # Micro-adjustments deliberately over- and under-shoot a little.
        assert abs(total - 1800) <= 100
        assert len(steps) > 3


def test_scroll_plan_sometimes_corrects_backwards():
    rng = _rng()
    reversals = 0
    for _ in range(100):
        steps = scroll_plan(1500, rng)
        if any(s.delta < 0 for s in steps):
            reversals += 1
    assert reversals > 0


def test_scroll_plan_pauses_between_flicks():
    rng = _rng()
    # Across many plans at least one inter-burst gap must be much longer than
    # the milliseconds between wheel events inside a single flick.
    assert any(
        any(step.delay > 0.15 for step in scroll_plan(4000, rng)) for _ in range(20)
    )


def test_scroll_plan_of_zero_is_empty():
    assert scroll_plan(0, _rng()) == []


# --- sanity ----------------------------------------------------------------


def test_no_delay_is_negative_or_absurd():
    rng = _rng()
    for step in mouse_path((0.0, 0.0), (900.0, 500.0), rng):
        assert 0 < step.delay < 1.0
    for step in scroll_plan(2000, rng):
        assert 0 < step.delay < 10.0
    for event in typing_plan("hello world", rng):
        assert 0 < event.delay < 10.0
    assert not math.isnan(lognormal_delay(1.0, rng))
