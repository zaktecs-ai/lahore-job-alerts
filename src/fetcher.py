"""
Asynchronous web fetcher.

Har career page ko aiohttp se fetch karta hai, batching + rate limit +
retries ke saath. Calls ko polite rakha gaya hai (request_delay) taake
websites ke load par asar na ho.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

import aiohttp

from .config import Settings

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result of a single URL fetch."""

    url: str
    status: int
    content_type: str = ""
    text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error and len(self.text) > 0


class Fetcher:
    """Reusable async HTTP client."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._headers = {
            "User-Agent": settings.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/json,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        self._sem = asyncio.Semaphore(settings.batch_size)

    async def fetch(self, url: str) -> Optional[FetchResult]:
        """Fetch one URL with retries. Returns None on hard failure."""
        timeout = aiohttp.ClientTimeout(total=self.settings.request_timeout)
        err = "unknown"
        for attempt in range(self.settings.max_retries + 1):
            async with self._sem:
                try:
                    async with aiohttp.ClientSession(
                        headers=self._headers, timeout=timeout
                    ) as session:
                        async with session.get(url, allow_redirects=True) as resp:
                            if resp.status != 200:
                                if attempt < self.settings.max_retries:
                                    err = f"HTTP {resp.status}"
                                    await asyncio.sleep(1.5 * (attempt + 1))
                                    continue
                                # Cloudflare 403 ka fallback: curl try karo
                                fallback = await asyncio.to_thread(
                                    self._curl_fetch, url
                                )
                                if fallback:
                                    return fallback
                                return FetchResult(
                                    url=url, status=resp.status, error=f"HTTP {resp.status}"
                                )
                            content_type = (resp.headers.get("Content-Type", "") or "").split(";")[0]
                            body = await resp.read()
                            if len(body) > self.settings.max_page_bytes:
                                return FetchResult(
                                    url=url, status=resp.status,
                                    content_type=content_type,
                                    error="page too large",
                                )
                            text = body.decode("utf-8", errors="replace")
                            return FetchResult(
                                url=str(resp.url), status=200,
                                content_type=content_type, text=text,
                            )
                except asyncio.TimeoutError:
                    err = "timeout"
                except aiohttp.ClientError as exc:
                    err = f"client error: {exc.__class__.__name__}"
                except Exception as exc:  # noqa: BLE001 - last resort guard
                    err = f"error: {exc}"
                # aiohttp failed kisi bhi wajah se -> curl fallback
                # (to_thread: blocking curl event loop ko block na kare)
                fallback = await asyncio.to_thread(self._curl_fetch, url)
                if fallback:
                    return fallback
                if attempt < self.settings.max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return FetchResult(url=url, status=0, error=err)

    def _curl_fetch(self, url: str) -> Optional[FetchResult]:
        """Fetch a URL with curl when aiohttp fails (Cloudflare etc.).

        Returns a FetchResult on success (HTTP 200), else None.
        """
        try:
            proc = subprocess.run(
                [
                    "curl", "-sL", "--compressed", "--max-time",
                    str(self.settings.request_timeout),
                    "-A", self._headers["User-Agent"],
                    "-w", "\n__STATUS__%{http_code}__CT__%{content_type}",
                    url,
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.request_timeout + 10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0 or not proc.stdout:
            return None
        body, _, meta = proc.stdout.rpartition("\n__STATUS__")
        if not meta:
            return None
        try:
            status_part, ct_part = meta.split("__CT__", 1)
            status = int(status_part.strip())
            content_type = (ct_part.strip().split(";") or [""])[0]
        except (ValueError, AttributeError):
            return None
        if status != 200 or len(body) == 0:
            return None
        if len(body) > self.settings.max_page_bytes:
            return FetchResult(url=url, status=status, content_type=content_type,
                               error="page too large")
        return FetchResult(url=url, status=200, content_type=content_type, text=body)

    async def fetch_many(self, urls: list[str]) -> list[FetchResult]:
        """Fetch a list of URLs with at-most batch_size concurrency."""
        results = await asyncio.gather(
            *(self.fetch(url) for url in urls), return_exceptions=True
        )
        out: list[FetchResult] = []
        for url, res in zip(urls, results):
            if isinstance(res, FetchResult):
                out.append(res)
            else:
                out.append(FetchResult(url=url, status=0, error=str(res)))
            await asyncio.sleep(self.settings.request_delay)
        return out

    async def close(self) -> None:
        """No persistent session; kept for interface symmetry."""
        return None


def chunked(items: list, size: int):
    """Yield successive chunks of `size` from `items`."""
    for i in range(0, len(items), size):
        yield items[i : i + size]