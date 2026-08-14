# HRHUB — Recruiter Candidate Search Platform

Enter your hiring requirements; HRHUB searches candidate profiles, extracts and scores
them against your criteria, and returns only the best matches — replacing hours of manual
profile review. The web app is branded **TalentFinder**.

The platform is **source-agnostic**: candidate data comes from a pluggable
`CandidateProvider`, so the app is not tied to any one site. It ships with:

- **`mock`** — deterministic fixtures. **No account, no network, no keys.** The default,
  and how the app is developed and tested.
- **`linkedin`** — we drive a real Chromium window ourselves. **You sign in and clear any
  CAPTCHA by hand**; the app never types credentials. Capped at **20 profiles per hour**
  by a rolling window persisted to disk, so the limit holds across searches and worker
  restarts. See [The scraping stack](#the-scraping-stack).
- **`apify`** — LinkedIn profiles bought through the [Apify](https://apify.com) API. No
  LinkedIn account is involved, so there is nothing to get banned. Needs an Apify token.

> **Scraping LinkedIn violates its User Agreement** and can get the account you sign in
> with restricted — no amount of behavioural realism changes that. This has already
> happened once to an account used with this repo. Read
> [`COMPLIANCE.md`](./COMPLIANCE.md) before pointing it at an account you care about.

---

## How matching works

Each candidate is scored 0–100 as a weighted sum of five components. All scoring is
deterministic and versioned, so stored results stay reproducible.

| Component  | Weight | Basis                                                         |
| ---------- | ------ | ------------------------------------------------------------- |
| Title      | 30%    | Token overlap of the required title vs. the candidate's title/headline |
| Skills     | 30%    | Fraction of required skills the candidate has (with alias matching) |
| Experience | 20%    | Total years (overlaps merged, gaps excluded) vs. the minimum required |
| Location   | 10%    | Location-token overlap                                        |
| Education  | 10%    | Presence of education and credentials                         |

Candidates that fail a hard requirement (below minimum experience, missing a critical
skill, below the score threshold) are filtered out. If none pass, every scored candidate
is still returned, ranked — a search is never silently empty.

Optional **AI semantic matching** (`AI_MATCHING=on`, off by default) layers Claude-based
scoring on top of the deterministic base — e.g. recognising Backend ≈ Full-Stack.

> **Skill matching is literal.** Requiring "Financial Reporting" does not match a profile
> listing "Financial Accounting" or "Financial Results" — they score 0 on the skills
> component despite being close. Either use terms that appear verbatim on profiles, leave
> skills empty and let title/experience/location rank, or turn on `AI_MATCHING`.

## Architecture

```
frontend/  Next.js 15 (App Router) · shadcn/ui · TanStack Query        → REST + SSE
backend/   FastAPI (REST + live SSE status)  and  a Celery worker  share one codebase
           providers/ (mock · linkedin · apify) · domain/ (scoring, filtering) · db/ · api/ · services/
Postgres   candidate + search data          Redis   Celery broker/result backend
```

The search pipeline runs in a worker, isolated from the API: **provider search →
pre-filter → cache/fetch → score → filter → store**, with progress committed incrementally
so the UI reflects live state over SSE. Already-seen candidates are served from the
database (within `PROFILE_TTL_DAYS`) and never re-fetched — no data-source cost is spent
twice on the same person.

---

## The scraping stack

Only relevant with `PROVIDER=linkedin`. Four layers, in descending order of how much they
actually protect you.

### 1. Volume cap — the control that matters

`providers/rate_limit.py` enforces at most **20 profiles per rolling hour**. Volume is
what abuse detection keys on; behavioural realism is a distant second.

The window is **persisted to `backend/_state/`**, not held in memory. An in-memory counter
resets on every worker restart, so a crash loop or an impatient re-run would quietly hand
out a fresh budget. A search that exhausts the budget stops early and keeps what it
collected rather than failing.

### 2. Manual sign-in

The app never types credentials and stores none. A visible Chromium window opens and waits
for you to sign in and clear any CAPTCHA (`SCRAPE_LOGIN_TIMEOUT_S`, default 600s). The
resulting Playwright `storage_state` is encrypted with Fernet and reused, so you should
only sign in once. `SCRAPE_HEADLESS` must be `false` — nobody can sign in to a headless
browser.

If LinkedIn restricts the account, the provider fails **fast and terminally** with an
explicit message rather than retrying: a restriction requires government-ID verification
and no code change can clear it.

### 3. Human behaviour emulation (`SCRAPE_HUMANIZE`)

`providers/human_motion.py` is pure, seedable math with no Playwright import;
`providers/human.py` drives a real page with it.

| Layer | Technique |
| --- | --- |
| **Mouse** | Cubic Bezier with perpendicular arc offset; ease-in-out sampled at a constant time step (which is what produces variable velocity); Fitts's-law duration; 8–12% ballistic overshoot then a corrective submovement |
| **Scroll** | Burst flicks whose deltas decay geometrically while gaps grow (inertia), then micro-adjustments once the target lands — sometimes correcting backwards |
| **Timing** | Log-normal delays (a floor, a common case, a long tail), micro-breaks every ~6 actions, hesitation between the pointer landing and the click |
| **Typing** | Per-session WPM with Gaussian noise, longer pauses at word and sentence boundaries, 1.5% typo rate corrected with a backspace after a "noticing" beat |
| **Safety** | A 10-point honeypot check before any click: display, visibility, opacity, size, off-document position, negative z-index, aria-hidden, name patterns, hidden/untabbable inputs, clipped/inert |

### 4. Fingerprint consistency

`providers/fingerprint.py`. Anti-bot systems rarely catch a single exotic value; they
catch *disagreement* between values a real browser keeps in sync.

- **Automation flags removed** — `navigator.webdriver` is restored to `false` (real Chrome
  has the property; deleting it is as distinctive as leaving it `true`), and Playwright's
  `--enable-automation` switch is dropped.
- **Patches target the prototype, not the instance** — defining properties straight onto
  `navigator` leaves own properties where a real browser has none, and enumerating
  `Object.getOwnPropertyNames(navigator)` is a cheaper bot check than reading any value.
- **Version comes from the live engine**, never a constant. Claiming a newer Chrome than
  the bundled Chromium fails plain feature detection. Only the patch component — which
  nothing feature-detects — is seed-derived.
- **Per-account machines.** GPU, CPU/memory, display and OS build are derived from the
  provider-account row id, drawn as coherent units (no 4-core laptop claiming an RTX
  4070). Same account ⇒ same machine forever; different accounts ⇒ different hardware.
  This matters because device correlation is how platforms link accounts: a fixed
  fingerprint means a restriction on one account can carry to the next. ~200 distinct
  identities, so it defeats *identical*-device matching, not a determined effort.
- **WebRTC leak prevention** at both the launch-switch and SDP-scrubbing level, with
  `RTCPeerConnection` left present and working — its absence is itself a fingerprint.

**Not mitigated: your IP address.** Every request comes from the host machine, and there
is no proxy support. After a restriction, that is the strongest remaining link between
one account and the next.

### Selector durability

LinkedIn's profile DOM uses build-hashed class names (`_02257691`, `d6f5ffc3`) that rotate
on every deploy, so nothing here depends on them. Extraction anchors on:

- `componentkey` — LinkedIn's server-driven-UI contract
  (`com.linkedin.sdui.profile.card.<urn>ExperienceTopLevelSection`)
- `entity-collection-item` for individual entries
- `data-testid` and visible heading text as fallbacks

Experience has two entry shapes: a grouped employer holding several roles, and a
standalone entry. The line before a date range is the *job title* in one and the *company*
in the other, so flat text parsing cannot work — container structure is what disambiguates.

Sections below the Activity feed (Experience, Education, Skills) hydrate lazily in seven
batches; the reader scrolls until they appear rather than a fixed number of screenfuls.

**When LinkedIn redesigns, this will break.** On failure the provider writes the full DOM
and a screenshot to `backend/_debug/profile-extraction-empty-*.{html,png}`. That dump is
how the current selectors were derived and makes re-tuning a short job rather than a
rediscovery.

---

## Quick start (local, no Docker)

Requires **Python ≥ 3.12** and **Node ≥ 18**. Neither Postgres nor Redis is needed for
local dev: the backend defaults to SQLite and runs Celery tasks inline.

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium                             # only for PROVIDER=linkedin

cp ../.env.example .env                                 # then edit .env (see below)
# Generate an encryption key and paste it into CREDENTIAL_ENC_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- API + interactive docs: http://localhost:8000/docs

> **Run it from `backend/`, not the repo root.** Four things resolve relative to the
> working directory, and the wrong one fails silently rather than loudly:
> `.env` (wrong dir ⇒ `PROVIDER=mock`), `dev.db` (⇒ empty database, no stored session),
> `_state/` (⇒ **a fresh 20-profile budget, bypassing the rate limit**), and `_debug/`.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

- Web app: http://localhost:3000

`AUTH_DISABLED=true` (the dev default) runs the whole flow without configuring Supabase —
create a search, watch it progress live, and browse ranked results.

### Running a LinkedIn search

1. Set `PROVIDER=linkedin` and `SCRAPE_HEADLESS=false` in `backend/.env`.
2. Start both servers, open http://localhost:3000/search/new, pick **LinkedIn**.
3. A Chromium window opens. Sign in and clear any CAPTCHA. Leave it open.
4. The search proceeds; the session is saved so later runs skip the login.

> With the dev default `CELERY_TASK_ALWAYS_EAGER=true`, the search runs **inside the HTTP
> request** — the browser appears to hang on submit until the whole search finishes
> (roughly 30–60s per profile). That is expected. Run a real Celery worker against Redis
> for background execution. Keep **max results ≤ 3** while testing.

---

## Configuration

Every setting is an environment variable, documented in [`.env.example`](./.env.example).
Key switches:

| Variable                       | Purpose                                                   |
| ------------------------------ | --------------------------------------------------------- |
| `PROVIDER`                     | Default data source: `mock`, `linkedin`, or `apify`        |
| `SCRAPE_MAX_PROFILES_PER_HOUR` | Hard scrape cap, persisted across restarts (20)            |
| `SCRAPE_RATE_LIMIT_MAX_WAIT_S` | How long a search waits for a slot before stopping early   |
| `SCRAPE_HEADLESS`              | Must be `false` for `linkedin` — you sign in by hand       |
| `SCRAPE_LOGIN_TIMEOUT_S`       | How long the window waits for you to sign in (600)         |
| `SCRAPE_HUMANIZE`              | Human-behaviour emulation on/off (`true`)                  |
| `SCRAPE_BEHAVIOR_SEED`         | Seed the behaviour RNG for reproducible runs               |
| `SCRAPE_FETCH_ALL_SKILLS`      | Follow "Show all" for the full skills list (`true`)        |
| `SCRAPE_TIMEZONE`              | IANA tz reported to the page; blank keeps the host's       |
| `APIFY_TOKEN`                  | Apify API token — required for the `apify` provider        |
| `AI_MATCHING`                  | `off` (default) or `on` — Claude semantic scoring          |
| `PROFILE_TTL_DAYS`             | Reuse a cached candidate profile fetched within N days     |
| `SCRAPE_MAX_PROFILES`          | Safety ceiling on profiles fetched per search              |
| `AUTH_DISABLED`                | Dev-only: skip Supabase JWT verification, inject a dev user |

## Testing

```bash
cd backend
pytest        # 187 tests
```

Covers scoring, experience merging, skills, filtering, providers, the API, the
motion/timing/typing models, the rate limiter, fingerprint derivation, and LinkedIn
extraction against synthetic fixtures reproducing the live DOM structure.

Frontend type-checking:

```bash
cd frontend
npm run typecheck
```

> The extraction fixtures are **synthetic**. No scraped profile is committed — warehousing
> someone's LinkedIn data in the repo would contradict `COMPLIANCE.md`.

## Project structure

```
backend/
  app/
    api/         FastAPI routes (search, candidates, dashboard, health)
    domain/      scoring · filtering · experience · skills · prefilter  (pure, no I/O)
    providers/   mock · playwright_linkedin · apify_linkedin · factory (CandidateProvider impls)
                 human · human_motion · fingerprint · rate_limit  (scraping behaviour layer)
    services/    search pipeline, candidate persistence, search CRUD
    db/          SQLAlchemy models, enums, session
    workers/     Celery app + tasks
  tests/
frontend/
  app/           Next.js App Router pages (search, results, settings, dashboard)
  components/    UI + search form
  lib/           API client, TanStack Query hooks, types
```

Adding a new data source is one class implementing `search()` + `fetch_profile()`, plus one
branch in `providers/factory.py` — nothing else in the app changes.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Every candidate scores a flat low number with `skills: 0` | Skill matching is literal — see the note under [How matching works](#how-matching-works) |
| Profiles stored with no headline/experience | Selector drift. Check `backend/_debug/profile-extraction-empty-*.html` |
| "only one usage of each socket address" | A server is already on that port; stop it first |
| Search hangs on submit | Expected with `CELERY_TASK_ALWAYS_EAGER=true` — the search runs in the request |
| "LinkedIn has RESTRICTED this account" | Terminal. Requires government-ID verification with LinkedIn; no retry helps |
| Rate limit seems not to apply | You are probably running from the repo root, so `_state/` resolves elsewhere |

## Compliance & data handling

Candidate profiles are personal data. Depending on jurisdiction (GDPR, CCPA, …) you may
need a lawful basis, a retention policy, and a deletion path. The local database, browser
sessions, and any raw provider dumps are git-ignored and must not be committed. See
[`COMPLIANCE.md`](./COMPLIANCE.md) before deploying or processing real candidate data.
