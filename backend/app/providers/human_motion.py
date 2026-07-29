"""Pure motion, timing and typing math for human-like browser control.

Deliberately **free of Playwright imports**. Every function here is a pure
function of its arguments plus an injected ``random.Random``, so the emitted
behaviour is seedable and unit-testable without launching a browser.
``app.providers.human`` is the thin layer that feeds these plans to a real Page.

The models below are the standard ones from the HCI literature, not folklore:

* **Pointing** — a cubic Bezier whose control points are pushed off the straight
  line along its perpendicular, so the path arcs the way a wrist does. Position
  is sampled on an ease-in-out curve at a *constant* time step, which is what
  produces the slow-fast-slow velocity profile; total duration comes from Fitts's
  law, so far/small targets legitimately take longer.
* **Overshoot** — real pointing is ballistic: the hand launches past the target
  and makes a short corrective submovement back. Modelled as 8-12% of travel.
* **Delays** — log-normal. Human inter-action gaps are right-skewed (a floor, a
  common case, and a long tail), which a uniform distribution cannot express;
  the occasional long pause falls out of the tail for free.
* **Typing** — keystroke intervals are Gaussian around a per-session WPM, with
  digraph effects (spaces and punctuation take longer) and a small typo rate
  that is corrected with backspaces after a "noticing" pause.
* **Scrolling** — a wheel flick is a burst of events whose deltas decay
  geometrically while the gaps between them grow, followed by micro-adjustments
  once the eye lands on the target.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from random import Random

Point = tuple[float, float]

# --- pointing --------------------------------------------------------------

# Fitts's law: duration = A + B * log2(distance / target_width + 1). The
# constants are in seconds and sit in the range usually measured for mouse
# pointing; they are multiplied by per-move Gaussian noise at call time.
_FITTS_A = 0.09
_FITTS_B = 0.11
_MIN_MOVE_DURATION = 0.08

# Mouse polling looks like 90-130 samples/second to page-level JS.
_SAMPLE_HZ = (90.0, 130.0)
_MIN_STEPS = 6
_MAX_STEPS = 90

# A move shorter than this is a nudge, not a pointing gesture: no arc, no
# overshoot, just a couple of samples.
_NUDGE_DISTANCE = 6.0
# Ballistic overshoot only happens on travel long enough to accelerate into.
_OVERSHOOT_MIN_DISTANCE = 120.0
_OVERSHOOT_PROBABILITY = 0.72
_OVERSHOOT_RANGE = (0.08, 0.12)


@dataclass(frozen=True, slots=True)
class MoveStep:
    """One ``mouse.move`` sample. ``delay`` is the pause *before* moving."""

    x: float
    y: float
    delay: float


def ease_in_out(u: float) -> float:
    """Sinusoidal ease-in-out on ``u`` in [0, 1]: slow, fast, slow."""
    return 0.5 * (1.0 - math.cos(math.pi * _clamp(u, 0.0, 1.0)))


def fitts_duration(distance: float, target_size: float, rng: Random) -> float:
    """Seconds a human would take to point ``distance`` px at a target."""
    width = max(target_size, 8.0)
    index_of_difficulty = math.log2(distance / width + 1.0)
    ideal = _FITTS_A + _FITTS_B * index_of_difficulty
    return max(_MIN_MOVE_DURATION, ideal * rng.gauss(1.0, 0.12))


def cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    mt = 1.0 - t
    a, b, c, d = mt**3, 3 * mt**2 * t, 3 * mt * t**2, t**3
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def arc_control_points(start: Point, end: Point, rng: Random) -> tuple[Point, Point]:
    """Two control points pushed off the start-end line along its perpendicular.

    Both are pushed to the *same* side so the path is one clean arc rather than
    an S-curve, which is how a wrist-driven movement actually bows.
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    distance = math.hypot(dx, dy)
    if distance == 0:
        return start, end
    # Unit perpendicular to the direction of travel.
    px, py = -dy / distance, dx / distance
    side = rng.choice((-1.0, 1.0))
    bow1 = side * abs(rng.gauss(0.06 * distance, 0.03 * distance))
    bow2 = side * abs(rng.gauss(0.06 * distance, 0.03 * distance))
    limit = 0.22 * distance
    bow1, bow2 = _clamp(bow1, -limit, limit), _clamp(bow2, -limit, limit)
    # Slide the anchors along the line so the arc's fullest point is not always
    # dead centre.
    at1 = _clamp(rng.gauss(0.33, 0.08), 0.10, 0.50)
    at2 = _clamp(rng.gauss(0.66, 0.08), 0.50, 0.92)
    c1 = (start[0] + dx * at1 + px * bow1, start[1] + dy * at1 + py * bow1)
    c2 = (start[0] + dx * at2 + px * bow2, start[1] + dy * at2 + py * bow2)
    return c1, c2


def overshoot_point(start: Point, end: Point, rng: Random) -> Point:
    """A point 8-12% of the travel distance past ``end``, slightly off-axis."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    distance = math.hypot(dx, dy)
    if distance == 0:
        return end
    excess = rng.uniform(*_OVERSHOOT_RANGE)
    ux, uy = dx / distance, dy / distance
    # A miss is rarely perfectly along the approach vector.
    lateral = rng.gauss(0.0, 0.02 * distance)
    return (
        end[0] + ux * distance * excess - uy * lateral,
        end[1] + uy * distance * excess + ux * lateral,
    )


def _leg(start: Point, end: Point, rng: Random, *, target_size: float) -> list[MoveStep]:
    """Sample one uninterrupted arc from ``start`` to ``end``."""
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    duration = fitts_duration(distance, target_size, rng)
    steps = int(_clamp(round(duration * rng.uniform(*_SAMPLE_HZ)), _MIN_STEPS, _MAX_STEPS))
    c1, c2 = arc_control_points(start, end, rng)

    out: list[MoveStep] = []
    previous_t = 0.0
    for index in range(1, steps + 1):
        # Constant time step + eased position == variable velocity.
        eased = ease_in_out(index / steps)
        t = _clamp(eased + rng.gauss(0.0, 0.012), previous_t, 1.0)
        previous_t = t
        x, y = cubic_bezier(start, c1, c2, end, t)
        delay = max(0.001, rng.gauss(duration / steps, duration / steps * 0.3))
        out.append(MoveStep(x=x, y=y, delay=delay))
    # Land exactly on the requested pixel; drift of a fraction of a pixel is a
    # tell, and callers rely on the final sample being the click point.
    out[-1] = MoveStep(x=end[0], y=end[1], delay=out[-1].delay)
    return out


def mouse_path(
    start: Point,
    end: Point,
    rng: Random,
    *,
    target_size: float = 24.0,
    allow_overshoot: bool = True,
    bounds: tuple[float, float] | None = None,
) -> list[MoveStep]:
    """A full pointing gesture from ``start`` to ``end``.

    Long moves are ballistic: one arc that lands 8-12% past the target, then a
    short corrective arc back onto it. ``bounds`` (viewport width/height) keeps
    the overshoot from landing outside the window, which the browser would clip.
    """
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    if distance < _NUDGE_DISTANCE:
        return [MoveStep(x=end[0], y=end[1], delay=max(0.004, rng.gauss(0.02, 0.008)))]

    overshooting = (
        allow_overshoot
        and distance >= _OVERSHOOT_MIN_DISTANCE
        and rng.random() < _OVERSHOOT_PROBABILITY
    )
    if not overshooting:
        return _leg(start, end, rng, target_size=target_size)

    aim = overshoot_point(start, end, rng)
    if bounds is not None:
        aim = (_clamp(aim[0], 1.0, bounds[0] - 2.0), _clamp(aim[1], 1.0, bounds[1] - 2.0))
    steps = _leg(start, aim, rng, target_size=target_size)
    # The corrective submovement is short, deliberate and never overshoots again.
    steps.extend(_leg(aim, end, rng, target_size=max(target_size, 12.0)))
    return steps


# --- timing ----------------------------------------------------------------

# Spread of the underlying normal. ~0.45 gives a realistic right tail: most
# gaps near the median, a few several times longer.
_DEFAULT_SIGMA = 0.45


def lognormal_delay(
    median: float, rng: Random, *, sigma: float = _DEFAULT_SIGMA, cap: float | None = None
) -> float:
    """A right-skewed pause in seconds whose median is ``median``.

    Sampled as ``median * exp(N(0, sigma))``, so half of all draws fall either
    side of ``median`` and the tail supplies the occasional long think.
    """
    value = median * math.exp(rng.gauss(0.0, sigma))
    return min(value, cap if cap is not None else median * 8.0)


@dataclass(frozen=True, slots=True)
class PacingProfile:
    """How restless the operator is. Tunable per run; defaults are unhurried."""

    #: Median gap between two ordinary actions.
    action_median_s: float = 1.6
    #: Median settle-and-decide pause after the pointer lands, before a click.
    hesitation_median_s: float = 0.32
    #: Chance an ordinary gap becomes a distracted, much longer one.
    long_pause_probability: float = 0.07
    #: Median length of that distracted pause.
    long_pause_median_s: float = 6.5
    #: Actions between micro-breaks, jittered +/- ``break_jitter``.
    actions_per_break: int = 6
    break_jitter: int = 2
    #: Median length of a micro-break (stepping away from the keyboard).
    break_median_s: float = 9.0
    #: Words per minute, drawn per session from this range.
    wpm_range: tuple[float, float] = (46.0, 78.0)
    #: Fraction of alphabetic keystrokes that come out wrong.
    typo_rate: float = 0.015


def think_delay(rng: Random, profile: PacingProfile) -> float:
    """The gap before the next ordinary action, occasionally a long one."""
    if rng.random() < profile.long_pause_probability:
        return lognormal_delay(profile.long_pause_median_s, rng, sigma=0.5)
    return lognormal_delay(profile.action_median_s, rng)


def next_break_after(rng: Random, profile: PacingProfile) -> int:
    """How many actions to run before the next micro-break."""
    jitter = profile.break_jitter
    return max(1, profile.actions_per_break + rng.randint(-jitter, jitter))


# --- typing ----------------------------------------------------------------

#: Physically adjacent keys on a QWERTY board, used to make typos plausible:
#: a slip lands on a neighbouring key, not a random letter.
_QWERTY_NEIGHBOURS: dict[str, str] = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr",
    "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb", "i": "ujko", "j": "huikmn",
    "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm", "o": "iklp",
    "p": "ol", "q": "wa", "r": "edft", "s": "awedxz", "t": "rfgy",
    "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc", "y": "tghu",
    "z": "asx",
}

#: Emitted where a real correction would press Backspace.
BACKSPACE = "\b"

_MIN_KEYSTROKE_S = 0.028
# A slip is felt before it is fixed; this is the "wait, no" beat.
_TYPO_NOTICE_MEDIAN_S = 0.34
_POST_BACKSPACE_MEDIAN_S = 0.16


@dataclass(frozen=True, slots=True)
class KeyEvent:
    """One keystroke. ``key`` is a literal character or :data:`BACKSPACE`."""

    key: str
    delay: float
    is_typo: bool = False


def keystroke_interval(wpm: float, rng: Random) -> float:
    """Seconds between two keystrokes at ``wpm``, with Gaussian noise.

    Uses the standard 5-characters-per-word convention.
    """
    mean = 60.0 / (wpm * 5.0)
    return max(_MIN_KEYSTROKE_S, rng.gauss(mean, mean * 0.32))


def _mistype(char: str, rng: Random) -> str | None:
    """A neighbouring key for ``char``, matching its case."""
    neighbours = _QWERTY_NEIGHBOURS.get(char.lower())
    if not neighbours:
        return None
    wrong = rng.choice(neighbours)
    return wrong.upper() if char.isupper() else wrong


def typing_plan(
    text: str,
    rng: Random,
    *,
    wpm: float | None = None,
    profile: PacingProfile | None = None,
) -> list[KeyEvent]:
    """Expand ``text`` into keystrokes, including typos and their corrections.

    Replaying the plan verbatim always yields ``text``: every emitted typo is
    followed by a :data:`BACKSPACE` and then the character that was intended.
    """
    profile = profile or PacingProfile()
    if wpm is None:
        wpm = rng.uniform(*profile.wpm_range)

    events: list[KeyEvent] = []
    for char in text:
        delay = keystroke_interval(wpm, rng)
        # Word boundaries and sentence punctuation are where typists breathe.
        if char == " ":
            delay *= rng.uniform(1.0, 1.7)
        elif char in ".,!?;:@":
            delay *= rng.uniform(1.2, 1.9)

        if rng.random() < profile.typo_rate and (wrong := _mistype(char, rng)) is not None:
            events.append(KeyEvent(key=wrong, delay=delay, is_typo=True))
            events.append(
                KeyEvent(key=BACKSPACE, delay=lognormal_delay(_TYPO_NOTICE_MEDIAN_S, rng))
            )
            delay = lognormal_delay(_POST_BACKSPACE_MEDIAN_S, rng)

        events.append(KeyEvent(key=char, delay=delay))
    return events


def replay_text(events: list[KeyEvent]) -> str:
    """The string a plan actually produces. Used to assert plans are faithful."""
    out: list[str] = []
    for event in events:
        if event.key == BACKSPACE:
            if out:
                out.pop()
        else:
            out.append(event.key)
    return "".join(out)


# --- scrolling -------------------------------------------------------------

# One flick's deltas decay by this factor per wheel event...
_BURST_DECAY = (0.70, 0.86)
# ...while the gaps between them stretch, which is what inertia feels like.
_BURST_GAP_GROWTH = (1.10, 1.30)
_BURST_FIRST_DELTA = (150, 320)
_BURST_FIRST_GAP = (0.012, 0.030)
_BURST_MIN_DELTA = 14
_MAX_EVENTS_PER_BURST = 24


@dataclass(frozen=True, slots=True)
class ScrollStep:
    """One ``mouse.wheel`` event. ``delay`` is the pause before it fires."""

    delta: int
    delay: float


def scroll_burst(total: int, rng: Random) -> list[ScrollStep]:
    """A single wheel flick covering ``total`` px: decaying deltas, growing gaps."""
    if total == 0:
        return []
    direction = 1 if total > 0 else -1
    remaining = abs(total)
    delta = min(float(rng.randint(*_BURST_FIRST_DELTA)), float(remaining))
    gap = rng.uniform(*_BURST_FIRST_GAP)
    decay = rng.uniform(*_BURST_DECAY)
    growth = rng.uniform(*_BURST_GAP_GROWTH)

    steps: list[ScrollStep] = []
    while remaining > 0 and len(steps) < _MAX_EVENTS_PER_BURST:
        this = int(min(round(delta), remaining))
        if this <= 0:
            break
        steps.append(ScrollStep(delta=direction * this, delay=gap))
        remaining -= this
        delta *= decay
        gap *= growth
        if delta < _BURST_MIN_DELTA:
            break
    # Whatever the decay left on the table goes onto the final, gentlest event.
    if remaining > 0 and steps:
        last = steps[-1]
        steps[-1] = ScrollStep(delta=last.delta + direction * remaining, delay=last.delay)
    return steps


def scroll_plan(
    total: int, rng: Random, *, profile: PacingProfile | None = None
) -> list[ScrollStep]:
    """Cover ``total`` px as several flicks, then settle with micro-adjustments.

    Nobody reaches a position in one continuous drag: they flick, glance, flick
    again, then nudge a little once the target is on screen — including a small
    correction back the other way when the last flick carried too far.
    """
    profile = profile or PacingProfile()
    if total == 0:
        return []

    bursts = rng.randint(1, 4)
    # Split the distance unevenly; the first flick is usually the biggest.
    weights = sorted((rng.uniform(0.5, 1.5) for _ in range(bursts)), reverse=True)
    scale = sum(weights)
    steps: list[ScrollStep] = []
    dealt = 0
    for index, weight in enumerate(weights):
        share = total - dealt if index == len(weights) - 1 else int(total * weight / scale)
        chunk = scroll_burst(share, rng)
        if not chunk:
            continue
        if steps:
            # The pause between flicks is where the eye actually reads.
            first = chunk[0]
            chunk[0] = ScrollStep(
                delta=first.delta, delay=lognormal_delay(0.45, rng, sigma=0.5)
            )
        steps.extend(chunk)
        dealt += share

    steps.extend(_micro_adjustments(total, rng))
    return steps


def _micro_adjustments(total: int, rng: Random) -> list[ScrollStep]:
    """One or two small nudges after landing, sometimes back the other way."""
    direction = 1 if total >= 0 else -1
    out: list[ScrollStep] = []
    for _ in range(rng.randint(1, 2)):
        magnitude = rng.randint(8, 48)
        # Correcting an over-scroll means briefly reversing.
        sign = -direction if rng.random() < 0.4 else direction
        out.append(
            ScrollStep(delta=sign * magnitude, delay=lognormal_delay(0.28, rng, sigma=0.4))
        )
    return out


# --- helpers ---------------------------------------------------------------


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
