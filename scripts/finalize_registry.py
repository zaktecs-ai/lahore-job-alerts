"""
Registry ko finalize karta hai: exactly 500 functional career pages.

Steps:
  1. companies.json load karo (career_url walon ko hi rakho)
  2. Har career URL live-check (HTTP 200, content-type HTML) - dead hatao
  3. Exactly 500 par cap (alphabetical order mein se 500)
  4. Final registry save (data/companies.json — app + cron isi ko parhta hai)

Usage:
    python scripts/finalize_registry.py [target_count]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Settings, load_env          # noqa: E402
from src.fetcher import Fetcher, chunked           # noqa: E402

INP = ROOT / "data" / "companies.json"
# App (config.yaml -> files.companies_file) isi file ko parhti hai, is liye
# final output bhi companies.json hi hai. Purani file .bak mein safe rehti hai.
OUT = ROOT / "data" / "companies.json"
BAK = ROOT / "data" / "archive" / "companies_before_finalize.json"


async def main() -> int:
    load_env()
    settings = Settings.from_file()
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    data = json.loads(INP.read_text(encoding="utf-8"))
    companies = data.get("companies", data) if isinstance(data, dict) else data

    with_urls = [c for c in companies if c.get("career_url")]
    print(f"registry: {len(companies)} companies, {len(with_urls)} with career_url", flush=True)

    # live check (parallel batches)
    fetcher = Fetcher(settings)
    ok: list[dict] = []

    async def check(c: dict):
        res = await fetcher.fetch(c["career_url"])
        return c, res

    batch_no = 0
    for batch in chunked(with_urls, 60):
        batch_no += 1
        got = await asyncio.gather(*(check(c) for c in batch), return_exceptions=True)
        for c, res in got:
            if not isinstance(res, Exception) and res and res.ok:
                ok.append(c)
        print(f"live-check batch {batch_no}: ok={len(ok)}/{len(with_urls)}", flush=True)
    await fetcher.close()

    # exact cap (agar target se kam hain to jitne hain wahi rakho)
    final = ok[:target]
    print(f"live-ok={len(ok)} -> keeping {len(final)} (target {target})", flush=True)

    # safety: purani registry backup (data/archive/)
    if INP.exists():
        BAK.parent.mkdir(parents=True, exist_ok=True)
        BAK.write_text(INP.read_text(encoding="utf-8"), encoding="utf-8")

    if not final:
        print("WARNING: koi bhi career URL live nahi mila — purani registry rakhi gayi.", flush=True)
        return 1

    json.dump({"companies": final}, OUT.open("w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"FINAL registry -> {OUT} ({len(final)} verified career pages)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))