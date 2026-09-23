"""
Job-listing parser.

Career page (HTML) se job postings nikalta hai. ATS JSON APIs
(e.g. Lever, Greenhouse) bhi handle hoti hain agar career URL kisi
JSON API point par le jaye.

Approach (simple + effective):
  1. Agar response JSON hai -> parse ATS-style JSON.
  2. Warna HTML hai -> har link dekho jo job posting jaisa lage
     (href/text hints), aur uske paas ka text snippet bhi pakdo.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import Job

log = logging.getLogger(__name__)

# Link ke raaste (href) jin se job posting ki pehchan hoti hai
JOB_URL_HINTS = (
    "/job", "/jobs", "/position", "/vacanc", "/opening", "/open-",
    "/apply", "job-detail", "job_post", "jobpost", "careers/",
    "hiring", "recruit", "listing?posting", "/o/",
)

# Link jis se pehchan ho ke yeh job posting NAHI hai (ignore karo)
NON_JOB_HINTS = (
    "login", "signup", "sign-in", "register", "forgot", "reset",
    "cookie", "privacy", "terms", "legal", "press", "media", "news",
    "blog", "events", "faq", "help", "support", "contact", "about",
    "apply-with-linkedin", "apply/step", "share", "twitter", "facebook",
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".pdf", ".zip", "#", "mailto:", "tel:", "javascript:", "?print",
)

TITLE_LEN_MIN, TITLE_LEN_MAX = 8, 140

# Job title mein itne se zyada words nahi hote. Listing container ka poora
# text (title + description) galti se title ban jata tha -> Weproms bug.
_MAX_TITLE_WORDS = 12

# Anchor text jo sirf CTA hota hai; asli title parent ke heading mein hota hai.
_GENERIC_ANCHOR_TEXT = (
    "view", "view role", "view details", "view job", "view position",
    "apply", "apply now", "read more", "learn more", "see more",
    "details", "more", "open", "show more", "click here",
)


def _looks_like_sentence_blob(text: str) -> bool:
    """True agar text job title nahi balki paragraph/sentence blob lage.

    Listing container ka poora text (title + description ek saath) galti se
    job title ban jata tha — Weproms jaisa false positive.
    """
    t = text.strip()
    if not t:
        return False
    if len(t) > TITLE_LEN_MAX:
        return True
    if len(t.split()) > _MAX_TITLE_WORDS:
        return True
    # do ya zyada sentence-end => paragraph (e.g. "…. RemoteSalary: Open View role")
    if len(re.findall(r"[.!?]\s", t)) >= 2:
        return True
    return False


def _is_fraction_candidate(text: str) -> bool:
    """Is this text a plausible job title (not an empty/noise string)?"""
    t = text.strip()
    if not t:
        return False
    if len(t) < TITLE_LEN_MIN:
        return False
    if _looks_like_sentence_blob(t):
        return False
    return True


def looks_like_job_link(href: str | None, text: str) -> bool:
    """Quick heuristic: does this anchor look like a job posting?"""
    if not href:
        return False
    href_l = href.lower()
    if any(n in href_l for n in NON_JOB_HINTS):
        return False
    if any(h in href_l for h in JOB_URL_HINTS):
        return True
    lowered = text.lower()
    return any(w in lowered for w in ("apply", "details", "read more"))


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html_text: str) -> str:
    """HTML ko plain text bana do (tags hata kar, whitespace normalize).

    Zaroori: detail pages aksar label aur value alag tags mein rakhte hain
    ("Experience: </strong></span><span>4-6"), is liye regex chalane se pehle
    tags hatana lazmi hai — warna experience miss ho jata hai (Arpatech bug).
    """
    if not html_text:
        return ""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html_text)
    cleaned = _TAG_RE.sub(" ", cleaned)
    return _clean(cleaned)


def parse_ats_json(raw: str, base_url: str, company: str) -> list[Job]:
    """Parse Lever/Greenhouse-style JSON APIs into jobs.

    Handles both a bare list and {"data": [...]} envelopes.
    """
    jobs: list[Job] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return jobs

    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if not isinstance(data, list):
        return jobs

    for item in data:
        if not isinstance(item, dict):
            continue
        title = _clean(str(item.get("title") or item.get("name") or ""))
        if not title:
            continue
        apply_url = item.get("url") or item.get("absolute_url") or item.get(
            "hostedUrl") or item.get("applyUrl") or base_url
        location = _clean(str(item.get("location") or item.get("location_text") or ""))
        snippet = _clean(str(item.get("content") or item.get("description") or ""))
        snippet = snippet[:800]
        jobs.append(
            Job(
                company=company,
                title=title[:200],
                url=str(apply_url),
                location=location,
                snippet=snippet,
                source_page=base_url,
            )
        )
    return jobs


def _find_title_near_link(anchor, fallback: str) -> str:
    """Best-effort title: anchor text, nearest heading, parent text (bounded).

    Generic CTA anchor text ("View role") ko title nahi maante — us surat
    mein parent ke andar asli heading dhoondhi jati hai. Blob text (title +
    description ek saath) kabhi title nahi banta.
    """
    fb = fallback.strip()
    generic = fb.lower() in _GENERIC_ANCHOR_TEXT
    if len(fb) >= TITLE_LEN_MIN and not generic and not _looks_like_sentence_blob(fb):
        return fb

    parent = anchor.find_parent(
        ["li", "h1", "h2", "h3", "h4", "h5", "td", "article", "div", "section"]
    )
    if parent is not None:
        # 1) parent ke andar heading / bold element = asli title
        for el in parent.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"]):
            t = _clean(el.get_text())
            if TITLE_LEN_MIN <= len(t) <= TITLE_LEN_MAX and not _looks_like_sentence_blob(t):
                return t
        # 2) parent ka apna text — sirf agar bounded aur blob na ho
        t = _clean(parent.get_text())
        if TITLE_LEN_MIN <= len(t) <= TITLE_LEN_MAX and not _looks_like_sentence_blob(t):
            return t

    # Kuch bhi theek na mila: blob/generic ko title banane ke bajaye chhor do
    if generic or _looks_like_sentence_blob(fb):
        return ""
    return fb


def _snippet_near_link(anchor) -> str:
    parent = anchor.find_parent(["li", "div", "article", "tr", "p"])
    if parent:
        return _clean(parent.get_text())
    return ""


def _looks_like_job_title(text: str) -> bool:
    """Weak signal: heading text that contains a job-ish word."""
    lowered = text.lower()
    return any(
        w in lowered
        for w in (
            "developer", "engineer", "analyst", "scientist", "data", "sql",
            "etl", "scrap", "automation", "intern", "trainee", "associate",
            "executive", "specialist", "coordinator", "rpa", "qa", "quality",
            "tester", "programmer", "coder", "consultant",
        )
    )


def parse_html_jobs(html_text: str, base_url: str, company: str) -> list[Job]:
    """Extract job postings from a generic career HTML page."""
    soup = BeautifulSoup(html_text, "html.parser")
    jobs: list[Job] = []
    seen_hrefs: set[str] = set()

    # --- Pass 1: all anchors -------------------------------------------------
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = _clean(a.get_text())
        if not looks_like_job_link(href, text):
            continue
        absolute = urljoin(base_url, href)
        if any(x in absolute for x in NON_JOB_HINTS):
            continue
        if absolute in seen_hrefs:      # already captured
            continue

        # link text vs parent heading text: prefer a real title
        title = _find_title_near_link(a, text)
        if not title or not _is_fraction_candidate(title):
            continue

        snippet = _snippet_near_link(a)
        jobs.append(
            Job(
                company=company,
                title=title[:200],
                url=absolute,
                snippet=snippet[:800],
                source_page=base_url,
            )
        )
        seen_hrefs.add(absolute)

    # --- Pass 2: headings that look like job titles --------------------------
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = _clean(tag.get_text())
        if not (TITLE_LEN_MIN <= len(text) <= TITLE_LEN_MAX):
            continue
        if not _looks_like_job_title(text):
            continue
        # heading already part of a captured anchor?
        anchor = tag.find_parent("a")
        if anchor and anchor.get("href"):
            continue
        container = tag.find_parent(["li", "div", "section", "article"]) or tag
        link = container.find("a", href=True)
        detail_url = (
            urljoin(base_url, link["href"]) if link and link.get("href")
            else base_url + "#" + text.lower().replace(" ", "-")
        )
        if any(n in detail_url.lower() for n in NON_JOB_HINTS):
            continue
        if detail_url in seen_hrefs:
            continue
        jobs.append(
            Job(
                company=company,
                title=text[:200],
                url=detail_url,
                snippet=_clean(container.get_text())[:800],
                source_page=base_url,
            )
        )
        seen_hrefs.add(detail_url)

    # --- Pass 3: common job-list CSS hooks ----------------------------------
    for sel in ("li.job", "div.job", "article.job", ".job-item", ".job-listing",
                ".job-card", ".jobpost", ".job-list-item"):
        for el in soup.select(sel):
            title_el = el.find(["a", "h1", "h2", "h3", "h4"])
            if not title_el:
                continue
            href = title_el.get("href") if title_el.name == "a" else None
            if not href:
                parent_a = el.find("a", href=True)
                href = parent_a["href"] if parent_a else None
            title = _clean(title_el.get_text())
            if not (TITLE_LEN_MIN <= len(title) <= TITLE_LEN_MAX):
                continue
            absolute = urljoin(base_url, href) if href else base_url
            if absolute in seen_hrefs:
                continue
            jobs.append(
                Job(
                    company=company,
                    title=title[:200],
                    url=absolute,
                    snippet=_clean(el.get_text())[:800],
                    source_page=base_url,
                )
            )
            seen_hrefs.add(absolute)

    return jobs


def parse_career_page(content: str, content_type: str, url: str, company: str) -> list[Job]:
    """Dispatch to the right parser based on content type."""
    if "json" in content_type:
        jobs = parse_ats_json(content, url, company)
        if jobs:
            return jobs
    return parse_html_jobs(content, url, company)


def parse_jobs_from_result(content: str, content_type: str, url: str, company: str) -> list[Job]:
    """Public wrapper used by the scraper pipeline."""
    return parse_career_page(content, content_type, url, company)