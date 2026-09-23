"""
Email notification module (Gmail SMTP).

Secrets .env se aate hain:
  GMAIL_USER, GMAIL_APP_PASSWORD, GMAIL_TO

`send_test()` command se email setup verify hota hai (bina kisi job ke).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Settings
from .models import Job

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class EmailNotifier:
    """Sends job alert emails via Gmail SMTP with an app password."""

    def __init__(self, settings: Settings):
        self.cfg = settings.email

    # -- public API -----------------------------------------------------
    def send_job_alert(self, jobs: list[Job], dry_run: bool = False) -> bool:
        """Send one email summarising all newly matched jobs."""
        if not jobs:
            log.info("No jobs to email.")
            return True
        if dry_run:
            log.info("[dry-run] %d job(s) WOULD be emailed (email disabled).", len(jobs))
            for job in jobs:
                log.info("  -> %s -- %s", job.company, job.title)
            return True
        if not self.cfg.is_configured():
            log.error("Email not configured. Check .env (GMAIL_USER/APP_PASSWORD/GMAIL_TO).")
            return False

        subject = self.cfg.subject.format(n=len(jobs))
        html = self._build_html(jobs)
        text = self._build_text(jobs)
        return self.send(subject, html, text)

    def send(self, subject: str, html: str, text: str = "") -> bool:
        """Low-level SMTP send."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.cfg.username
        msg["To"] = self.cfg.to_addr
        if text:
            msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                host=self.cfg.smtp_host,
                port=self.cfg.smtp_port,
                context=context,
                timeout=30,
            ) as server:
                server.login(self.cfg.username, self.cfg.app_password)
                server.sendmail(self.cfg.username, [self.cfg.to_addr], msg.as_string())
            log.info("Email sent -> %s | %s", self.cfg.to_addr, subject)
            return True
        except smtplib.SMTPAuthenticationError as exc:
            log.error(
                "Gmail auth failed (%s). App password sahi hai? "
                "Gmail mein 2-Step Verification ON karein aur app password banayein.",
                exc.smtp_code,
            )
            return False
        except Exception as exc:  # noqa: BLE001 - network/other SMTP errors
            log.error("Email sending failed: %s", exc)
            return False

    def send_test(self, dry_run: bool = False) -> bool:
        """Send a simple test email to confirm credentials work."""
        if dry_run:
            log.info("[dry-run] Test email WOULD be sent to %s", self.cfg.to_addr)
            return True
        html = (
            "<h2>Job Alert System - Test Email</h2>"
            "<p>Congrats! Email setup bilkul theek hai.</p>"
            "<p>Sender: <b>{}</b><br>Receiver: <b>{}</b></p>"
            "<p>Ab jab bhi koi matching entry-level data role milegi, "
            "yaksha help se notify hoga.</p>"
        ).format(self.cfg.username, self.cfg.to_addr)
        text = (
            "Job Alert System - Test Email\n"
            "Email setup bilkul theek hai.\n"
            "Sender/receiver confirmed. Matching jobs par alerts aayengi."
        )
        return self.send(f"[TEST] Job Alert System - {_now()}", html, text)

    # -- templates -------------------------------------------------------
    def _build_text(self, jobs: list[Job]) -> str:
        lines = [
            f"🔔 {len(jobs)} new entry-level data job(s) in Lahore (0-2 yrs).",
            "",
        ]
        for job in jobs:
            lines.append(f"► {job.title} — {job.company}")
            if job.location:
                lines.append(f"  📍 {job.location}")
            lines.append(f"  🔗 {job.url}")
            if job.snippet:
                lines.append(f"  {job.snippet[:160]}")
            lines.append("")
        lines.append("Apply soon — entry-level roles fill fast.")
        lines.append(f"Portfolio: {self.cfg.portfolio_url}")
        lines.append("Next check: 8 hours.")
        return "\n".join(lines)

    def _build_html(self, jobs: list[Job]) -> str:
        rows = []
        for job in jobs:
            location = (
                f'<div style="font-size:13px;color:#6b7280;margin:6px 0 2px;">'
                f'📍 {job.location}</div>'
                if job.location
                else ""
            )
            snippet = (
                f'<div style="font-size:13px;color:#4b5563;line-height:1.5;'
                f'margin-top:8px;">{job.snippet[:280]}</div>'
                if job.snippet
                else ""
            )
            rows.append(
                f'<div style="background:#ffffff;border:1px solid #e5e7eb;'
                f'border-radius:12px;padding:18px 20px;margin:14px 0;">'
                f'<div style="font-size:12px;font-weight:700;letter-spacing:1px;'
                f'text-transform:uppercase;color:#6366f1;margin-bottom:6px;">'
                f'{job.company}</div>'
                f'<div style="font-size:17px;font-weight:700;color:#111827;'
                f'line-height:1.35;">{job.title}</div>'
                f'{location}{snippet}'
                f'<div style="margin-top:14px;">'
                f'<a href="{job.url}" style="display:inline-block;background:#4f46e5;'
                f'color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;'
                f'padding:9px 22px;border-radius:8px;">View &amp; Apply →</a>'
                f'<a href="{job.url}" style="font-size:12px;color:#6b7280;'
                f'margin-left:12px;text-decoration:none;">{job.url}</a>'
                f"</div></div>"
            )
        return (
            '<div style="margin:0;padding:0;background:#f3f4f6;">'
            '<div style="max-width:620px;margin:0 auto;font-family:Arial,Helvetica,'
            'sans-serif;">'
            '<div style="background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%);'
            'border-radius:14px 14px 0 0;padding:26px 28px;text-align:center;">'
            f'<div style="font-size:22px;font-weight:800;color:#ffffff;">'
            f'🔔 {len(jobs)} New Entry-Level Data Job{"s" if len(jobs) != 1 else ""}</div>'
            '<div style="font-size:14px;color:#e0e7ff;margin-top:6px;">'
            'Lahore, Pakistan · 0-2 years experience</div></div>'
            '<div style="background:#ffffff;border:1px solid #e5e7eb;'
            'border-top:none;padding:20px 24px 8px;">'
            '<p style="font-size:14px;color:#374151;line-height:1.6;margin:0 0 6px;">'
            'Assalam-o-Alaikum! Aap ke liye fresh entry-level data roles mile hain. '
            "Requirements zaroor parh lein aur jaldi apply karein — "
            "entry-level positions foran fill ho jati hain.</p>"
            f"{''.join(rows)}"
            "</div>"
            '<div style="background:#111827;border-radius:0 0 14px 14px;'
            'padding:18px 24px;text-align:center;">'
            f'<a href="{self.cfg.portfolio_url}" style="color:#a5b4fc;font-size:13px;'
            f'text-decoration:none;font-weight:600;">'
            f"💎 zaktecs.dev — Portfolio</a>"
            '<div style="color:#6b7280;font-size:12px;margin-top:8px;">'
            "Agla check 8 hours baad · Lahore Job Alert System</div>"
            "</div></div></div>"
        )
