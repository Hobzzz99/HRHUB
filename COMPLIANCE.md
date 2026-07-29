# Compliance, Legal & Data-Handling Notes

Read this before enabling the Playwright provider or deploying to production.

## LinkedIn automation risk

Automating a LinkedIn login and scraping member profiles **violates the LinkedIn User
Agreement** (§8.2, which prohibits scrapers, bots, and other automated access), and the
LinkedIn Professional Community Policies. Realistic consequences:

- **Account restriction or permanent ban** of the recruiter's LinkedIn account.
- **Legal exposure.** Scraping has been litigated (e.g. *hiQ Labs v. LinkedIn*); outcomes
  are fact-specific and have shifted over time. Accessing data behind a login, in breach
  of the terms you agreed to, is materially riskier than scraping fully public pages.
- **Detection.** LinkedIn actively fingerprints automation. No delay/jitter strategy makes
  this "safe" — it only reduces the rate of detection.

**This project does not require scraping to function.** The default `PROVIDER=mock` runs
the entire application on deterministic fixtures. The Playwright provider is **opt-in,
disabled by default**, and isolated in its own worker so it can be removed without touching
the rest of the app.

## Current configuration

This checkout is set to `PROVIDER=linkedin` — it scrapes with your own account. Everything
above applies. Switch to `mock` (fixtures) or `apify` at any time; they are drop-in
`CandidateProvider` implementations and nothing else in the app changes.

## Recommended path

Prefer a data source that does not require you to automate a logged-in LinkedIn session.
Each is a drop-in `CandidateProvider` implementation (`backend/app/providers/`), so
switching requires no changes elsewhere:

- **Apify** (`apify` provider — implemented) — LinkedIn data fetched via Apify's API. Apify
  runs the collection; no LinkedIn account is connected here, so there is nothing to get
  banned. It is a third-party service processing public data — review Apify's terms and your
  own lawful basis for the personal data you retain afterward, and treat the actor as rented:
  scraping vendors are litigated by LinkedIn and can disappear (Proxycurl was sued and shut
  down in 2025).
- **LinkedIn Talent Solutions API** — the official, sanctioned integration for recruiting;
  access is restricted to approved partners.
- **ATS integrations** — Greenhouse, Lever, Workday for candidates already in a pipeline.

## If you still enable scraping

You accept the risk above. The code applies these mitigations, none of which are a
guarantee:

- **A hard volume cap of 20 profiles per rolling hour** (`SCRAPE_MAX_PROFILES_PER_HOUR`).
  This is the mitigation that actually matters — volume is what abuse detection keys on.
  The window is persisted to `backend/_state/`, so it survives worker restarts instead of
  handing out a fresh budget after every crash or re-run. A search that exhausts it stops
  early and keeps what it collected.
- **Sign-in is manual.** The app never types credentials and stores none; you log in and
  clear CAPTCHAs yourself in a visible window (`SCRAPE_HEADLESS=false`). This keeps the
  most heavily-scrutinised step human, and means a stolen database yields no password.
- Session state (`storageState`) is encrypted at rest with Fernet (`app/core/crypto.py`);
  the key lives only in `CREDENTIAL_ENC_KEY`. Reusing it keeps logins rare.
- **Human-behaviour emulation** (`SCRAPE_HUMANIZE`, `app/providers/human*.py`): Bezier
  pointer paths with ballistic overshoot and correction, inertial scroll bursts,
  log-normal action pacing with micro-breaks, typing at a variable WPM with corrected
  typos, and a 10-point honeypot check before any click.
- **Fingerprint consistency** (`app/providers/fingerprint.py`): automation flags removed,
  `navigator`/WebGL/client hints kept in agreement, WebRTC leak prevention, timezone
  pinned to the locale. The claimed Chrome version is read off the running engine, never
  hard-coded — claiming a newer Chrome than the binary actually is fails plain feature
  detection. This removes *contradictions*, which is all it can do; it does not make the
  traffic anonymous.
- **Per-account fingerprints.** The GPU, CPU/memory, display and OS build are derived
  from the provider-account row id, so each connected account presents one stable machine
  and two accounts never present the same one. This matters because device correlation is
  how platforms link accounts: a fixed fingerprint means a restriction on one account can
  carry to the next you sign in with. Deleting the account row to switch accounts rotates
  the fingerprint with it. The pools yield ~200 distinct identities, so this defeats
  *identical*-device matching, not a determined correlation effort.
- **What is NOT mitigated: your IP address.** Every request still comes from this host.
  Signing a second account in from the same IP shortly after the first was restricted is
  the single strongest link left, and there is no proxy support in `BrowserPool`.
- A conservative pre-filter reduces the number of profiles actually opened.
- Prefer a **dedicated, disposable account** you are willing to lose. If you sign in with a
  personal or primary recruiting account, understand that a restriction there is
  unrecoverable without sending LinkedIn government ID.

## Data protection & minimization

- Store **only** the fields the product uses (see `candidates` table). Do not warehouse raw
  profile dumps beyond the `raw` JSON needed for debugging; prune it in production.
- Candidate profiles are personal data. Depending on jurisdiction (GDPR, CCPA, etc.) you may
  need a lawful basis, a retention policy, and a deletion/DSAR path. `PROFILE_TTL_DAYS`
  controls cache freshness; add a purge job for production.
- Never log credentials, session state, or full profile PII (`app/core/logging.py` is
  configured to avoid this).

## Scope of what this repo provides

This repository is engineering scaffolding. It is **not** legal advice. Confirm your own
lawful basis and obligations with counsel before processing real candidate data.
