"""
Seed the company registry from all sources.

Inputs (data/sources/):
  - websites.tsv              (TechBehemoths: name, slug, status, website)
  - new_domains_goodfirms.txt (GoodFirms domains, one per line)
  - itprofiles_domains.txt    (ITProfiles domains, one per line)
  - manual_domains.txt        (manual list of major software houses)

Output: data/companies.json (validated career-page registry)

Resolution order per domain:
  1. discovery.resolve_career_url  (homepage links + common paths + sitemap)
  2. DDG-lite/Bing site-search fallback for the ones still unresolved

Usage:
    python scripts/seed_companies.py [--skip-search]
"""
from __future__ import annotations

import asyncio
import base64
import io
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Settings, load_env          # noqa: E402
from src.discovery import CompanyDiscovery         # noqa: E402
from src.models import Company                     # noqa: E402
from src.storage import CompaniesStore             # noqa: E402

OUT = ROOT / "data" / "companies.json"
SRC = ROOT / "data" / "sources"        # registry build inputs (TSV/TXT)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"

SEARCH_ENGINES = (
    "https://lite.duckduckgo.com/lite/?q=",
    "https://html.duckduckgo.com/html/?q=",
    "https://www.bing.com/search?mkt=en-US&setlang=en-US&cc=us&q=",
)


def _base(netloc: str) -> str:
    parts = netloc.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else netloc


def load_rows() -> list[tuple[str, str]]:
    """(name, domain) pairs, deduped by registrable domain."""
    rows: dict[str, str] = {}

    tsv = SRC / "websites.tsv"
    if tsv.exists():
        with io.open(tsv, encoding="utf-8-sig") as f:
            f.readline()
            for line in f:
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) >= 4 and cols[2] == "ok" and cols[3]:
                    base = _base(cols[3])
                    if base and base not in rows:
                        rows[base] = cols[0]

    for fname in (
        "new_domains_goodfirms.txt",
        "itprofiles_domains.txt",
        "manual_domains.txt",
    ):
        p = SRC / fname
        if not p.exists():
            continue
        for line in io.open(p, encoding="utf-8", errors="replace"):
            d = line.strip().lower()
            if not d or "." not in d:
                continue
            d = d.split("/")[0]
            if d.startswith("www."):
                d = d[4:]
            if d not in rows:
                label = d.rsplit(".", 1)[0]
                rows[d] = label.replace("-", " ").title()

    return sorted((v, k) for k, v in rows.items())


def site_search_career(domain: str) -> str:
    """Search-engine fallback: site:domain careers -> first same-site/ATS URL."""
    query = quote_plus(f"site:{domain} careers OR jobs")
    for engine in SEARCH_ENGINES:
        try:
            proc = subprocess.run(
                ["curl", "-sL", "--compressed", "--max-time", "20",
                 "-A", UA, engine + query],
                capture_output=True, timeout=30,
            )
            html = proc.stdout.decode("utf-8", errors="replace")
        except Exception:
            continue
        hrefs = re.findall(r'href="(https?://[^"]+)"', html)
        cites = re.findall(r"<cite[^>]*>([^<]+)</cite>", html)
        candidates = []
        for h in hrefs:
            h = h.replace("&amp;", "&")
            if "duckduckgo" in h or "bing.com" in h or "google" in h:
                # Bing organic results: bing.com/ck/a?...&u=a1<base64url>
                m = re.search(r"u=a1([A-Za-z0-9_-]{16,})", h)
                if m:
                    b64 = m.group(1)
                    b64 += "=" * (-len(b64) % 4)
                    try:
                        dec = base64.urlsafe_b64decode(b64).decode(
                            "utf-8", errors="replace"
                        )
                        if dec.startswith("http"):
                            candidates.append(dec)
                    except Exception:
                        pass
                continue
            candidates.append(h)
        for c in cites:
            c = c.strip()
            if c and "." in c:
                candidates.append("https://" + c if "://" not in c else c)
        for cand in candidates[:10]:
            try:
                netloc = urlparse(cand).netloc.lower()
            except ValueError:
                continue
            if netloc.endswith("." + domain) or netloc == domain:
                return cand
            if any(
                netloc == a or netloc.endswith("." + a)
                for a in CompanyDiscovery.ATS_HOSTS
            ):
                return cand
        time.sleep(1.0)
    return ""


async def search_fallback(
    disc: CompanyDiscovery, results: dict[str, str], unresolved: list[tuple[str, str]]
) -> int:
    """DDG/Bing fallback pass. Returns count of newly resolved."""
    fixed = 0
    for i, (name, domain) in enumerate(unresolved, 1):
        found = await asyncio.to_thread(site_search_career, domain)
        if found and await disc._validate_career_url(found):
            results[domain] = found
            fixed += 1
            print(f"  [search] {domain} -> {found}", flush=True)
        if i % 25 == 0:
            print(f"  search progress: {i}/{len(unresolved)} (+{fixed})", flush=True)
        time.sleep(2.0 + (i % 3))
    return fixed


async def main() -> int:
    load_env()
    settings = Settings.from_file()
    # seed ke liye fast settings (dead domains jaldi skip ho jayen)
    settings.batch_size = 60
    settings.request_timeout = 10
    settings.request_delay = 0.1
    settings.max_retries = 0
    disc = CompanyDiscovery(settings)
    skip_search = "--skip-search" in sys.argv

    rows = load_rows()
    print(f"domains to resolve: {len(rows)}", flush=True)

    # resume: pehle se resolved career URLs wapas lo
    results: dict[str, str] = {}
    store = CompaniesStore(OUT)
    if OUT.exists():
        try:
            for prev in store.load_companies():
                if prev.career_url:
                    site = prev.website.replace("https://", "").replace("http://", "")
                    if site.startswith("www."):
                        site = site[4:]
                    results[site] = prev.career_url
        except Exception:
            pass
    todo = [(n, s) for n, s in rows if s not in results]
    print(f"resume: {len(results)} already resolved, {len(todo)} to do", flush=True)

    from src.fetcher import chunked

    batch_no = 0
    for batch in chunked(todo, settings.batch_size):
        batch_no += 1
        tasks = [disc.resolve_career_url(site) for _, site in batch]
        got = await asyncio.gather(*tasks, return_exceptions=True)
        for (name, site), result in zip(batch, got):
            if not isinstance(result, Exception) and result and result[0]:
                results[site] = result[0]
        print(
            f"batch {batch_no}: resolved={len(results)}/{len(rows)}",
            flush=True,
        )

    if not skip_search:
        unresolved = [(n, s) for n, s in rows if s not in results]
        print(f"search-engine fallback for {len(unresolved)} domains", flush=True)
        n = await search_fallback(disc, results, unresolved)
        print(f"search fallback resolved: {n}", flush=True)

    companies = [
        Company(
            name=name,
            website=f"https://{site}",
            career_url=results.get(site, ""),
            source="lahore-registry",
            notes="" if results.get(site) else "no career page found",
        )
        for name, site in rows
    ]
    store = CompaniesStore(OUT)
    store.save_companies(companies)
    valid = [c for c in companies if c.career_url]
    print(
        f"DONE -> domains={len(companies)} career_pages={len(valid)} "
        f"(registry: {OUT})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

