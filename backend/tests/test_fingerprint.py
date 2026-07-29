"""Tests for the fingerprint layer and the honeypot rule set.

The stealth script and the honeypot check only have meaning inside a real
browser, so what is asserted here is what can be checked without one: that the
values told to the page agree with each other, that per-account derivation is
stable and distinct, and that the rule set has not silently lost a rule.
"""

from __future__ import annotations

import re
import subprocess
import sys

from app.providers import fingerprint
from app.providers.human import _HONEYPOT_JS, HONEYPOT_CHECKS

# --- fingerprint consistency -----------------------------------------------


def test_no_placeholder_survives_into_the_script():
    script = fingerprint.stealth_script()
    assert "__" not in re.sub(r"__proto__|__defineGetter__", "", script)


def test_client_hints_agree_with_the_user_agent():
    profile = fingerprint.derive_profile("acct-1")
    options = fingerprint.context_options(profile=profile)
    hints = options["extra_http_headers"]["sec-ch-ua"]
    major = profile.chrome_major
    assert f"Chrome/{major}.0.0.0" in profile.user_agent
    assert f'"Google Chrome";v="{major}"' in hints
    assert options["extra_http_headers"]["sec-ch-ua-platform"] == '"Windows"'
    # The UA claims Windows; every other platform signal must too.
    assert "Windows NT" in profile.user_agent
    assert "'Win32'" in fingerprint.stealth_script(profile=profile)


def test_user_agent_hides_the_patch_version():
    # Chrome froze the UA at <major>.0.0.0 (UA reduction); a real patch level
    # appearing there is a spoof marker on its own. It belongs in client hints.
    profile = fingerprint.derive_profile("acct-1")
    assert profile.chrome_full not in profile.user_agent
    assert f"Chrome/{profile.chrome_major}.0.0.0" in profile.user_agent
    assert profile.chrome_full in fingerprint.stealth_script(profile=profile)


def test_claimed_version_follows_the_real_engine():
    # Claiming a newer Chrome than the engine actually is fails plain feature
    # detection, so the major must be taken from the running binary.
    profile = fingerprint.derive_profile("acct-1").with_engine_version("118.0.5993.88")
    assert profile.chrome_major == "118"
    assert profile.chrome_full.startswith("118.")
    assert "Chrome/118.0.0.0" in profile.user_agent
    assert '"Google Chrome";v="118"' in (
        fingerprint.context_options(profile=profile)["extra_http_headers"]["sec-ch-ua"]
    )


def test_engine_version_pinning_tolerates_junk():
    profile = fingerprint.derive_profile("acct-1")
    assert profile.with_engine_version(None) == profile
    assert profile.with_engine_version("") == profile
    assert profile.with_engine_version("not-a-version") == profile


def test_webgl_renderer_is_plausible_for_the_claimed_platform():
    for seed in ("a", "b", "c", "d", "e", "f", "g", "h"):
        profile = fingerprint.derive_profile(seed)
        assert profile.webgl_renderer in fingerprint.stealth_script(profile=profile)
        # A software renderer under a Windows UA is the classic headless tell.
        assert "SwiftShader" not in profile.webgl_renderer
        assert "Mesa" not in profile.webgl_renderer
        assert "Direct3D" in profile.webgl_renderer


def test_accept_language_follows_the_configured_locale():
    options = fingerprint.context_options(locale="fr-FR")
    assert options["extra_http_headers"]["Accept-Language"].startswith("fr-FR,fr")
    assert '"fr-FR"' in fingerprint.stealth_script(locale="fr-FR")


def test_timezone_is_only_set_when_configured():
    assert "timezone_id" not in fingerprint.context_options()
    assert fingerprint.context_options(timezone_id="Africa/Cairo")["timezone_id"] == (
        "Africa/Cairo"
    )


def test_automation_flags_are_removed():
    assert "--disable-blink-features=AutomationControlled" in fingerprint.launch_args(
        headless=False
    )
    assert "--enable-automation" in fingerprint.IGNORE_DEFAULT_ARGS
    assert "delete Object.getPrototypeOf(navigator).webdriver" in (
        fingerprint.stealth_script()
    )


def test_webdriver_reports_false_rather_than_undefined():
    # Real Chrome has the property and returns false. Deleting it outright is
    # just as distinctive as leaving it true.
    assert "define(navigator, 'webdriver', () => false)" in fingerprint.stealth_script()


def test_navigator_patches_target_the_prototype_not_the_instance():
    # Patching `navigator` directly leaves own properties where a real browser
    # has none, so `Object.getOwnPropertyNames(navigator)` becomes the tell.
    script = fingerprint.stealth_script()
    assert "Object.getPrototypeOf(owner)" in script
    assert "getOwnPropertyDescriptor(owner, prop)" in script


def test_webrtc_leak_prevention_is_installed_at_both_levels():
    args = fingerprint.launch_args(headless=False)
    assert any("webrtc-ip-handling-policy" in arg for arg in args)
    script = fingerprint.stealth_script()
    # RTCPeerConnection must survive — its absence is itself a fingerprint.
    assert "RTCPeerConnection" in script
    assert "typ relay" in script


def test_patched_natives_still_report_native_code():
    # Without this, every override is trivially discoverable via toString().
    assert "[native code]" in fingerprint.stealth_script()


def test_viewport_fits_inside_the_reported_screen():
    for seed in (str(i) for i in range(40)):
        profile = fingerprint.derive_profile(seed)
        assert profile.viewport["width"] <= profile.screen["width"]
        # Strictly shorter: browser chrome and the taskbar take real pixels, and
        # a window exactly as tall as the screen is a kiosk, not a desktop.
        assert profile.viewport["height"] < profile.screen["height"]


# --- per-account derivation ------------------------------------------------


def test_the_same_seed_always_yields_the_same_machine():
    # An account that appears to change hardware between sessions is worse than
    # one that never varied at all.
    assert fingerprint.derive_profile("account-a") == fingerprint.derive_profile(
        "account-a"
    )
    left = fingerprint.stealth_script(profile=fingerprint.derive_profile("account-a"))
    right = fingerprint.stealth_script(profile=fingerprint.derive_profile("account-a"))
    assert left == right


def test_different_seeds_yield_different_machines():
    # The point of the exercise: two accounts must not present identical
    # hardware from the same host.
    identities = {
        (
            p.webgl_renderer,
            p.cores,
            p.memory,
            p.viewport["width"],
            p.viewport["height"],
            p.screen["width"],
            p.platform_version,
        )
        for p in (fingerprint.derive_profile(f"account-{i}") for i in range(40))
    }
    # Finite pools mean 40 seeds cannot all be unique, but the spread must be wide.
    assert len(identities) >= 15


def test_two_accounts_do_not_share_a_fingerprint():
    a = fingerprint.derive_profile("11111111-1111-1111-1111-111111111111")
    b = fingerprint.derive_profile("22222222-2222-2222-2222-222222222222")
    assert a != b
    assert fingerprint.stealth_script(profile=a) != fingerprint.stealth_script(profile=b)


def test_derivation_is_stable_across_processes():
    # Python's builtin hash() is salted per process, which would silently hand
    # an account new hardware after every worker restart.
    code = (
        "from app.providers import fingerprint;"
        "p = fingerprint.derive_profile('stability-probe');"
        "print(p.webgl_renderer, p.cores, p.memory, p.viewport, p.platform_version)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd="."
    ).stdout.strip()
    local = fingerprint.derive_profile("stability-probe")
    expected = (
        f"{local.webgl_renderer} {local.cores} {local.memory} "
        f"{local.viewport} {local.platform_version}"
    )
    assert out == expected


def test_hardware_combinations_stay_plausible():
    for seed in (str(i) for i in range(60)):
        profile = fingerprint.derive_profile(seed)
        assert profile.cores in (4, 6, 8, 12, 16)
        # Chrome never reports more than 8 for deviceMemory.
        assert profile.memory in (4, 8)
        # A 4-core laptop claiming a high-tier discrete card is the kind of
        # mismatch that stands out more than either value would alone.
        if "GeForce RTX 40" in profile.webgl_renderer:
            assert profile.cores >= 12
        if "UHD Graphics" in profile.webgl_renderer:
            assert profile.cores <= 8


def test_window_size_argument_matches_the_profile_viewport():
    profile = fingerprint.derive_profile("acct-window")
    args = fingerprint.launch_args(headless=False, profile=profile)
    assert any(f"--window-size={profile.viewport['width']}," in a for a in args)
    # Headless has no window to size.
    assert not any("--window-size" in a for a in fingerprint.launch_args(headless=True))


def test_describe_is_loggable_and_leaks_no_seed():
    profile = fingerprint.derive_profile("super-secret-account-id")
    summary = fingerprint.describe(profile)
    assert "super-secret-account-id" not in summary
    assert str(profile.cores) in summary
    assert profile.chrome_full in summary


# --- honeypot rule set -----------------------------------------------------


def test_honeypot_check_has_ten_points():
    assert len(HONEYPOT_CHECKS) == 10
    assert len(set(HONEYPOT_CHECKS)) == 10


def test_every_declared_check_is_actually_raised_by_the_script():
    for name in HONEYPOT_CHECKS:
        assert f"'{name}'" in _HONEYPOT_JS, f"{name} is declared but never pushed"


def test_the_script_raises_no_undeclared_check():
    raised = set(re.findall(r"flags\.push\('([a-z_]+)'\)", _HONEYPOT_JS))
    assert raised == set(HONEYPOT_CHECKS)


def test_honeypot_covers_the_expected_signal_families():
    # The named dimensions from the safety spec: display, opacity, size,
    # position, z-index, aria-hidden, and name patterns.
    for token in ("display", "opacity", "visibility", "zIndex", "aria-hidden"):
        assert token in _HONEYPOT_JS
    assert "getBoundingClientRect" in _HONEYPOT_JS
    assert "honey" in _HONEYPOT_JS


def test_below_the_fold_is_not_treated_as_offscreen():
    # The offscreen rule must compare against document coordinates; using the
    # viewport would reject every result further down a search page.
    assert "scrollWidth" in _HONEYPOT_JS and "scrollHeight" in _HONEYPOT_JS
    assert "window.scrollY" in _HONEYPOT_JS
