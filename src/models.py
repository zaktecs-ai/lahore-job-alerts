"""
Data models used across the system.

Jobs aur Companies ke liye simple, readable dataclasses.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class Company:
    """A Lahore-based company entry in the registry."""

    name: str
    website: str = ""
    career_url: str = ""
    source: str = "discovery"
    last_checked: str = ""
    notes: str = ""


@dataclass
class Job:
    """A single job posting found on a career page."""

    company: str
    title: str
    url: str
    location: str = ""
    snippet: str = ""
    posted_age: str = ""
    source_page: str = ""

    @property
    def uid(self) -> str:
        """Stable unique id for deduplication.

        Company + title + URL ke hash se banta hai, taake same job dobara
        email na ho.
        """
        raw = f"{self.company.strip().lower()}|{self.title.strip().lower()}|{self.url.strip()}"
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def keywords(self) -> str:
        """Combine everything searchable for keyword matching."""
        return f"{self.title} {self.snippet} {self.location}"


def dedupe_jobs(jobs: list[Job]) -> list[Job]:
    """Remove duplicate job postings (same uid)."""
    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        if job.uid in seen:
            continue
        seen.add(job.uid)
        unique.append(job)
    return unique