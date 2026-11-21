"""Runtime configuration for DAGonService.

Every setting is read from an environment variable so that the service can be
configured identically under Docker Compose, a process manager, or a test
harness. The legacy ``MONGO_DB`` variable of the 2018 prototype is still
honoured, so existing ``docker-compose.yml`` files keep working.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

DUPLICATE_POLICIES = ("replace", "reject", "keep")


def _flag(value: Optional[str], default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Optional[str], default: int, minimum: int = 0) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("expected an integer, got %r" % value) from exc
    if parsed < minimum:
        raise ValueError("expected an integer >= %d, got %d" % (minimum, parsed))
    return parsed


@dataclass
class Settings:
    """Validated service settings.

    Use :meth:`from_env` in production; tests build the dataclass directly.
    """

    mongo_uri: str = "mongodb://localhost:27017"
    db_name: str = "dagon"
    duplicate_policy: str = "replace"
    api_token: Optional[str] = None
    protect_reads: bool = False
    webhook_urls: List[str] = field(default_factory=list)
    webhook_timeout: float = 2.0
    max_history: int = 1000
    dashboard: bool = True
    dashboard_refresh_ms: int = 3000
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.duplicate_policy not in DUPLICATE_POLICIES:
            raise ValueError(
                "DAGONSERVICE_DUPLICATE_POLICY must be one of %s, got %r"
                % (", ".join(DUPLICATE_POLICIES), self.duplicate_policy))
        if self.api_token is not None and self.api_token.strip() == "":
            self.api_token = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        mongo_uri = env.get("DAGONSERVICE_MONGO_URI", "").strip()
        if not mongo_uri:
            legacy_host = env.get("MONGO_DB", "").strip()
            mongo_uri = ("mongodb://%s:27017" % legacy_host) if legacy_host else cls.mongo_uri
        webhooks = [url.strip() for url in env.get("DAGONSERVICE_WEBHOOK_URLS", "").split(",") if url.strip()]
        return cls(
            mongo_uri=mongo_uri,
            db_name=env.get("DAGONSERVICE_DB_NAME", "").strip() or cls.db_name,
            duplicate_policy=(env.get("DAGONSERVICE_DUPLICATE_POLICY", "").strip().lower() or cls.duplicate_policy),
            api_token=env.get("DAGONSERVICE_API_TOKEN"),
            protect_reads=_flag(env.get("DAGONSERVICE_PROTECT_READS"), False),
            webhook_urls=webhooks,
            webhook_timeout=float(env.get("DAGONSERVICE_WEBHOOK_TIMEOUT", "") or 2.0),
            max_history=_int(env.get("DAGONSERVICE_MAX_HISTORY"), 1000, minimum=1),
            dashboard=_flag(env.get("DAGONSERVICE_DASHBOARD"), True),
            dashboard_refresh_ms=_int(env.get("DAGONSERVICE_DASHBOARD_REFRESH_MS"), 3000, minimum=500),
            log_level=(env.get("DAGONSERVICE_LOG_LEVEL", "").strip().upper() or "INFO"),
        )

    def public(self) -> Dict[str, Any]:
        """Return the settings that are safe to show (no URI credentials, no token)."""
        return {
            "db_name": self.db_name,
            "duplicate_policy": self.duplicate_policy,
            "auth_enabled": self.api_token is not None,
            "protect_reads": self.protect_reads,
            "webhooks": len(self.webhook_urls),
            "max_history": self.max_history,
            "dashboard": self.dashboard,
        }
