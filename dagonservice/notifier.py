"""Optional webhook notifications for workflow events.

This replaces the Socket.IO "Centinel" client of the 2018 prototype, which
depended on an unmaintained Python 2 era library and never connected because
its URL was undefined. When ``DAGONSERVICE_WEBHOOK_URLS`` is set, each event
recorded by the store is POSTed as JSON to every URL. Delivery is
best-effort: it runs on a small background pool, uses a short timeout, and a
failing receiver never delays or fails the DAGonStar request that caused the
event.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)


class WebhookNotifier:
    def __init__(self, urls: List[str], timeout: float = 2.0, max_workers: int = 2) -> None:
        self.urls = [url for url in urls if url.startswith(("http://", "https://"))]
        ignored = set(urls) - set(self.urls)
        if ignored:
            LOG.warning("Ignoring webhook URLs that are not http(s): %s", ", ".join(sorted(ignored)))
        self.timeout = timeout
        self._pool: Optional[ThreadPoolExecutor] = (
            ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dagonservice-webhook")
            if self.urls else None)

    @property
    def enabled(self) -> bool:
        return self._pool is not None

    def publish(self, event: Dict[str, Any]) -> None:
        if self._pool is None:
            return
        body = json.dumps(event, default=str).encode("utf-8")
        for url in self.urls:
            self._pool.submit(self._deliver, url, body)

    def _deliver(self, url: str, body: bytes) -> None:
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "DAGonService-webhook"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (admin-configured URL)
                response.read(0)
        except Exception as exc:
            LOG.warning("Webhook delivery to %s failed: %s", url, exc)

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False)
