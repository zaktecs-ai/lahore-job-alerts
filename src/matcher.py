"""
Job matcher: entry-level (0-2 yrs) data-role filter.

Kaam:
  1. Kya title/description mein target data-role hai?        -> relevance
  2. Kya job senior hai? (senior/lead/5+ years etc)          -> reject
  3. Kya experience 0-2 years range mein hai?                 -> accept
     agar experience mention hi nahi aur title junior lage     -> accept (config)

Sab keywords config.yaml se aate hain — system chaltay waqt
script ko chhunay ki zaroorat nahi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Settings
from .models import Job

# Experience patterns (common formats in job postings)
_EXP_RANGE = re.compile(r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*(?:years?|yrs?)", re.I)
_EXP_MAX = re.compile(
    r"(?:up to|less than|under|max(?:imum)? of?|no more than)\s*(\d{1,2})\s*(?:years?|yrs?)",
    re.I,
)
_EXP_MIN = re.compile(
    r"(?:at least|minimum of?|minimum)\s*(\d{1,2})\s*(?:years?|yrs?)", re.I
)
_EXP_PLUS = re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)", re.I)
_EXP_NAKED = re.compile(r"(\d{1,2})\s*(?:years?|yrs?)\s*(?:of experience|experience)", re.I)
# "Experience: 4-6" / "Experience Required: 3-5" / "Exp: 2 - 4"
# Kai career pages "years" shabd likhte hi nahi (Arpatech bug: "Experience: 4-6").
_EXP_LABELED_RANGE = re.compile(
    r"(?:experience|exp)\s*(?:required|needed)?\s*[:\-–—]\s*(\d{1,2})\s*[-–—]\s*(\d{1,2})(?!\d)",
    re.I,
)
# "Experience: 5" / "Experience Required: 3"  (single number, bina unit)
# month/week/day ke saath aaye to use nahi karte (e.g. "Experience: 6 months"
# ek fresh-grad internship ho sakti hai — usay reject nahi karna).
_EXP_LABELED_SINGLE = re.compile(
    r"(?:experience|exp)\s*(?:required|needed)?\s*[:\-–—]\s*(\d{1,2})(?!\s*(?:month|week|day))",
    re.I,
)


@dataclass
class MatchResult:
    """Outcome of matching one job against the rules."""

    is_match: bool
    reason: str = ""
    role_match: str = ""
    experience_text: str = ""


# Blog/article/case-study pages career site par ho sakti hain — inko
# job posting samajh kar email bhejna galat hai (real bug fix).
_NON_JOB_URL_PATTERNS = (
    "/blog", "/news/", "/article", "/press", "/case-stud", "/whitepaper",
    "/insight", "/guide", "/tutorial", "/portfolio/", "/gallery",
    "/services", "/solutions", "/products", "/industries", "/pricing",
)

# Title mein yeh words hon to wo job nahi (service/solution offering pages)
_TITLE_NON_JOB_WORDS = (
    "services", "solutions we offer", "case study", "our work",
    "hire dedicated", "whitepaper", "roadmap", "playbook",
)

# Kisi sahi job title mein yeh "job words" almost hamesha hote hain
# (engineer, analyst, intern...). Blog category jaisi headings
# ("AI & Data Science") mein ye nahi hote — reject karo.
_TITLE_JOB_WORDS = (
    "engineer", "developer", "analyst", "scientist", "scraper", "scraping",
    "programmer", "intern", "trainee", "associate", "operator", "assistant",
    "executive", "specialist", "administrator", "admin", "consultant",
    "junior", "entry", "fresher", "graduate", "automation", "etl",
    "database", "devops", "architect", "manager", "officer", "resources",
)


def extract_experience(text: str) -> tuple[int | None, int | None]:
    """Return (min_years, max_years) found in text, or (None, None).

    Examples:
      "2-3 years"            -> (2, 3)
      "up to 2 years"        -> (0, 2)
      "minimum 1 year"       -> (1, 1)
      "3+ years"             -> (3, None)
      "2 years of experience"-> (2, 2)  -- ambiguous, treat as exactly 2
    """
    if m := _EXP_LABELED_RANGE.search(text):
        return int(m.group(1)), int(m.group(2))
    if m := _EXP_RANGE.search(text):
        return int(m.group(1)), int(m.group(2))
    if m := _EXP_MAX.search(text):
        return 0, int(m.group(1))
    if m := _EXP_MIN.search(text):
        return int(m.group(1)), int(m.group(1))
    if m := _EXP_PLUS.search(text):
        return int(m.group(1)), None
    if m := _EXP_NAKED.search(text):
        val = int(m.group(1))
        return val, val
    if m := _EXP_LABELED_SINGLE.search(text):
        val = int(m.group(1))
        return val, val
    return None, None


class JobMatcher:
    """Decision engine for entry-level data roles."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._roles = [k.lower() for k in settings.target_roles if k.strip()]
        self._blocked = [k.lower() for k in settings.blocked_keywords if k.strip()]
        self._junior = [k.lower() for k in settings.junior_hints if k.strip()]

    # -- public API ---------------------------------------------------
    def match(self, job: Job) -> MatchResult:
        title = job.title.lower()
        url_l = (job.url or "").lower()
        blob = job.keywords().lower()

        # 0a) blog/news/article/services URL -> job posting nahi hai (false positive fix)
        if any(p in url_l for p in _NON_JOB_URL_PATTERNS):
            return MatchResult(False, "non-job URL (blog/services/article)")

        # 0a-2) title service/offering page ka lag raha hai -> reject
        if any(w in title for w in _TITLE_NON_JOB_WORDS):
            return MatchResult(False, "title is a service/offering page, not a job")

        # 0b) title mein koi job-word nahi -> blog heading / page section hai
        if not any(w in title for w in _TITLE_JOB_WORDS):
            return MatchResult(False, "title has no job word (blog/heading?)")

        # 0a-3) title ek text-blob / paragraph lagta hai -> parser noise
        # (Weproms bug: poora listing text title ban gaya tha)
        if len(title.split()) > 12 or len(re.findall(r"[.!?]\s", title)) >= 2:
            return MatchResult(False, "title is a text blob, not a job title")

        # 1) relevance: kya ye data-related role hai?
        role_hit = self._first_hit(self._roles, title, blob)
        if not role_hit:
            return MatchResult(False, "no target role keyword")
        role_in_title = self._first_hit(self._roles, title, "")

        # 2) blocked: seniority guard (title se prioritize)
        blocked_hit = self._first_hit(self._blocked, title, blob)
        if blocked_hit:
            return MatchResult(False, f"blocked keyword: {blocked_hit}")

        # 3) experience check
        exp_text = extract_experience_text(job)
        lo, hi = extract_experience(exp_text)
        max_years = self.settings.max_experience_years

        if lo is not None:
            # explicit range present: accept agar start <= max_years
            if lo > max_years:
                return MatchResult(False, f"requires {lo}+ years")
            return MatchResult(True, "experience within range", role_hit, exp_text)
        if hi is not None:      # pragma: no cover - defensive
            if hi > max_years:
                return MatchResult(False, f"requires up-to {hi} years")
            return MatchResult(True, "experience within range", role_hit, exp_text)

        # 4) unknown experience: junior hint ya clear-role fallback
        junior = self._first_hit(self._junior, title, blob)
        if junior:
            return MatchResult(True, f"junior hint: {junior}", role_hit, exp_text)
        if (
            self.settings.include_unstated_experience_if_junior_title
            and any(w in title for w in ("junior", "entry", "fresh", "trainee", "intern"))
        ):
            return MatchResult(True, "junior in title (config fallback)", role_hit, exp_text)
        if (
            self.settings.include_unstated_experience
            and role_in_title
            and "internship" not in blob
        ):
            return MatchResult(
                True,
                "clear role in title; experience unstated (config fallback)",
                role_in_title,
                exp_text,
            )

        return MatchResult(False, "experience not stated & no junior hint")

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _first_hit(keywords: list[str], title: str, blob: str) -> str:
        """Return the first keyword that appears in title (strong) or blob."""
        for kw in keywords:
            if kw in title:
                return kw
        for kw in keywords:
            if kw in blob:
                return kw
        return ""


def extract_experience_text(job: Job) -> str:
    """Join title + snippet for experience extraction (bounded length)."""
    return f"{job.title[:200]} {job.snippet[:1200]}"