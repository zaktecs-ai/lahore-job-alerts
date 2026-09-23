"""
Configuration loader.

Loads settings from config.yaml and secrets from the .env file.
Sab config ek hi jagah se control hoti hai — is module ko roz
change karne ki zaroorat nahi.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Project root = parent of the package directory (lahore-job-alerts/)
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT_DIR / "config.yaml"
ENV_FILE = ROOT_DIR / ".env"


def load_env(env_file: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into the environment.

    Existing environment variables are never overwritten.
    """
    env_file = env_file or ENV_FILE
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


@dataclass
class EmailSettings:
    """Email notification settings (secrets come from .env)."""

    enabled: bool = True
    subject: str = "Job Alert: {n} Entry-Level Data Role(s) Found — Lahore"
    portfolio_url: str = "https://zaktecs.dev"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    username: str = ""
    app_password: str = ""
    to_addr: str = ""

    def is_configured(self) -> bool:
        return bool(self.username and self.app_password and self.to_addr)


@dataclass
class Settings:
    """All runtime settings, loaded once from config.yaml + .env."""

    # scraping
    batch_size: int = 40
    max_companies: int = 500
    request_timeout: int = 20
    request_delay: float = 0.3
    max_retries: int = 2
    max_page_bytes: int = 8_000_000
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # matching
    max_experience_years: int = 2
    include_unstated_experience_if_junior_title: bool = True
    include_unstated_experience: bool = True
    verify_detail_experience: bool = True
    target_roles: list[str] = field(default_factory=list)
    blocked_keywords: list[str] = field(default_factory=list)
    junior_hints: list[str] = field(default_factory=list)

    # email
    email: EmailSettings = field(default_factory=EmailSettings)

    # files
    companies_file: Path = ROOT_DIR / "data" / "companies.json"
    seen_jobs_file: Path = ROOT_DIR / "data" / "seen_jobs.json"
    log_level: str = "INFO"

    # discovery
    career_path_candidates: list[str] = field(
        default_factory=lambda: [
            "/careers", "/career", "/jobs", "/job", "/join-us", "/joinus",
            "/vacancies", "/open-positions", "/career.html", "/we-are-hiring",
            "/careers.html", "/career.php", "/careers.php", "/jobs.php",
            "/careers/index.html", "/current-openings", "/career-opportunities",
            "/work-with-us", "/about/careers", "/company/careers",
            "/careers/", "/jobs/", "/hiring", "/opportunities",
        ]
    )

    @classmethod
    def from_file(cls, config_path: Path | None = None) -> "Settings":
        load_env()
        cfg: dict[str, Any] = {}
        config_path = config_path or CONFIG_FILE
        if config_path.exists():
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

        # config.yaml flat keys use karti hai (easy for the user);
        # sirf `email:` aur `files:` nested sections hain.
        email_cfg = cfg.get("email") or {}
        files_cfg = cfg.get("files") or {}

        return cls(
            batch_size=int(cfg.get("batch_size", 40)),
            max_companies=int(cfg.get("max_companies", 500)),
            request_timeout=int(cfg.get("request_timeout", 20)),
            request_delay=float(cfg.get("request_delay", 0.3)),
            max_retries=int(cfg.get("max_retries", 2)),
            max_page_bytes=int(cfg.get("max_page_bytes", 8_000_000)),
            user_agent=str(cfg.get("user_agent") or cls.user_agent),
            max_experience_years=int(cfg.get("max_experience_years", 2)),
            include_unstated_experience_if_junior_title=bool(
                cfg.get("include_unstated_experience_if_junior_title", True)
            ),
            include_unstated_experience=bool(
                cfg.get("include_unstated_experience", True)
            ),
            verify_detail_experience=bool(
                cfg.get("verify_detail_experience", True)
            ),
            target_roles=list(cfg.get("target_roles") or []),
            blocked_keywords=list(cfg.get("blocked_keywords") or []),
            junior_hints=list(cfg.get("junior_hints") or []),
            email=EmailSettings(
                enabled=bool(email_cfg.get("enabled", True)),
                subject=email_cfg.get("subject") or EmailSettings.subject,
                portfolio_url=email_cfg.get("portfolio_url", "https://zaktecs.dev"),
                smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
                smtp_port=int(os.environ.get("SMTP_PORT", "465")),
                username=os.environ.get("GMAIL_USER", ""),
                app_password=os.environ.get("GMAIL_APP_PASSWORD", ""),
                to_addr=os.environ.get("GMAIL_TO", ""),
            ),
            companies_file=ROOT_DIR / files_cfg.get("companies_file", "data/companies.json"),
            seen_jobs_file=ROOT_DIR / files_cfg.get("seen_jobs_file", "data/seen_jobs.json"),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )