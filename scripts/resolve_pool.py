"""
Fast career-page resolver for a pool of domains.

Kyun alag script: seed_companies.py har domain ke ~30 candidates ko
sequentially try karta hai (slow). Yeh script candidates ko priority
groups mein CONCURRENT validate karta hai -> 5-8x tez.

Usage:
    python scripts/resolve_pool.py data/sources/pool_domains.txt [concurrency]

Input : text file, ek domain per line
Output: data/sources/pool_resolved.tsv  (domain<TAB>career_url) -- append + resume-safe
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Settings, load_env          # noqa: E402
from src.discovery import CompanyDiscovery         # noqa: E402
from src.fetcher import chunked                    # noqa: E402

SRC = ROOT / "data" / "sources"
OUT = SRC / "pool_resolved.tsv"
GROUP = 5            # candidates per validation round
PER_DOMAIN_CAP = 70  # seconds; hard cap per domain


async def resolve_one(disc: CompanyDiscovery, domain: str) -> str:
    """Return verified career URL for a domain, else ''."""
    homepage = ""
    html = ""
    for host in (f"https://{domain}", f"https://www.{domain}", f"http://{domain}"):
        res = await disc.fetcher.fetch(host)
        if res and res.ok and res.text:
            homepage = host
            html = res.text if "html" in res.content_type else ""
            break
    if not homepage:
        return ""

    ordered: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        if u and u not in seen:
            seen.add(u)
            ordered.append(u)

    # 1) homepage ke career-jaisay links (sab se reliable)
    if html:
        for c in disc._homepage_career_links(html, homepage):
            add(c)
    # 2) common paths (config order = priority order)
    for path in disc.settings.career_path_candidates:
        add(urljoin(homepage, path))

    ordered = [u for u in ordered if disc._career_link_allowed(u, homepage)]

    # priority groups mein concurrent validate -> pehla valid jeet gaya
    for i in range(0, len(ordered), GROUP):
        grp = ordered[i:i + GROUP]
        got = await asyncio.gather(
            *(disc._validate_career_url(u) for u in grp), return_exceptions=True
        )
        for url, ok in zip(grp, got):
            if ok is True:
                return url

    # 3) aakhri koshish: sitemap se career URLs
    try:
        for sm in await disc._sitemap_career_urls(homepage):
            if await disc._validate_career_url(sm):
                return sm
    except Exception:
        pass
    return ""


async def main() -> int:
    load_env()
    settings = Settings.from_file()
    conc = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    # fast + polite: timeout chhota, retries 0, global concurrency = conc
    settings.batch_size = conc
    settings.request_timeout = 8
    settings.max_retries = 0
    settings.request_delay = 0.0

    pool_file = Path(sys.argv[1] if len(sys.argv) > 1 else "data/sources/pool_domains.txt")
    if not pool_file.is_absolute():
        pool_file = ROOT / pool_file
    domains = [
        ln.strip().lower().replace("www.", "")
        for ln in pool_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.strip() and "." in ln
    ]
    domains = list(dict.fromkeys(domains))

    done: set[str] = set()
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8", errors="replace").splitlines():
            if "\t" in ln:
                done.add(ln.split("\t")[0].strip())

    todo = [d for d in domains if d not in done]
    print(f"pool: {len(domains)} domains, already done: {len(done)}, todo: {len(todo)}",
          flush=True)

    disc = CompanyDiscovery(settings)
    fh = OUT.open("a", encoding="utf-8")
    resolved = 0
    batch_no = 0

    for batch in chunked(todo, conc):
        batch_no += 1
        got = await asyncio.gather(
            *(asyncio.wait_for(resolve_one(disc, d), PER_DOMAIN_CAP) for d in batch),
            return_exceptions=True,
        )
        for d, r in zip(batch, got):
            if isinstance(r, str) and r:
                resolved += 1
                fh.write(f"{d}\t{r}\n")
        fh.flush()
        print(f"batch {batch_no}: +{resolved} career pages "
              f"({min(batch_no * conc, len(todo))}/{len(todo)})", flush=True)

    fh.close()
    print(f"DONE: {resolved} new career pages -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))