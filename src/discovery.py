"""
Company & career-page discovery for Lahore.

Metadata sources:
  - TechBehemoths ka Lahore directory (520 companies) - default source

Har domain ka career page is order mein dhoonda jata hai:
  1. Homepage ke andar "career"-type links
  2. Common career paths (/careers, /jobs, ...) - config se

Har candidate URL ko validate karte hain (200 + page career-jaisa lage)
taake broken links registry mein na aayen.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .config import Settings
from .fetcher import Fetcher, chunked
from .models import Company

log = logging.getLogger(__name__)

TECHBEHEMOTHS_LAHORE = "https://techbehemoths.com/companies/lahore"

# External website link on TechBehemoths listing pages carries this marker
WEBSITE_MARKER = "utm_source=Tech-Behemoths"

CAREER_HINT_RE = re.compile(
    r"career|jobs?|vacanc|open.?pos|join.?us|hiring|work.?with.?us|current.?open", re.I
)

CAREER_PAGE_TERMS = (
    "careers", "career", "open positions", "current openings", "job openings",
    "vacancies", "join our team", "we are hiring", "work with us",
    "current opportunities", "apply now",
)


@dataclass
class DiscoveryStats:
    pages_fetched: int = 0
    domains_found: int = 0
    career_success: int = 0
    career_failed: int = 0


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _domain_name(website: str) -> str:
    netloc = urlparse(website).netloc
    return netloc or website.replace("https://", "").replace("http://", "").strip("/")


def extract_websites_from_listing(html_text: str) -> list[str]:
    """Parse a TechBehemoths listing page for company website domains."""
    soup = BeautifulSoup(html_text, "html.parser")
    websites: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if WEBSITE_MARKER not in href:
            continue
        parsed = urlparse(href)
        domain = parsed.netloc or ""
        if not domain or domain in {"techbehemoths.com", "rest.techbehemoths.com"}:
            continue
        if domain.startswith("www."):
            domain = domain[4:]
        websites.append(domain)
    # dedupe, keep order
    seen: set[str] = set()
    out: list[str] = []
    for d in websites:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def extract_name_from_listing(html_text: str, website: str) -> str:
    """Find the company name in a card that also links to this website."""
    soup = BeautifulSoup(html_text, "html.parser")
    website_l = website.replace("www.", "")
    for a in soup.find_all("a", href=True):
        if WEBSITE_MARKER in a["href"] and website_l in a["href"]:
            node = a
            for _ in range(6):
                parent = node.find_parent()
                if parent is None:
                    break
                heading = parent.find(["h2", "h3", "h4", "h5"])
                if heading:
                    name = _clean(heading.get_text())
                    if 2 <= len(name) <= 60:
                        return name
                node = parent
            break
    return ""


class CompanyDiscovery:
    """Finds Lahore companies and resolves their career pages."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.fetcher = Fetcher(settings)
        self.stats = DiscoveryStats()

    # -- public pipeline ------------------------------------------------
    async def discover(self, pages: int | None = None, limit: int | None = None) -> list[Company]:
        """Full pipeline: websites -> career URLs -> validated registry."""
        companies: list[Company] = []

        websites = await self.collect_websites(pages)
        log.info("Collected %d unique company websites.", len(websites))
        if limit:
            websites = websites[:limit]
        self.stats.domains_found = len(websites)

        for batch in chunked(websites, self.settings.batch_size):
            tasks = [self.resolve_career_url(w) for w in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for website, result in zip(batch, results):
                if isinstance(result, Exception):
                    log.warning("resolution error for %s: %s", website, result)
                    continue
                url, name = result
                if url:
                    self.stats.career_success += 1
                else:
                    self.stats.career_failed += 1
                companies.append(
                    Company(
                        name=name or _domain_name(website),
                        website=f"https://{website}",
                        career_url=url or "",
                        source="techbehemoths-lahore",
                        notes="" if url else "no career page found",
                    )
                )
            log.info(
                "Progress %d/%d | success=%d failed=%d",
                len(companies), len(websites),
                self.stats.career_success, self.stats.career_failed,
            )
        return companies

    # -- website collection ---------------------------------------------
    async def collect_websites(self, pages: int | None = None) -> list[str]:
        """Fetch TechBehemoths Lahore listing pages and collect domains."""
        total_pages = pages or 22
        urls = [
            TECHBEHEMOTHS_LAHORE if p == 1 else f"{TECHBEHEMOTHS_LAHORE}?page={p}"
            for p in range(1, total_pages + 1)
        ]
        results = await self.fetcher.fetch_many(urls)
        all_websites: list[str] = []
        for url, res in zip(urls, results):
            self.stats.pages_fetched += 1
            if not res.ok:
                log.warning("listing page failed: %s (%s)", url, res.error)
                continue
            found = extract_websites_from_listing(res.text)
            log.info("Page %s -> %d websites", url, len(found))
            all_websites.extend(found)
        seen: set[str] = set()
        unique: list[str] = []
        for w in all_websites:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return unique

    # -- career resolution ----------------------------------------------
    # ATS hosts jo genuine job-listing pages dete hain (cross-origin allowed)
    ATS_HOSTS = (
        "lever.co", "greenhouse.io", "myworkdayjobs.com", "smartrecruiters.com",
        "workable.com", "recruitee.com", "breezy.hr", "bamboohr.com",
        "jobvite.com", "applytojob.com", "rippling-ats.com", "zoho.eu", "zoho.com",
    )

    @staticmethod
    def _base_domain(netloc: str) -> str:
        """netloc ka registrable domain (a.b.com -> b.com)."""
        parts = netloc.lower().split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else netloc

    def _career_link_allowed(self, url: str, homepage: str) -> bool:
        """Same base domain (subdomains theek) ya known ATS host."""
        netloc = urlparse(url).netloc.lower()
        home_base = self._base_domain(urlparse(homepage).netloc)
        if self._base_domain(netloc) == home_base:
            return True
        return any(netloc == a or netloc.endswith("." + a) for a in self.ATS_HOSTS)

    async def resolve_career_url(self, website: str) -> tuple[str, str]:
        """Find a working career page for a domain. Returns (url, name)."""
        hosts = [
            f"https://{website}",
            f"https://www.{website}",
            f"http://{website}",
        ]
        homepage, res = "", None
        for host in hosts:
            res = await self.fetcher.fetch(host)
            if res.ok and res.text:
                homepage = host
                break
        if not homepage or res is None or not res.ok:
            return "", ""

        name = extract_name_from_listing(res.text, website)
        candidates: list[str] = []
        if "html" in res.content_type:
            candidates = self._homepage_career_links(res.text, homepage)
        # common paths bhi try karo
        for path in self.settings.career_path_candidates:
            candidates.append(urljoin(homepage, path))
        # sitemap.xml mein career URLs dhoondo (har sitemap variant try karo)
        candidates.extend(await self._sitemap_career_urls(homepage))
        # validate candidates (dedupe, allow-list)
        seen: set[str] = set()
        for cand in candidates:
            if cand in seen:
                continue
            seen.add(cand)
            if not self._career_link_allowed(cand, homepage):
                continue
            if await self._validate_career_url(cand):
                return cand, name
            await asyncio.sleep(self.settings.request_delay)
        return "", name

    async def _sitemap_career_urls(self, homepage: str) -> list[str]:
        """sitemap.xml se career/job URLs mine karo (ek request, sasta)."""
        out: list[str] = []
        for sm_url in (f"{homepage}/sitemap.xml", f"{homepage}/sitemap_index.xml"):
            res = await self.fetcher.fetch(sm_url)
            if not res.ok or not res.text:
                continue
            for m in re.finditer(r"<loc>\s*([^<\s]+)\s*</loc>", res.text):
                loc = m.group(1)
                if CAREER_HINT_RE.search(loc) and len(urlparse(loc).path) > 1:
                    out.append(loc)
            # sitemap index ho to pehli nested sitemap bhi check karo
            if not out and "<sitemapindex" in res.text:
                first = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", res.text)
                if first:
                    res2 = await self.fetcher.fetch(first.group(1))
                    if res2.ok and res2.text:
                        for m in re.finditer(r"<loc>\s*([^<\s]+)\s*</loc>", res2.text):
                            loc = m.group(1)
                            if CAREER_HINT_RE.search(loc):
                                out.append(loc)
            if out:
                break
        return out[:6]

    def _homepage_career_links(self, html_text: str, homepage: str) -> list[str]:
        """Find career-looking links on the homepage (allow-list filtered)."""
        soup = BeautifulSoup(html_text, "html.parser")
        out: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip().split("#")[0]
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            text = _clean(a.get_text())[:60]
            combined = (href + " " + text).lower()
            if not CAREER_HINT_RE.search(combined):
                continue
            absolute = urljoin(homepage, href)
            if not self._career_link_allowed(absolute, homepage):
                continue
            out.append(absolute)

        def score(url: str) -> int:
            u = url.lower()
            s = 0
            if any(t in u for t in ("/careers", "/careers/", "/career")):
                s += 3
            if "/jobs" in u:
                s += 2
            if "career" in u:
                s += 1
            return -s

        return sorted(set(out), key=score)[:8]

    async def _validate_career_url(self, url: str) -> bool:
        """A career URL is valid if it returns 200 and looks career-ish."""
        res = await self.fetcher.fetch(url)
        if not res.ok:
            return False
        if "html" not in res.content_type and "json" not in res.content_type:
            return False
        if len(res.text) < 500:
            return False
        return self._looks_like_career_page(res.text)

    @staticmethod
    def _looks_like_career_page(html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "html.parser")
        parts: list[str] = []
        if soup.title and soup.title.string:
            parts.append(str(soup.title.string))
        for tag in soup.find_all(["h1", "h2", "h3"]):
            parts.append(_clean(tag.get_text()))
        combined = " ".join(parts).lower()
        if any(t in combined for t in CAREER_PAGE_TERMS):
            return True
        # fallback: kuch anchors "job/apply" jaisay hon
        text = _clean(soup.get_text())[:20000].lower()
        return text.count("job") >= 2 or "apply" in text
