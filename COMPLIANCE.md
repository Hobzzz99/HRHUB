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

- Credentials **and** session state (`storageState`) are encrypted at rest with Fernet
  (`app/core/crypto.py`); the key lives only in `CREDENTIAL_ENC_KEY`.
- Logins are minimized by persisting and reusing the browser session.
- Configurable human-like delays with jitter between actions (`SCRAPE_*` env vars).
- A conservative pre-filter reduces the number of profiles actually opened.
- Use a **dedicated, disposable account** you are willing to lose — never a personal or
  primary recruiting account.

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
