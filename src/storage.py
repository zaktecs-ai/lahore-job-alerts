"""
Persistent JSON storage.

Two stores:
  - companies.json  -> Lahore companies ki registry (discovery output)
  - seen_jobs.json  -> already-notified job uids (taake dobara email na ho)

JSON simple, readable aur server se server migrate karna aasaan hai.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .models import Company, Job


class JsonStore:
    """Thread-safe JSON file store with atomic writes."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: Any = self._load()

    # -- raw helpers -------------------------------------------------
    def _load(self) -> Any:
        if not self.path.exists():
            return self._default()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt file ka aasan se recovery — empty state se chalu kar lo.
            return self._default()

    def _default(self) -> Any:
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(self.path)  # atomic on same filesystem

    # -- thread-safe wrappers ---------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()


class SeenJobsStore(JsonStore):
    """Tracks which job postings have already been notified about."""

    def _default(self) -> dict:
        return {"uids": []}

    def is_seen(self, job: Job) -> bool:
        with self._lock:
            return job.uid in self._data["uids"]

    def mark_seen(self, jobs: list[Job]) -> None:
        with self._lock:
            uid_list = self._data.setdefault("uids", [])
            for job in jobs:
                if job.uid not in uid_list:
                    uid_list.append(job.uid)
            # Keep it bounded (only most recent 5000 uids).
            if len(uid_list) > 5000:
                self._data["uids"] = uid_list[-5000:]
            self._save()

    def count(self) -> int:
        with self._lock:
            return len(self._data.get("uids", []))


class CompaniesStore(JsonStore):
    """Registry of discovered Lahore companies."""

    def _default(self) -> dict:
        return {"companies": []}

    def load_companies(self) -> list[Company]:
        with self._lock:
            raw = self._data.get("companies", [])
        return [Company(**item) for item in raw]

    def save_companies(self, companies: list[Company]) -> None:
        with self._lock:
            self._data["companies"] = [
                {
                    "name": c.name,
                    "website": c.website,
                    "career_url": c.career_url,
                    "source": c.source,
                    "last_checked": c.last_checked,
                    "notes": c.notes,
                }
                for c in companies
            ]
            self._save()

    def count(self) -> int:
        with self._lock:
            return len(self._data.get("companies", []))