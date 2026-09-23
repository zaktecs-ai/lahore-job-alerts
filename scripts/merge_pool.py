"""
pool_resolved.tsv -> companies.json merge.

Resolver ke naye career URLs ko registry mein add/update karta hai.
Uske baad finalize_registry.py (live-check + cap) chalana hai.

Usage:
    python scripts/merge_pool.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.models import Company          # noqa: E402
from src.storage import CompaniesStore  # noqa: E402

REG = ROOT / "data" / "companies.json"
POOL = ROOT / "data" / "sources" / "pool_resolved.tsv"


def norm(url: str) -> str:
    d = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
    return d[4:] if d.startswith("www.") else d


def main() -> int:
    store = CompaniesStore(REG)
    companies = store.load_companies()

    index: dict[str, int] = {}
    for i, c in enumerate(companies):
        index.setdefault(norm(c.website), i)

    added = updated = 0
    for line in POOL.read_text(encoding="utf-8", errors="replace").splitlines():
        if "\t" not in line:
            continue
        dom, url = (p.strip() for p in line.split("\t", 1))
        if not dom or not url:
            continue
        if dom in index:
            c = companies[index[dom]]
            if not c.career_url:
                c.career_url = url
                c.notes = ""
                updated += 1
            continue
        label = dom.split(".")[0].replace("-", " ").title()
        companies.append(
            Company(
                name=label,
                website=f"https://{dom}",
                career_url=url,
                source="pool-resolver",
                notes="",
            )
        )
        index[dom] = len(companies) - 1
        added += 1

    store.save_companies(companies)
    with_url = sum(1 for c in companies if c.career_url)
    print(f"merged: +{added} new, {updated} updated | total={len(companies)} "
          f"with_career_url={with_url}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())