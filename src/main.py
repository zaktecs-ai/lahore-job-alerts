"""
CLI entry point.

Commands:
  python -m src.main discover  [--pages N] [--limit M]   Lahore companies + career pages
  python -m src.main validate                            registry mein URLs dobara check
  python -m src.main scrape    [--dry-run] [--limit N]   main job-alert run
  python -m src.main test-email [--dry-run]              email setup test
  python -m src.main status                              system ka haal-chaal

Cron waala command:  python -m src.main scrape
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import Settings
from .discovery import CompanyDiscovery
from .fetcher import chunked
from .matcher import JobMatcher
from .models import Company, Job, dedupe_jobs
from .notifier import EmailNotifier
from .parser import parse_jobs_from_result
from .storage import CompaniesStore, SeenJobsStore

log = logging.getLogger("job_alerts")


# --------------------------------------------------------------------------
# logging setup
# --------------------------------------------------------------------------
def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# --------------------------------------------------------------------------
# discover / validate
# --------------------------------------------------------------------------
async def cmd_discover(settings: Settings, args: argparse.Namespace) -> int:
    disc = CompanyDiscovery(settings)
    companies = await disc.discover(pages=args.pages, limit=args.limit)

    store = CompaniesStore(settings.companies_file)
    store.save_companies(companies)

    valid = [c for c in companies if c.career_url]
    print("\n===== DISCOVERY SUMMARY =====")
    print(f"Websites found      : {disc.stats.domains_found}")
    print(f"Career pages (valid): {len(valid)}")
    print(f"Not found           : {disc.stats.career_failed}")
    print(f"Saved to            : {settings.companies_file}")
    for c in valid[:20]:
        print(f"  - {c.name or c.website:35s} {c.career_url}")
    if len(valid) > 20:
        print(f"  ... aur {len(valid) - 20} aur companies (companies.json dekhein)")
    return 0


async def cmd_validate(settings: Settings, args: argparse.Namespace) -> int:
    from .fetcher import Fetcher

    store = CompaniesStore(settings.companies_file)
    companies = store.load_companies()
    print(f"Validating {len(companies)} companies...")
    fetcher = Fetcher(settings)
    ok = bad = 0

    async def check(c: Company) -> tuple[Company, bool]:
        res = await fetcher.fetch(c.career_url)
        return c, res.ok
    for batch in chunked(companies, settings.batch_size):
        results = await asyncio.gather(*(check(c) for c in batch))
        for c, good in results:
            if good:
                ok += 1
            else:
                bad += 1
                c.career_url = ""
                c.notes = "link dead"
        print(f"\rok={ok} bad={bad}", end="", flush=True)
    print()
    store.save_companies(companies)
    print(f"VALIDATE DONE -> valid={ok} broken={bad}")
    return 0


# --------------------------------------------------------------------------
# scrape (main pipeline)
# --------------------------------------------------------------------------
async def cmd_scrape(settings: Settings, args: argparse.Namespace) -> int:
    store = CompaniesStore(settings.companies_file)
    companies = [c for c in store.load_companies() if c.career_url]
    if not companies:
        log.warning("Koi company with career_url nahi mili. Pehle 'discover' chalayein.")
        return 1
    if args.limit:
        companies = companies[: args.limit]
    companies = companies[: settings.max_companies]
    log.info("Scraping %d career pages (batch_size=%d)...", len(companies), settings.batch_size)

    from .fetcher import Fetcher

    fetcher = Fetcher(settings)
    matcher = JobMatcher(settings)
    seen_store = SeenJobsStore(settings.seen_jobs_file)
    notifier = EmailNotifier(settings)

    all_jobs: list[Job] = []
    checked = errors = 0
    for batch in chunked(companies, settings.batch_size):
        results = await fetcher.fetch_many([c.career_url for c in batch])
        for company, res in zip(batch, results):
            checked += 1
            if not res.ok:
                errors += 1
                continue
            jobs = parse_jobs_from_result(
                res.text, res.content_type, res.url,
                company.name or company.website,
            )
            all_jobs.extend(jobs)
        log.info("Checked %d/%d | errors=%d | jobs-so-far=%d",
                 checked, len(companies), errors, len(all_jobs))

    # filter + dedupe
    matched = dedupe_jobs([
        job for job in all_jobs if matcher.match(job).is_match
    ])

    # ---- Stage-2 verify: job detail page par experience confirm karo ----
    # Listing ka snippet aksar experience na dikhaye; detail page par
    # "4-6 years" jaisi requirement hidden ho sakti hai. Yahan pakro.
    if settings.verify_detail_experience and matched:
        from .matcher import extract_experience
        from .parser import html_to_text

        verified: list[Job] = []
        for job in matched:
            res = await fetcher.fetch(job.url)
            if not res.ok:
                verified.append(job)  # detail na khule to listing ka faisla
                continue
            # HTML tags hata kar plain text par check karo — warna
            # "Experience: </strong></span><span>4-6" jaisi tag-split value
            # regex ko miss ho jati hai (Arpatech 4-6 yrs bug). Poora page
            # dekho, sirf pehle 30k chars nahi (page 136KB tha).
            lo, _hi = extract_experience(html_to_text(res.text)[:200_000])
            if lo is not None and lo > settings.max_experience_years:
                log.info(
                    "detail-verify REJECT %s (%s) -> needs %s+ years",
                    job.company, job.title, lo,
                )
                continue
            verified.append(job)
        log.info("detail-verify: %d -> %d candidates",
                 len(matched), len(verified))
        matched = verified

    # har match log karo (new + already-seen) — quality verify ke liye
    for job in matched:
        log.info("MATCH: %s | %s | %s | %s",
                 job.company, job.title[:70], matcher.match(job).reason, job.url[:90])

    new_jobs = [j for j in matched if not seen_store.is_seen(j)]

    log.info("== SUMMARY: pages=%d jobs_found=%d matched=%d new=%d ==",
             checked, len(all_jobs), len(matched), len(new_jobs))

    # mark seen only when NOT dry-run (taake dry-run dobara chal sake)
    if not args.dry_run:
        seen_store.mark_seen(matched)

    if new_jobs:
        sent = notifier.send_job_alert(
            new_jobs, dry_run=args.dry_run or not settings.email.enabled
        )
        for job in new_jobs:
            print(f"\n  [MATCH] {job.company} — {job.title}\n          {job.url}")
        return 0 if sent else 1
    print("No new matching jobs this run.")
    return 0


# --------------------------------------------------------------------------
# test-email / status
# --------------------------------------------------------------------------
def cmd_test_email(settings: Settings, args: argparse.Namespace) -> int:
    notifier = EmailNotifier(settings)
    ok = notifier.send_test(dry_run=args.dry_run)
    return 0 if ok else 1


def cmd_status(settings: Settings) -> int:
    store = CompaniesStore(settings.companies_file)
    companies = store.load_companies()
    valid = [c for c in companies if c.career_url]
    seen = SeenJobsStore(settings.seen_jobs_file)
    print("======== JOB ALERT SYSTEM — STATUS ========")
    print(f"Companies in registry : {len(companies)}")
    print(f"  with career URL     : {len(valid)}")
    print(f"Jobs already notified : {seen.count()}")
    print(f"Email enabled         : {settings.email.enabled}")
    print(f"Email configured      : {settings.email.is_configured()}")
    print(f"Target roles          : {len(settings.target_roles)}")
    print(f"Batch size            : {settings.batch_size}")
    return 0


# --------------------------------------------------------------------------
# argument parsing + entry
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="job_alerts", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="Lahore companies + career pages dhoondo")
    d.add_argument("--pages", type=int, default=None, help="listing pages (default all 22)")
    d.add_argument("--limit", type=int, default=None, help="max companies")
    d.set_defaults(fn=cmd_discover)

    v = sub.add_parser("validate", help="registry ke career URLs dobara verify karo")
    v.set_defaults(fn=cmd_validate)

    s = sub.add_parser("scrape", help="main alert run (cron isi ko chalata hai)")
    s.add_argument("--dry-run", action="store_true", help="email ke baghair, sirf dekho")
    s.add_argument("--limit", type=int, default=None, help="sirf N companies check karo")
    s.set_defaults(fn=cmd_scrape)

    t = sub.add_parser("test-email", help="test email bhejo (credentials verify)")
    t.add_argument("--dry-run", action="store_true")
    t.set_defaults(fn=cmd_test_email)

    st = sub.add_parser("status", help="system ki halat dekho")
    st.set_defaults(fn=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_file()
    setup_logging(settings.log_level)
    if args.command == "status":
        return cmd_status(settings)
    if args.command == "test-email":
        return cmd_test_email(settings, args)
    return asyncio.run(args.fn(settings, args))


if __name__ == "__main__":
    sys.exit(main())