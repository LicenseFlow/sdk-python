"""Local audit/activity log (opt-in). Same format as the JS SDK: sdk/AUDIT_LOG_FORMAT.md.

Enable with LICENSEFLOW_AUDIT_LOG=1 or AuditLogger(enabled=True). Never writes full
license keys, API keys, tokens or passwords.
"""
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

SECRET_RE = re.compile(r"(lf_(?:live|test)_[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._-]+|eyJ[A-Za-z0-9._-]{10,})")


def mask_license(key: Optional[str]) -> str:
    if not key:
        return "-"
    if len(key) <= 4:
        return "****"
    m = re.match(r"^[A-Za-z]{2,4}-", key)
    return f"{m.group(0) if m else ''}****-{key[-4:]}"


def scrub_secrets(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", SECRET_RE.sub("[redacted]", text))


def format_audit_line(action: str, result: str, actor: str = "app", license: Optional[str] = None,
                      status: Optional[int] = None, duration_ms: Optional[int] = None,
                      request_id: Optional[str] = None, detail: Optional[str] = None,
                      now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    parts = [ts, f"actor={actor}", f"action={action}", f"license={mask_license(license)}",
             f"result={result}", f"status={status if status is not None else '-'}",
             f"duration_ms={duration_ms if duration_ms is not None else '-'}",
             f"request_id={request_id or '-'}"]
    if detail:
        parts.append('detail="' + scrub_secrets(detail).replace('"', "'")[:300] + '"')
    return scrub_secrets(" | ".join(parts))


def default_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LicenseFlow" / "logs"
    return Path.home() / ".licenseflow" / "logs"


class AuditLogger:
    def __init__(self, enabled: Optional[bool] = None, directory: Optional[str] = None, actor: str = "app",
                 max_bytes: int = 10 * 1024 * 1024, retention_days: int = 14):
        if enabled is None:
            enabled = os.environ.get("LICENSEFLOW_AUDIT_LOG", "").lower() in ("1", "true", "yes")
        self.enabled = enabled
        self.directory = Path(directory) if directory else default_dir()
        self.actor, self.max_bytes, self.retention_days = actor, max_bytes, retention_days

    def write(self, action: str, result: str, **kw) -> None:
        if not self.enabled:
            return
        try:
            kw.setdefault("actor", self.actor)
            line = format_audit_line(action, result, **kw)
            self.directory.mkdir(parents=True, exist_ok=True)
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = self.directory / f"licenseflow-audit-{day}.txt"
            if path.exists() and path.stat().st_size >= self.max_bytes:
                path.rename(self.directory / f"licenseflow-audit-{day}-{int(time.time())}.txt")
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._prune()
        except Exception:
            pass  # logging must never break licensing

    def _prune(self) -> None:
        cutoff = time.time() - timedelta(days=self.retention_days).total_seconds()
        for p in self.directory.glob("licenseflow-audit-*.txt"):
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
