# Lahore Entry-Level Data Job Alerts

Lahore (Pakistan) ki software companies ke **verified career pages** ko scrape
karta hai, **entry-level (0–2 years) data roles** filter karta hai, aur naye
jobs par **email alert** bhejta hai. OCI server par cron ke zariye har 8 ghante
chalta hai.

> Status: live — 253 verified career pages, 33/33 tests pass, cron active.

---

## Yeh system kya karta hai

```text
data/companies.json (253 verified career pages)
        │
        ▼
  Fetcher  ──►  Parser  ──►  Matcher  ──►  detail-verify  ──►  Notifier
 (aiohttp/curl) (jobs)     (0-2 yrs)     (job page par         (email)
                                          experience check)
                                            │
                                            ▼
                                     data/seen_jobs.json (dedupe)
```

1. **Fetcher** — har career page download karta hai (aiohttp; Cloudflare-blocked
   sites ke liye `curl` fallback).
2. **Parser** — job listings nikalta hai (HTML anchors, headings, ATS JSON).
3. **Matcher** — sirf entry-level data roles rakhta hai:
   - target role keyword ho (data engineer, scraper, analyst, ETL…)
   - senior/lead/manager/5+ years na ho
   - experience 0–2 years ho (ya junior/intern/fresher ho)
   - blog/news/services/articles pages reject
4. **detail-verify** — listing snippet mein experience na mile to job ke
   detail page par dobara check hota hai (HTML → plain text).
5. **Notifier** — sirf **naye** jobs ka email (dedupe `seen_jobs.json` se).

---

## Project structure

```text
lahore-job-alerts/
├── config.yaml              # saari settings (roles, keywords, limits, email)
├── run_alerts.sh            # cron wrapper (flock → scrape)
├── .env                     # secrets (Gmail app password) — git mein NAHI
├── .env.example             # template
├── requirements.txt
├── pytest.ini                # pytest config (testpaths + pythonpath)
├── DEPLOYMENT.md            # server setup + cron
├── TESTING.md               # tests + regression evidence
│
├── src/                     # application code
│   ├── main.py              # CLI (discover/validate/scrape/test-email/status)
│   ├── config.py            # config.yaml + .env → Settings
│   ├── fetcher.py           # HTTP fetch (+ curl fallback)
│   ├── parser.py            # career page → Job objects
│   ├── matcher.py           # entry-level data-role filter
│   ├── discovery.py         # homepage → career URL dhoondna
│   ├── notifier.py          # email (SMTP)
│   ├── models.py            # Company / Job + dedupe
│   └── storage.py           # JSON stores (registry, seen jobs)
│
├── scripts/                 # registry build tools (one-time / maintenance)
│   ├── fetch_websites.py    # TechBehemoths slug → real website
│   ├── seed_companies.py    # sources → companies.json
│   ├── resolve_pool.py      # domain list → career URL (verified)
│   ├── merge_pool.py        # pool_resolved.tsv → companies.json
│   ├── finalize_registry.py # live-check + cap → companies.json
│   └── scrape_clutch.py     # optional: Clutch se domain list
│
├── data/
│   ├── companies.json       # ✅ ACTIVE registry (app + cron)
│   ├── seen_jobs.json       # already-notified jobs (dedupe)
│   └── sources/             # registry build inputs (TSV/TXT)
│
├── tests/                   # pytest (parser + matcher)
└── logs/                    # cron.log (gitignored)
```

---

## Quick start (local)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/macOS
pip install -r requirements.txt

cp .env.example .env               # phir Gmail credentials bharein
python -m src.main status          # registry + email config check
python -m src.main scrape --dry-run   # email ke baghair test run
```

### CLI commands

| Command | Kaam |
|---|---|
| `python -m src.main status` | registry count, email config, notified jobs |
| `python -m src.main scrape` | asli run (naye matches par email) |
| `python -m src.main scrape --dry-run` | email ke baghair, sirf matches dekho |
| `python -m src.main scrape --limit 20` | sirf 20 companies check karo |
| `python -m src.main validate` | registry ke career URLs dobara verify |
| `python -m src.main discover` | naye Lahore companies + career pages dhoondo |
| `python -m src.main test-email` | SMTP credentials test |

### Tests

```bash
python -m pytest tests/ -q        # 33 tests
```

---

## Configuration (`config.yaml`)

Sab kuch yahan se control hota hai — code chhune ki zaroorat nahi:

| Key | Matlab |
|---|---|
| `max_experience_years: 2` | is se zyada experience wali jobs reject |
| `verify_detail_experience: true` | detail page par experience dobara verify |
| `target_roles` | kaunsi roles chahiye (data engineer, scraper, ETL…) |
| `blocked_keywords` | senior/lead/manager/5+ years → reject |
| `junior_hints` | junior/intern/fresher/0-2 → accept |
| `include_unstated_experience` | experience na likha ho to bhi accept |
| `max_companies` | ek run mein max companies |
| `email.subject` / `portfolio_url` | email ka subject + portfolio link |

Secrets `.env` mein rehte hain (git mein nahi): `GMAIL_USER`,
`GMAIL_APP_PASSWORD`, `GMAIL_TO`, `SMTP_HOST`, `SMTP_PORT`.

---

## Registry kaise banayi jaati hai

```bash
# 1) sources → companies.json
.venv/bin/python scripts/seed_companies.py

# 2) (optional) naye domains → career URLs
.venv/bin/python scripts/resolve_pool.py data/sources/pool_domains.txt
.venv/bin/python scripts/merge_pool.py

# 3) live-check + cap (dead links hata deta hai)
.venv/bin/python scripts/finalize_registry.py 500
```

`data/sources/` mein build inputs hain (`websites.tsv`, `pool_domains.txt`,
`pool_resolved.tsv`, GoodFirms/ITProfiles/manual domain lists).

---

## Deployment

Server setup, cron aur maintenance ke liye **[DEPLOYMENT.md](DEPLOYMENT.md)**
dekhein. Tests aur regression evidence ke liye **[TESTING.md](TESTING.md)**.