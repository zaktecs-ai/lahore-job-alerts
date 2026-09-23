"""
Scrape Lahore software companies from Clutch (clutch.co/pk/developers).

Har page ~85 providers, total ~1,448 companies (~17 pages).
Regular listings ka website link r.clutch.co/redirect?...&u=<real-site>
mein hota hai (URL-encoded). PPC/spotlight listings encrypted hain -> skip.

Output: data/clutch_companies.tsv  (name, website, city)

Usage:
    python scripts/scrape_clutch.py [max_pages]
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sources" / "clutch_companies.tsv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

PROVIDER_SPLIT = re.compile(r'data-provider-id="')
NAME_RE = re.compile(r"<h3[^>]*>\s*<a[^>]*>([^<]+)</a>", re.I)
CITY_RE = re.compile(r">[^<]{0,60}?([A-Z][\w\s-]{2,30}),\s*Pakistan\s*<")
HREF_RE = re.compile(r'href="(https://r\.clutch\.co/redirect\?[^"]+)"')


def fetch(url: str) -> str:
    proc = subprocess.run(
        ["curl", "-s", "--compressed", "--max-time", "40", "-A", UA, url],
        capture_output=True, timeout=50,
    )
    return proc.stdout.decode("utf-8", errors="replace")


def extract_website(block: str) -> str:
    """Regular redirect ka u= param asli website hota hai."""
    for m in HREF_RE.finditer(block):
        href = m.group(1).replace("&amp;", "&")
        u = re.search(r"[?&]u=([^&]+)", href)
        if not u:
            continue
        site = unquote(u.group(1)).strip()
        if "ppc.clutch.co" in site or "clutch.co" in site:
            continue
        p = urlparse(site)
        if p.scheme not in ("http", "https") or "." not in p.netloc:
            continue
        return p.netloc.removeprefix("www.")
    return ""


def parse_page(html: str) -> tuple[list[tuple[str, str, str]], tuple[int, int, int]]:
    """Parse one listing page.

    Returns (page_rows, (providers, lahore_with_site, lahore_total)).
    """
    blocks = PROVIDER_SPLIT.split(html)[1:]
    page_rows: list[tuple[str, str, str]] = []
    stats = [0, 0, 0]
    for block in blocks:
        stats[0] += 1
        name_m = NAME_RE.search(block[:6000])
        city_m = CITY_RE.search(block)
        city = city_m.group(1).strip() if city_m else ""
        is_lahore = (not city) or "lahore" in city.lower()
        if not is_lahore:
            continue
        stats[2] += 1
        site = extract_website(block)
        if site and name_m:
            stats[1] += 1
            page_rows.append((name_m.group(1).strip(), site, city))
    return page_rows, (stats[0], stats[1], stats[2])


def main() -> int:
    rows: list[tuple[str, str, str]] = []
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    seen_pages = 0
    for page in range(1, max_pages + 1):
        url = "https://clutch.co/pk/developers" + (f"?page={page}" if page > 1 else "")
        html = fetch(url)
        page_rows, (total, with_site, lahore) = parse_page(html)
        rows.extend(page_rows)
        if total == 0:
            print(f"page {page}: 0 providers -> stop", flush=True)
            break
        seen_pages = page
        print(
            f"page {page}: providers={total} lahore={lahore} with_site={with_site}",
            flush=True,
        )
        time.sleep(2.5)

    # dedupe by website, keep first name
    seen: dict[str, str] = {}
    for name, site, city in rows:
        seen.setdefault(site, f"{name}\t{city}")
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("name\twebsite\tcity\n")
        for site, name_city in seen.items():
            name, city = name_city.split("\t", 1)
            f.write(f"{name}\t{site}\t{city}\n")
    print(f"DONE pages={seen_pages} rows={len(rows)} unique_sites={len(seen)} -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
