# Deploying TalentFinder for company use

This deploys the product with **the scraping you have now** — each recruiter
signs in to LinkedIn with their own account, on their own laptop, clearing the
CAPTCHA by hand.

## The shape, and why it is this shape

Sign-in and CAPTCHAs are cleared by a person in a visible browser window
(`SCRAPE_HEADLESS=false`). A server has no screen, so the scraper cannot live
there. It runs on each recruiter's laptop instead, and everything shared runs on
the server:

```
  Company server  (Linux VM, public)         Recruiters' laptops (Windows)
  ┌──────────────────────────────┐           ┌────────────────────────────┐
  │  Caddy  :443  TLS            │           │ Aya    → queue user-<aya>  │
  │    ├── /      → web  :3000   │           │   own LinkedIn account     │
  │    └── /api/* → api  :8000   │  SSH      │   own 20/hour budget       │
  │  Postgres :5432  loopback ───┼─ tunnel ─►├────────────────────────────┤
  │  Redis    :6379  loopback ───┼──────────►│ Omar   → queue user-<omar> │
  └──────────────────────────────┘           │   own LinkedIn account     │
        shared database,                     │   own 20/hour budget       │
        shared shortlists, one login         └────────────────────────────┘
```

**Throughput scales with recruiters.** Each laptop has its own account and its
own 20 profiles/hour. Five recruiters is 100 profiles/hour. The cap is per
account, not per company.

### Searches are routed, not shared

A recruiter's search runs **only on their own laptop**. Celery's default is the
opposite — every worker drains one shared queue — which here would hand a search
to a colleague's machine and load the originating recruiter's LinkedIn session
into a different browser on a different IP. Unusable, and close to the textbook
signal of a stolen account.

So each worker listens to `user-<their-id>` only. See
`backend/app/workers/routing.py`. This is why every laptop needs its own
`WORKER_USER_ID`.

If a recruiter's laptop is off, their searches wait in their queue until it is
back. That is deliberate: better than another account running them.

---

## Part 1 — The server

### 1.1 What you need

- A small Linux VM (2 vCPU / 4 GB is ample). Hetzner, DigitalOcean, or a
  machine in the office.
- A domain name, with an A record pointing at the VM's IP.
- Ports 80 and 443 open. **Nothing else.**
- Docker and the compose plugin.

### 1.2 Sign-in accounts

Auth is required in production and is not optional: `APP_ENV=prod` makes the API
ignore `AUTH_DISABLED` and enforce real JWT verification
(`backend/app/core/security.py`). Create a free project at
[supabase.com](https://supabase.com), then take **Project Settings → API** →
project URL and anon key.

Add each recruiter under **Authentication → Users → Add user**, ticking **Auto
Confirm User** — without it they wait forever on an email that never arrives.
**Note each one's user id**; it becomes `WORKER_USER_ID` on their laptop.

Turn **off** "Allow new users to sign up" (Authentication → Sign In / Providers
→ Email). The app has a login page but no sign-up page, and Supabase's signup
endpoint is public: anyone holding the anon key — which ships in every page load
— can otherwise create themselves an account without going near your URL.

### Which signing key your project uses

Current Supabase projects sign login tokens with an **asymmetric ES256 key**,
not the legacy shared secret. Check:

```bash
curl -s https://<your-project>.supabase.co/auth/v1/.well-known/jwks.json
```

- Keys shown with `"alg": "ES256"` or `"RS256"` → **leave `SUPABASE_JWT_SECRET`
  blank** and set `SUPABASE_JWKS_URL`. `security.py` prefers the secret whenever
  it is set, so a leftover value keeps the wrong path active.
- Empty key list → legacy project; set `SUPABASE_JWT_SECRET` instead.

The trap worth knowing: on a current project the *anon API key* is still an
HS256 JWT signed by the legacy secret, while *user login tokens* are ES256. The
secret therefore verifies the anon key perfectly and rejects every real login,
with the API logging `The specified alg value is not allowed`.

### 1.3 Configure

```bash
git clone <your-repo> /opt/talentfinder && cd /opt/talentfinder
cp .env.prod.example .env.prod
```

Fill in every `REPLACE_` value. Generate secrets properly:

```bash
openssl rand -base64 32                                    # each password
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Keep a copy of `CREDENTIAL_ENC_KEY`.** Losing it invalidates every stored
LinkedIn session. Every laptop must use the identical key.

### 1.4 Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Migrations run automatically on API start. Caddy obtains the certificate on
first request.

```bash
docker compose -f docker-compose.prod.yml ps            # all healthy?
curl -sf https://your-domain/api/ready && echo READY
```

Use `/ready`, not `/health`. Liveness answers 200 whatever the database is
doing — by design, so a blip does not get the process killed — which makes it
useless as a deploy gate. `/ready` checks Postgres and Redis and returns 503
when either is down, and it is what the compose healthcheck uses too.

### 1.5 Backups — now, not later

Profiles cost scrape budget to collect. The database is the one thing here that
cannot be rebuilt.

```bash
chmod +x infra/backup.sh
sudo crontab -e
# 0 2 * * * cd /opt/talentfinder && ./infra/backup.sh >> /var/log/tf-backup.log 2>&1
```

Set `BACKUP_REMOTE` in `.env.prod` to copy dumps off the machine.

---

## Part 2 — Each recruiter's laptop

Repeat per recruiter. Each needs a screen, a person, and to stay awake.

### 2.1 Install once

- **Python 3.12+** — tick "Add Python to PATH"
- **OpenSSH Client** — Settings → System → Optional features

```powershell
git clone <your-repo> C:\TalentFinder
cd C:\TalentFinder\backend
pip install .
playwright install chromium
```

### 2.2 Configure

```powershell
cd C:\TalentFinder\infra\worker-pc
copy .env.worker.example .env.worker
notepad .env.worker
```

Three things must be right:

| Setting | Value |
|---|---|
| `WORKER_USER_ID` | **This recruiter's** Supabase user id. Different on every laptop |
| `CREDENTIAL_ENC_KEY` | Identical to the server's |
| The two passwords | From the server's `.env.prod` |

`WORKER_USER_ID` is the one people get wrong by copying a colleague's file. The
worker refuses to start without it, but it cannot tell whether the id is the
right person's — so check it.

### 2.3 Run — two windows, both stay open

```powershell
# Window 1: the encrypted path to the server
.\tunnel.ps1 -Server talent.yourcompany.com -User deploy

# Window 2: the worker
.\start-worker.ps1
```

The worker prints the queue it is serving. Confirm it matches the recruiter
sitting at the machine.

When they start a search on the website, **Chromium opens on this laptop.** The
first run of the day asks for LinkedIn sign-in and a CAPTCHA, cleared by hand.
Nothing types a password.

### 2.4 Keep it awake

`powercfg /change standby-timeout-ac 0` — a sleeping laptop means that
recruiter's searches queue and never run.

---

## What is deliberately not automated

**The 20/hour cap.** Per account, and it is what keeps the account alive.
Raising it does not create capacity; it converts account lifetime into speed.
Two accounts have already been restricted at this setting. Adding recruiters is
how you add throughput.

**Account rotation.** A restriction is detected, the run stops, collected work is
kept, and the account is marked unusable. Issuing a replacement is a deliberate
step in Settings, because the honest response to a restriction is usually to stop
rather than burn the next account.

**Retention and deletion.** Not built. A shared company database of candidate
personal data carries deletion obligations that a local dev database did not.
This is a legal exposure rather than an inconvenience — see §15 of the briefing.

---

## Before switching it on for everyone

Company-wide deployment moves the LinkedIn terms-of-service breach from one
personal account to **every recruiter's personal account, at company
direction**. A restriction costs that person their own professional network, not
just a tool. `COMPLIANCE.md` covers the position; the owner should make this
call knowingly.
