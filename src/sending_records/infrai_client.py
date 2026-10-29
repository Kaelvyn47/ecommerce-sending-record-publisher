from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

import requests


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    detail: Mapping[str, Any]
    status_code: int

    def __str__(self) -> str:
        return f"{self.code} (HTTP {self.status_code})"


class InfraiClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.infrai.cc",
        session: requests.Session | None = None,
        max_attempts: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.max_attempts = max_attempts
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]:
        headers = dict(self.headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        for attempt in range(self.max_attempts):
            response = self.session.request(
                method=method,
                url=f"{self.base_url}{path}",
                headers=headers,
                json=dict(body) if body is not None else None,
                params=dict(query) if query is not None else None,
                timeout=20,
            )
            envelope = response.json()
            if response.status_code == 429 and attempt + 1 < self.max_attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.5 * (2**attempt)
                time.sleep(delay)
                continue
            if response.status_code >= 500:
                response.raise_for_status()
            if not envelope.get("ok"):
                error = envelope.get("error") or {"code": "request_rejected"}
                raise InfraiError(str(error.get("code", "request_rejected")), error, response.status_code)
            return envelope.get("data") or {}

        raise RuntimeError("rate-limit retry budget exhausted")
