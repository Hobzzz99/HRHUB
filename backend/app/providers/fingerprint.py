"""Browser fingerprint consistency for the Playwright provider.

Anti-bot systems rarely catch automation on any single exotic value; they catch
it on *disagreement* between values that a real browser keeps in sync — a UA
claiming Chrome on Windows next to an empty plugin list, a Linux WebGL renderer,
and a `navigator.webdriver` that is still `true`. Everything here exists to keep
that set of signals internally consistent.

Two rules govern this module:

**1. The claimed Chrome version comes from the live engine, never a constant.**
Claiming a *newer* Chrome than the bundled Chromium actually is gets caught by
plain feature detection — the page asks for an API that version shipped and it
is not there. So the major version is read off the running browser
(`browser.version`) and the UA is built from it. Only the patch component, which
no feature depends on and which genuinely varies between real installs, is
derived from the seed.

**2. Everything else is derived per account, deterministically.**
A fixed fingerprint means every account this app touches presents byte-identical
hardware from the same IP — which is precisely how a platform links accounts
together, so one restricted account can take the next one with it.
:func:`derive_profile` maps a seed (the provider-account row id) to a coherent
machine: GPU, cores, memory and display are drawn together so the combination
stays plausible, and the same seed always yields the same machine, so an account
does not appear to hop hardware between sessions.

The patches install through ``add_init_script``, so they run in every frame
before page scripts do. ``Function.prototype.toString`` is patched too: an
override that does not report ``[native code]`` is a louder signal than the
value it was hiding.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from random import Random
from typing import Any

# Used only when the live engine version is not available yet (e.g. building
# launch arguments before the browser exists). Never reported to a page.
FALLBACK_ENGINE_VERSION = "131.0.6778.33"

#: Coherent (cores, deviceMemory, WebGL vendor, WebGL renderer) machines.
#: Drawn as a unit so a 4-core office laptop never claims an RTX 4070, and every
#: renderer is a Windows/Direct3D string — a SwiftShader or Mesa renderer under
#: a Windows UA is the single most reliable headless tell there is.
#: `deviceMemory` maxes out at 8 in Chrome regardless of installed RAM.
_MACHINES: tuple[tuple[int, int, str, str], ...] = (
    (4, 4, "Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00005917) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (4, 8, "Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (8, 8, "Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x000046A6) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (8, 8, "Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (8, 8, "Google Inc. (AMD)",
     "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (12, 8, "Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (12, 8, "Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (16, 8, "Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    (16, 8, "Google Inc. (AMD)",
     "ANGLE (AMD, AMD Radeon RX 7600 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
)

#: (screen, [inner window sizes]). The window is always smaller than the screen
#: — browser chrome and the taskbar take real pixels, and a viewport exactly
#: equal to the screen is a kiosk, not a desktop.
_DISPLAYS: tuple[tuple[tuple[int, int], tuple[tuple[int, int], ...]], ...] = (
    ((1920, 1080), ((1536, 864), (1600, 900), (1745, 975), (1820, 945))),
    ((1536, 864), ((1366, 768), (1440, 790), (1512, 730))),
    ((2560, 1440), ((1920, 1080), (2048, 1152), (1728, 972))),
    ((1366, 768), ((1366, 657), (1280, 660))),
)

#: Chrome reports Windows 11 as platformVersion "15.0.0" and Windows 10 as
#: "10.0.0"; both still say "Windows NT 10.0" in the UA string itself.
_PLATFORM_VERSIONS = ("10.0.0", "15.0.0")


@dataclass(frozen=True, slots=True)
class FingerprintProfile:
    """One coherent machine to present to the page."""

    chrome_major: str
    chrome_full: str
    webgl_vendor: str
    webgl_renderer: str
    cores: int
    memory: int
    viewport: dict[str, int]
    screen: dict[str, int]
    platform_version: str

    @property
    def user_agent(self) -> str:
        # Chrome froze the UA's version detail at <major>.0.0.0 (UA reduction),
        # so the patch component must NOT appear here — only in client hints.
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{self.chrome_major}.0.0.0 Safari/537.36"
        )

    def with_engine_version(self, version: str | None) -> FingerprintProfile:
        """Re-pin the Chrome version to the engine actually running.

        The seed decides the patch component; the major always comes from the
        real binary, so feature detection can never contradict the claim.
        """
        if not version:
            return self
        major = version.split(".", 1)[0]
        if not major.isdigit():
            return self
        tail = self.chrome_full.split(".", 1)[1] if "." in self.chrome_full else "0.0.0"
        return replace(self, chrome_major=major, chrome_full=f"{major}.{tail}")


def derive_profile(
    seed: str | None = None, *, engine_version: str | None = None
) -> FingerprintProfile:
    """Map ``seed`` to a stable, coherent machine profile.

    The same seed always returns the same profile, so an account keeps one
    identity across sessions; different seeds return different hardware, so two
    accounts never look like the same device. ``seed=None`` yields a fixed
    default profile (used by tests and by any caller with no account context).
    """
    # SHA-256 rather than hash(): Python's string hash is randomised per process,
    # which would hand the same account a new machine on every worker restart.
    digest = hashlib.sha256((seed or "default").encode("utf-8")).digest()
    rng = Random(int.from_bytes(digest[:16], "big"))

    cores, memory, webgl_vendor, webgl_renderer = rng.choice(_MACHINES)
    screen, windows = rng.choice(_DISPLAYS)
    window = rng.choice(windows)
    base = engine_version or FALLBACK_ENGINE_VERSION
    major = base.split(".", 1)[0]
    # A plausible patch level for that major; real installs are spread across
    # several. Nothing feature-detectable depends on it.
    build = rng.randint(6000, 6999)
    patch = rng.randint(30, 250)

    return FingerprintProfile(
        chrome_major=major,
        chrome_full=f"{major}.0.{build}.{patch}",
        webgl_vendor=webgl_vendor,
        webgl_renderer=webgl_renderer,
        cores=cores,
        memory=memory,
        viewport={"width": window[0], "height": window[1]},
        screen={"width": screen[0], "height": screen[1]},
        platform_version=rng.choice(_PLATFORM_VERSIONS),
    )


def launch_args(*, headless: bool, profile: FingerprintProfile | None = None) -> list[str]:
    """Chromium switches that remove automation tells at the process level."""
    profile = profile or derive_profile()
    args = [
        # The big one: without it, Blink exposes automation to page scripts.
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-features=IsolateOrigins,site-per-process",
        # Stops ICE from enumerating local interfaces (see the JS patch too).
        "--force-webrtc-ip-handling-policy=default_public_interface_only",
        # Suppress first-run/infobar chrome that a real profile would not show.
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
        "--password-store=basic",
    ]
    if not headless:
        # Size the real window to the profile's display so the reported window
        # metrics match what is actually on screen.
        args.append(
            f"--window-size={profile.viewport['width']},{profile.viewport['height'] + 88}"
        )
        # The window spends the run minimised (see providers/window.py), and
        # Chromium throttles timers, rAF and rendering in windows it believes
        # nobody is watching — which stalls the very page we are driving. These
        # switches keep a backgrounded window running at full speed. They say
        # nothing about automation: a real browser accepts them too.
        args += [
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
        ]
    return args


#: Passed to ``chromium.launch(ignore_default_args=...)``. Playwright adds
#: ``--enable-automation``, which sets ``navigator.webdriver`` and shows the
#: "controlled by automated software" infobar.
IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def context_options(
    *,
    profile: FingerprintProfile | None = None,
    timezone_id: str | None = None,
    locale: str = "en-US",
) -> dict[str, Any]:
    """Keyword arguments for ``browser.new_context`` matching ``profile``."""
    profile = profile or derive_profile()
    options: dict[str, Any] = {
        "user_agent": profile.user_agent,
        "locale": locale,
        "viewport": dict(profile.viewport),
        "screen": dict(profile.screen),
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
        "color_scheme": "light",
        "java_script_enabled": True,
        # Client hints must tell the same story as the UA string.
        "extra_http_headers": {
            "Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9",
            "sec-ch-ua": (
                f'"Chromium";v="{profile.chrome_major}", "Not=A?Brand";v="24", '
                f'"Google Chrome";v="{profile.chrome_major}"'
            ),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    }
    if timezone_id:
        options["timezone_id"] = timezone_id
    return options


# Placeholders are substituted rather than f-string-interpolated so the JS keeps
# its braces and stays copy-pasteable into a devtools console for debugging.
_STEALTH_TEMPLATE = r"""
(() => {
  'use strict';

  // --- keep patched natives looking native ---------------------------------
  // Every override below is discoverable via toString(); route them all through
  // one proxy that reports the real thing.
  const nativeStrings = new WeakMap();
  const originalToString = Function.prototype.toString;
  Function.prototype.toString = new Proxy(originalToString, {
    apply(target, thisArg, args) {
      if (nativeStrings.has(thisArg)) {
        return 'function ' + nativeStrings.get(thisArg) + '() { [native code] }';
      }
      return Reflect.apply(target, thisArg, args);
    },
  });
  nativeStrings.set(Function.prototype.toString, 'toString');
  const asNative = (fn, name) => { nativeStrings.set(fn, name); return fn; };

  // Patches the object in the prototype chain that really owns the property.
  // Defining it straight onto `navigator` would work, but it would also leave
  // an own property where a real browser has none — and enumerating
  // navigator's own keys is a cheaper bot check than reading any single value.
  const define = (obj, prop, get) => {
    try {
      let owner = obj;
      while (owner && !Object.getOwnPropertyDescriptor(owner, prop)) {
        owner = Object.getPrototypeOf(owner);
      }
      // Properties this build lacks entirely (e.g. userAgentData on older
      // Chromium) belong on the prototype, where the real one would live.
      if (!owner) owner = Object.getPrototypeOf(obj) || obj;
      Object.defineProperty(owner, prop, {
        get: asNative(get, 'get ' + prop),
        configurable: true,
        enumerable: true,
      });
    } catch (e) { /* already locked down; nothing useful to do */ }
  };

  // --- automation flag removal ---------------------------------------------
  // Real Chrome DOES have navigator.webdriver: it is an enumerable accessor on
  // Navigator.prototype that returns false. Deleting it outright makes the
  // value `undefined`, which is just as distinctive as `true` — so restore the
  // property with the value an ordinary browser reports.
  try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}
  define(navigator, 'webdriver', () => false);

  // --- navigator consistency ------------------------------------------------
  define(navigator, 'languages', () => __LANGUAGES__);
  define(navigator, 'platform', () => 'Win32');
  define(navigator, 'vendor', () => 'Google Inc.');
  define(navigator, 'hardwareConcurrency', () => __CORES__);
  define(navigator, 'deviceMemory', () => __MEMORY__);
  define(navigator, 'maxTouchPoints', () => 0);
  define(navigator, 'pdfViewerEnabled', () => true);

  // A Chrome install always reports these five; an empty PluginArray under a
  // Chrome UA is a headless giveaway.
  const pluginData = [
    ['PDF Viewer', 'internal-pdf-viewer'],
    ['Chrome PDF Viewer', 'internal-pdf-viewer'],
    ['Chromium PDF Viewer', 'internal-pdf-viewer'],
    ['Microsoft Edge PDF Viewer', 'internal-pdf-viewer'],
    ['WebKit built-in PDF', 'internal-pdf-viewer'],
  ];
  const mimeData = [
    ['application/pdf', 'pdf'],
    ['text/pdf', 'pdf'],
  ];

  const makeArrayLike = (items, proto, nameKey) => {
    const arr = Object.create(proto);
    items.forEach((item, i) => { arr[i] = item; });
    Object.defineProperty(arr, 'length', { value: items.length, enumerable: false });
    arr.item = asNative(function item(i) { return this[i] ?? null; }, 'item');
    arr.namedItem = asNative(function namedItem(n) {
      return items.find((x) => x[nameKey] === n) ?? null;
    }, 'namedItem');
    return arr;
  };

  try {
    const mimes = mimeData.map(([type, suffixes]) => {
      const m = Object.create(MimeType.prototype);
      Object.defineProperties(m, {
        type: { value: type, enumerable: true },
        suffixes: { value: suffixes, enumerable: true },
        description: { value: 'Portable Document Format', enumerable: true },
      });
      return m;
    });
    const plugins = pluginData.map(([name, filename]) => {
      const p = Object.create(Plugin.prototype);
      Object.defineProperties(p, {
        name: { value: name, enumerable: true },
        filename: { value: filename, enumerable: true },
        description: { value: 'Portable Document Format', enumerable: true },
        length: { value: mimes.length, enumerable: true },
      });
      mimes.forEach((m, i) => { p[i] = m; });
      return p;
    });
    const pluginArray = makeArrayLike(plugins, PluginArray.prototype, 'name');
    const mimeArray = makeArrayLike(mimes, MimeTypeArray.prototype, 'type');
    // Cross-link them the way the real implementation does.
    mimes.forEach((m) => {
      Object.defineProperty(m, 'enabledPlugin', { value: plugins[0], enumerable: true });
    });
    define(navigator, 'plugins', () => pluginArray);
    define(navigator, 'mimeTypes', () => mimeArray);
  } catch (e) { /* Plugin/MimeType constructors missing — skip rather than throw */ }

  // userAgentData must agree with the UA string and the sec-ch-ua headers.
  try {
    const brands = [
      { brand: 'Chromium', version: '__CHROME_MAJOR__' },
      { brand: 'Not=A?Brand', version: '24' },
      { brand: 'Google Chrome', version: '__CHROME_MAJOR__' },
    ];
    const highEntropy = {
      architecture: 'x86',
      bitness: '64',
      brands,
      fullVersionList: brands.map((b) => ({
        brand: b.brand,
        version: b.brand === 'Not=A?Brand' ? '24.0.0.0' : '__CHROME_FULL__',
      })),
      mobile: false,
      model: '',
      platform: 'Windows',
      platformVersion: '__PLATFORM_VERSION__',
      uaFullVersion: '__CHROME_FULL__',
      wow64: false,
    };
    define(navigator, 'userAgentData', () => ({
      brands,
      mobile: false,
      platform: 'Windows',
      getHighEntropyValues: asNative(
        function getHighEntropyValues(hints) {
          const out = { brands, mobile: false, platform: 'Windows' };
          (hints || []).forEach((h) => {
            if (h in highEntropy) out[h] = highEntropy[h];
          });
          return Promise.resolve(out);
        }, 'getHighEntropyValues'),
      toJSON: asNative(function toJSON() {
        return { brands, mobile: false, platform: 'Windows' };
      }, 'toJSON'),
    }));
  } catch (e) {}

  // window.chrome exists in every real Chrome, including when not extension-y.
  if (!window.chrome) {
    window.chrome = {
      app: { isInstalled: false, InstallState: {}, RunningState: {} },
      csi: asNative(function csi() { return {}; }, 'csi'),
      loadTimes: asNative(function loadTimes() { return {}; }, 'loadTimes'),
      runtime: { id: undefined, connect: undefined, sendMessage: undefined },
    };
  }

  // Notification permission and the Permissions API disagree in headless Chrome.
  try {
    const query = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = asNative(function query(desc) {
      if (desc && desc.name === 'notifications') {
        return Promise.resolve({
          state: Notification.permission, name: 'notifications',
          onchange: null, addEventListener() {}, removeEventListener() {},
        });
      }
      return query(desc);
    }, 'query');
  } catch (e) {}

  // Window metrics: a real window has browser chrome above the viewport.
  define(window, 'outerWidth', () => window.innerWidth);
  define(window, 'outerHeight', () => window.innerHeight + 88);

  // --- WebGL ---------------------------------------------------------------
  // UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL are the parameters every
  // fingerprinter reads; answer with hardware that fits the claimed platform.
  const patchWebGL = (proto) => {
    if (!proto) return;
    const getParameter = proto.getParameter;
    proto.getParameter = asNative(function getParameter(parameter) {
      if (parameter === 37445) return '__WEBGL_VENDOR__';
      if (parameter === 37446) return '__WEBGL_RENDERER__';
      return getParameter.apply(this, arguments);
    }, 'getParameter');
  };
  patchWebGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchWebGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  // --- WebRTC leak prevention ----------------------------------------------
  // The launch switch stops interface enumeration; this strips anything that
  // still carries a routable address out of the SDP and the candidate events,
  // while leaving RTCPeerConnection present and working (its absence is itself
  // a fingerprint).
  try {
    const LEAKY = /(\d{1,3}\.){3}\d{1,3}|[a-f0-9]{4}:[a-f0-9:]+|\.local/i;
    const isLeak = (line) => line.includes('candidate:') &&
      !line.includes('typ relay') && LEAKY.test(line);
    const scrubSdp = (sdp) => typeof sdp === 'string'
      ? sdp.split('\n').filter((line) => !isLeak(line)).join('\n')
      : sdp;

    const OriginalPC = window.RTCPeerConnection;
    if (OriginalPC) {
      const proto = OriginalPC.prototype;
      const createOffer = proto.createOffer;
      proto.createOffer = asNative(function createOffer() {
        return createOffer.apply(this, arguments).then((d) => {
          if (d && d.sdp) { try { d.sdp = scrubSdp(d.sdp); } catch (e) {} }
          return d;
        });
      }, 'createOffer');

      const addIceCandidate = proto.addIceCandidate;
      proto.addIceCandidate = asNative(function addIceCandidate(candidate) {
        if (candidate && candidate.candidate && isLeak(candidate.candidate)) {
          return Promise.resolve();
        }
        return addIceCandidate.apply(this, arguments);
      }, 'addIceCandidate');
    }
  } catch (e) {}
})();
"""


def stealth_script(
    *, profile: FingerprintProfile | None = None, locale: str = "en-US"
) -> str:
    """The init script to install on a context, tailored to ``profile``."""
    profile = profile or derive_profile()
    languages = [locale, locale.split("-")[0]]
    if "en" not in languages:
        languages.append("en")
    return (
        _STEALTH_TEMPLATE.replace("__LANGUAGES__", str(languages).replace("'", '"'))
        .replace("__CORES__", str(profile.cores))
        .replace("__MEMORY__", str(profile.memory))
        .replace("__CHROME_MAJOR__", profile.chrome_major)
        .replace("__CHROME_FULL__", profile.chrome_full)
        .replace("__PLATFORM_VERSION__", profile.platform_version)
        .replace("__WEBGL_VENDOR__", profile.webgl_vendor)
        .replace("__WEBGL_RENDERER__", profile.webgl_renderer)
    )


def describe(profile: FingerprintProfile) -> str:
    """A one-line summary for logs. No seed, so it is safe to log."""
    gpu = re.sub(r"^ANGLE \([^,]+, ", "", profile.webgl_renderer).split(" Direct3D")[0]
    return (
        f"Chrome {profile.chrome_full} · {gpu} · {profile.cores}c/{profile.memory}GB · "
        f"{profile.viewport['width']}x{profile.viewport['height']} "
        f"on {profile.screen['width']}x{profile.screen['height']} · "
        f"Windows {profile.platform_version}"
    )
