"""
Fetch real company websites from TechBehemoths profile pages (SSR HTML).

The profile page contains a "Visit Website" link in the contact-box:
    <a href="http://www.brainxtech.com?utm_source=Tech-Behemoths&utm_medium=Profile...">
We only accept links carrying utm_medium=Profile to avoid generic footer links.
Falls back to the Nuxt payload field:  website:"http:\\u002F\\u002Fwww.example.com"

Usage:
    python scripts/fetch_websites.py [input.tsv] [output.tsv]

Input : name<TAB>slug   (data/sources/tb_companies_all.tsv)
Output: name<TAB>slug<TAB>website
"""
import io
import re
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

TB_BASE = "https://techbehemoths.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CONCURRENCY = 12

# href="http://site?utm_source=...&utm_medium=Profile..."
RE_VISIT = re.compile(
    r'href="(https?://[^"?]+)\?[^"]*utm_medium=Profile', re.I)
# Nuxt payload: website:"http:\u002F\u002Fwww.site.com"
RE_PAYLOAD = re.compile(r'website:"(https?:\\u002F\\u002F[^"]+)"')
BAD_DOMAINS = re.compile(
    r"techbehemoths\.com|facebook\.com|twitter\.com|x\.com|linkedin\.com|"
    r"instagram\.com|youtube\.com|google\.com|apple\.com|wa\.me|whatsapp\.com",
    re.I)


def clean_url(raw: str) -> str:
    url = raw.encode().decode("unicode_escape") if "\\u002F" in raw else raw
    url = url.strip()
    host = urllib.parse.urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host


def curl(url: str) -> str:
    """Fetch page via curl (aiohttp gets 403-blocked by Cloudflare)."""
    try:
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "30", "-A", UA, url],
            capture_output=True, timeout=35)
        return proc.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_website(html: str) -> str:
    m = RE_VISIT.search(html)
    if m:
        return clean_url(m.group(1))
    m = RE_PAYLOAD.search(html)
    if m:
        return clean_url(m.group(1))
    return ""


def fetch_one(slug):
    html = curl(f"{TB_BASE}/company/{slug}")
    if not html:
        return slug, "empty", ""
    site = extract_website(html)
    if not site or BAD_DOMAINS.search(site):
        return slug, "no-website", ""
    return slug, "ok", site


def main(inp, outp):
    rows = []
    with io.open(inp, encoding="utf-8-sig") as f:
        f.readline()
        for line in f:
            cols = line.strip().split("\t")
            if len(cols) >= 2:
                rows.append((cols[0], cols[1]))
    print(f"companies to process: {len(rows)}", flush=True)

    status_by_slug = {}
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        for i, (slug, st, site) in enumerate(
                pool.map(fetch_one, [s for _, s in rows]), 1):
            status_by_slug[slug] = (st, site)
            if i % 50 == 0:
                print(f"  progress {i}/{len(rows)}", flush=True)

    ok = no_site = err = 0
    with io.open(outp, "w", encoding="utf-8", newline="") as f:
        f.write("name\tslug\tstatus\twebsite\n")
        for name, slug in rows:
            st, site = status_by_slug.get(slug, ("missing", ""))
            if st == "ok":
                ok += 1
            elif st == "no-website":
                no_site += 1
            else:
                err += 1
            f.write(f"{name}\t{slug}\t{st}\t{site}\n")
    print(f"done: ok={ok} no-website={no_site} failed={err} -> {outp}")


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/sources/tb_companies_all.tsv"
    outp = sys.argv[2] if len(sys.argv) > 2 else "data/sources/websites.tsv"
    main(inp, outp)
