# HRHUB — Recruiter Candidate Search Platform

Enter your hiring requirements; HRHUB searches candidate profiles, extracts and scores
them against your criteria, and returns only the best matches — replacing hours of manual
profile review. The web app is branded **TalentFinder**.

The platform is **source-agnostic**: candidate data comes from a pluggable
`CandidateProvider`, so the app is not tied to any one site. It ships with:

- **`mock`** — deterministic fixtures. **No account, no network, no keys.** The default,
  and how the app is developed and tested.
- **`apify`** — real LinkedIn profiles fetched through the [Apify](https://apify.com) API.
  Apify runs the collection on its own infrastructure, so **no LinkedIn account is
  connected and nothing can get banned.** Needs an Apify API token.

> A legacy Playwright LinkedIn scraper also exists in the backend but is **disabled in the
> UI**. Scraping LinkedIn directly violates its Terms of Service and gets accounts
> restricted — see [`COMPLIANCE.md`](./COMPLIANCE.md). Use the Apify provider instead.

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

## Architecture

```
frontend/  Next.js 15 (App Router) · shadcn/ui · TanStack Query        → REST + SSE
backend/   FastAPI (REST + live SSE status)  and  a Celery worker  share one codebase
           providers/ (mock · apify) · domain/ (scoring, filtering) · db/ · api/ · services/
Postgres   candidate + search data          Redis   Celery broker/result backend
```

The search pipeline runs in a worker, isolated from the API: **provider search →
pre-filter → cache/fetch → score → filter → store**, with progress committed incrementally
so the UI reflects live state over SSE. Already-seen candidates are served from the
database (within `PROFILE_TTL_DAYS`) and never re-fetched — no data-source cost is spent
twice on the same person.

## Quick start (local, no Docker)

Requires **Python ≥ 3.12** and **Node ≥ 18**. Neither Postgres nor Redis is needed for
local dev: the backend defaults to SQLite and runs Celery tasks inline.

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp ../.env.example .env                                 # then edit .env (see below)
# Generate an encryption key and paste it into CREDENTIAL_ENC_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

alembic upgrade head
uvicorn app.main:app --reload
```

- API + interactive docs: http://localhost:8000/docs

To use real LinkedIn data, create an Apify token at
[console.apify.com](https://console.apify.com/account/integrations) (free tier included)
and set `APIFY_TOKEN` in `.env`. Without it, the app runs fully on the `mock` provider.

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

## Configuration

Every setting is an environment variable, documented in [`.env.example`](./.env.example).
Key switches:

| Variable           | Purpose                                                        |
| ------------------ | ------------------------------------------------------------- |
| `PROVIDER`         | Default data source: `mock` (default) or `apify`             |
| `APIFY_TOKEN`      | Apify API token — required for the `apify` provider          |
| `AI_MATCHING`      | `off` (default) or `on` — Claude semantic scoring            |
| `PROFILE_TTL_DAYS` | Reuse a cached candidate profile fetched within N days       |
| `SCRAPE_MAX_PROFILES` | Safety ceiling on profiles fetched per search             |
| `AUTH_DISABLED`    | Dev-only: skip Supabase JWT verification, inject a dev user  |

## Testing

```bash
cd backend
pytest        # 92 tests: scoring, experience, skills, filtering, providers, API
```

Frontend type-checking:

```bash
cd frontend
npm run typecheck
```

## Project structure

```
backend/
  app/
    api/         FastAPI routes (search, candidates, dashboard, health)
    domain/      scoring · filtering · experience · skills · prefilter  (pure, no I/O)
    providers/   mock · apify_linkedin · factory  (CandidateProvider implementations)
    services/    search pipeline, candidate persistence, search CRUD
    db/          SQLAlchemy models, enums, session
    workers/     Celery app + tasks
  tests/
frontend/
  app/           Next.js App Router pages (search, results, settings, dashboard)
  components/     UI + search form
  lib/            API client, TanStack Query hooks, types
```

Adding a new data source is one class implementing `search()` + `fetch_profile()`, plus one
branch in `providers/factory.py` — nothing else in the app changes.

## Compliance & data handling

Candidate profiles are personal data. Depending on jurisdiction (GDPR, CCPA, …) you may
need a lawful basis, a retention policy, and a deletion path. The local database and any
raw provider dumps are git-ignored and must not be committed. See
[`COMPLIANCE.md`](./COMPLIANCE.md) before deploying or processing real candidate data.
