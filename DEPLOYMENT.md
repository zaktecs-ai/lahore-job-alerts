# Deployment Guide — Lahore Job Alerts (OCI Server)

Plain-English, low-complexity setup. Copy-paste ready.

## 1. Layout on the server — ONE self-contained folder

The whole project lives in a **single top-level folder**: `~/lahore-job-alerts/`
(nothing outside it — no stray archives, no nested wrapper dir).

```
~/lahore-job-alerts/
├── src/            (Python code)
├── scripts/        (registry-build helpers)
├── tests/          (unit tests)
├── data/           (companies.json + seen_jobs.json + sources/)
├── logs/           (cron.log)
├── run_alerts.sh   (cron wrapper — lives INSIDE the project)
├── config.yaml  requirements.txt  .env  .env.example
└── .venv/          (virtualenv)
```

Upload changed files straight into that folder — no tarball needed (tarballs
were only used during the initial bootstrap and have been deleted):

```bash
cd "/e/Silverlight Group Work/lahore-job-alerts"
scp src/config.py oci:~/lahore-job-alerts/src/     # example: one file
# or mirror the folder (Git Bash / PowerShell):
ssh oci "mkdir -p ~/lahore-job-alerts/src ~/lahore-job-alerts/scripts"
scp -r src scripts tests config.yaml requirements.txt \
    oci:~/lahore-job-alerts/
```

## 2. One-time server setup (SSH)

```bash
ssh oci
cd ~/lahore-job-alerts

# system deps (Ubuntu)
sudo apt-get update -y && sudo apt-get install -y python3-venv curl cron

# virtualenv + packages
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Secrets (.env) — NEVER commit these

```bash
cd ~/lahore-job-alerts
cp .env.example .env
nano .env
```

Fill in:

```
GMAIL_USER=ranazak73@gmail.com
GMAIL_APP_PASSWORD=<16-char Gmail App Password>
GMAIL_TO=zakriarajpoot73@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
LOG_LEVEL=INFO
```

> Gmail App Password: Google Account → Security → 2-Step Verification ON →
> App Passwords → generate 16-char password (spaces hata dein).
> Normal Gmail password will NOT work.

## 4. Smoke test on server

```bash
cd ~/lahore-job-alerts
# 1. config sanity
.venv/bin/python -m src.main status

# 2. test email delivery (sends a test alert)
.venv/bin/python -m src.main test-email

# 3. one manual scrape run over the registry (does NOT send real alerts
#    with --dry-run)
.venv/bin/python -m src.main scrape --dry-run

# 4. real run (sends email if matches found)
.venv/bin/python -m src.main scrape
```

Expected: `status` shows company count, `test-email` lands in
zakriarajpoot73@gmail.com inbox (check Spam once and mark "not spam").

## 5. Cron — every 8 hours (ALREADY INSTALLED on this server)

Wrapper script `~/lahore-job-alerts/run_alerts.sh` runs the scraper with a lock
(flock) so overlapping runs can't pile up. Installed crontab line:

```
0 */8 * * * /home/ubuntu/lahore-job-alerts/run_alerts.sh
```

Runs at 00:00, 08:00, 16:00 server time (OCI default is UTC —
add `CRON_TZ=Asia/Karachi` on its own line above to switch to PKT).

## 6. Verify cron works

```bash
# manual wrapper test (same path cron uses):
~/lahore-job-alerts/run_alerts.sh
tail -20 ~/lahore-job-alerts/logs/cron.log

# after a scheduled slot:
grep CRON /var/log/syslog | tail -5
tail -20 ~/lahore-job-alerts/logs/cron.log
```

## 7. Maintenance

| Task | Command |
|---|---|
| See current stats | `.venv/bin/python -m src.main status` |
| Manual run | `.venv/bin/python -m src.main scrape` |
| Re-verify career links | `.venv/bin/python -m src.main validate` |
| Test email | `.venv/bin/python -m src.main test-email` |
| Update code | re-upload changed files, no restart needed (cron picks up next run) |

Log rotation is built in: `logs/cron.log` grows ~1 line per run; truncate
monthly with `: > logs/cron.log` if large.

## 8. Registry (career pages)

Active registry: `data/companies.json` — **253 live-verified career pages**
(app `config.yaml` -> `files.companies_file` isi file ko parhta hai).

Live-check + cap (dead links hata deta hai, purani file backup rehti hai):

```bash
.venv/bin/python scripts/finalize_registry.py 500
```

| File | Kya hai |
|---|---|
| `data/companies.json` | active registry (app + cron isi ko parhta hai) |
| `data/sources/pool_resolved.tsv` | resolver se nikle naye career URLs (merge input) |
| `data/sources/*.tsv,*.txt` | registry build inputs (websites, domains lists) |

Har entry ka career URL career-ish path par hai (`careers`, `jobs`, `vacancy`,
`apply` waghaira) — koi homepage fallback nahi. Ye verify kiya gaya hai:

```bash
.venv/bin/python -c "import json,re;d=json.load(open('data/companies.json'))['companies'];p=re.compile(r'career|job|vacanc|join|hiring|position|opening|work-with|recruit|apply|employ',re.I);print(len(d), sum(bool(p.search(c['career_url'])) for c in d))"
# -> 253 253
```

Latest verified dry-run (253 pages): `pages=253 jobs_found=568 matched=2
new=0 errors=0`.
