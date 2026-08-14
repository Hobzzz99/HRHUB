# Runbook — what to do when something breaks

`DEPLOYMENT.md` sets the system up. This is for afterwards.

Every entry below is a failure that has either already happened or that the code
makes possible. Start with **"A recruiter says their search did nothing"** — that
is the report you will actually get, and it has several different causes.

---

## First: is it the app, or is it LinkedIn?

```bash
# On the server
curl -sf https://your-domain/api/ready | jq        # 503 = a dependency is down
docker compose -f docker-compose.prod.yml ps       # all healthy?
```

`/ready` checks Postgres and Redis. `/health` deliberately does not — it answers
200 as long as the process is alive, so never use it to judge whether the system
is working.

---

## "A recruiter says their search did nothing"

**The app now tells you which of these it was.** Open the search and read it:

| What the screen says | What happened | What to do |
|---|---|---|
| "These results are not what you asked for" | A filter did not reach LinkedIn. The results are real but unfiltered | Follow the on-screen instruction: run the search on LinkedIn, tick the firms, paste that URL into the form. Then see *Filter panel stopped working* below |
| "No candidates matched" **with** a breakdown | The scraper worked; the criteria were too tight | The breakdown names the filter to loosen — usually the credential or the employer |
| "Stopped early — hourly scrape limit reached" | The 20/hour cap | Nothing to fix. It says when the next slot frees |
| "Stopped — the LinkedIn account was restricted" | LinkedIn locked the account | See *An account was restricted* |
| "This search stopped unexpectedly" | Their laptop or worker died mid-run | Their worker is not running. See *A recruiter's searches never start* |
| Still "Running" after an hour | Task time limit is 60 min; the sweep marks it failed after 70 | Check their worker window for a stack trace |

If the screen says none of those and there is genuinely nothing, it is what it
says: nobody in the pool matched.

---

## A recruiter's searches never start (stuck on "Queued")

Their laptop is the only machine that can run their searches — by design, since
it holds their LinkedIn session.

1. Is their worker window open? It prints the queue it serves on startup.
2. Is `tunnel.ps1` still running? The worker cannot reach Redis without it.
3. On their laptop: `cd infra\worker-pc; .\preflight.ps1` — it checks Python,
   Chromium, the tunnel, the state directory and the power settings, and prints
   the fix for each failure.
4. Confirm the `WORKER_USER_ID` it prints belongs to **the person sitting
   there**. Copying a colleague's `.env.worker` makes this laptop run their
   searches against the wrong LinkedIn account, and nothing server-side
   prevents it.

To see what is queued:

```bash
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" --no-auth-warning -n 1 KEYS 'user-*'
```

---

## An account was restricted

The run stops, the account is retired, and everything collected before it is
kept. This is not recoverable in the app — only the account's owner can clear it
with LinkedIn, usually by submitting identity documents.

Before issuing a replacement, read `COMPLIANCE.md`. Two accounts have been lost
at 20 profiles/hour, and the replacement is more exposed than the last: the IP is
unchanged. Rotating is a decision, not a routine.

Settings → **Connect a different account** retires the current one and prompts a
fresh sign-in on the next search.

---

## Filter panel stopped working

LinkedIn changes its markup without notice; this has broken twice. Symptom: the
degraded banner saying a filter could not be applied.

The evidence is already on the recruiter's laptop:

```
backend\_debug\company-filter-*.html    (the page as it was)
backend\_debug\company-filter-*.png     (what it looked like)
```

Search the HTML for `Current compan`. If it is **absent**, the filter bar had not
rendered — a timing problem. If it is **present**, the selectors no longer match
it; the markup around it is what they need to become. Both previous breakages
were this, and both times the pill had become a different element type.

Selectors live in `backend/app/providers/company_filter.py`. Anchor on
`aria-label` and `role`, never on class names — LinkedIn's are build-hashed and
rotate on every deploy.

Meanwhile recruiters can paste a LinkedIn URL with the filter applied, which
uses ids LinkedIn resolved itself and cannot pick the wrong company entity.

---

## Extraction returns empty profiles

Symptom: candidates come back with no experience or skills and score near zero;
the degraded banner mentions incomplete profiles.

Look for `backend\_debug\profile-extraction-empty-*.png`.

**Do not just fix the selectors and re-run.** Profiles are cached for
`PROFILE_TTL_DAYS` (7 by default), so a run affected by drift poisons the cache
and the fixed code will serve the same empty rows back. Clear the affected
candidates first:

```sql
DELETE FROM candidates WHERE headline IS NULL AND current_title IS NULL;
```

---

## Backups

The dump runs at 02:00 by cron. Failure writes to `/var/log/tf-backup.log` and
nowhere else, so **check it deliberately** — a month of failures looks exactly
like a month of successes.

```bash
ls -lh /opt/talentfinder/backups | tail -5     # yesterday's should be there
tail -20 /var/log/tf-backup.log
```

Restore:

```bash
gunzip -c backups/talentfinder-YYYY-MM-DD.sql.gz \
  | docker compose -f docker-compose.prod.yml exec -T postgres \
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

**Rehearse this at least once**, on a copy, before you need it. An untested
backup is an assumption.

Redis is not backed up. Searches queued for an offline laptop live only there —
if Redis is lost, those searches stay "queued" until the sweep fails them, and
the recruiter re-runs them.

---

## "Please delete my data" (a candidate, not a recruiter)

Find them in any search that returned them, open the candidate, and delete.
That removes the profile, every search result referencing it, and every
recruiter's bookmark of it.

By API:

```bash
curl -X DELETE https://your-domain/api/candidate/<candidate_id> \
     -H "Authorization: Bearer <a recruiter's token>"
```

The deletion is logged as `candidate_forgotten` with the profile URL — that log
line is the only remaining evidence the request was honoured, so keep it.

Routine retention runs by itself: `raw` payloads are pruned past the cache
window, and profiles nothing references are deleted after
`CANDIDATE_RETENTION_DAYS` (180).

---

## Offboarding a recruiter

1. Delete their user in Supabase (Authentication → Users) — this stops the login.
2. On their laptop, stop the worker and delete `infra\worker-pc\.env.worker`,
   which holds the database password and the session encryption key.
3. Their stored LinkedIn session lives in `provider_accounts`. Remove it:

```sql
DELETE FROM provider_accounts WHERE user_id = '<their-user-id>';
```

Their searches and saved lists remain. Delete the `users` row instead if you
want those gone too — it cascades.

---

## Where the logs are

| What | Where |
|---|---|
| API, including the sweeps | `docker compose logs api` |
| **Worker — the only place stack traces land** | `<SCRAPE_STATE_DIR>\..\logs\worker-YYYY-MM-DD.log` on the recruiter's laptop, kept 14 days |
| Scraper page dumps | `backend\_debug\` on the recruiter's laptop |
| Caddy access log | `docker compose exec caddy cat /data/access.log` |

The worker log is the one that matters when a search misbehaves, and it is on a
laptop rather than the server. Ask for the file.
