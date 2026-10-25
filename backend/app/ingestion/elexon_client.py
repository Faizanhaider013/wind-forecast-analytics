"""HTTP client for the Elexon BMRS Insights API.

Uses only the Python standard library (``urllib``) so Phase 1 adds no runtime
dependency. The single network call goes through an injectable ``transport``
callable, which lets tests supply canned responses without any live HTTP or
third-party mocking library.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from . import config


class ElexonAPIError(RuntimeError):
    """Raised when the API cannot be queried successfully or returns bad data."""


@dataclass(frozen=True)
class HttpResponse:
    """Minimal transport result: an HTTP status and the raw response body."""

    status: int
    body: bytes


# A transport maps a fully-qualified URL to an HttpResponse. The default uses
# urllib; tests inject a fake. Network/timeout failures must raise OSError (or a
# subclass such as urllib.error.URLError) so the retry logic can catch them.
Transport = Callable[[str, float], HttpResponse]


def _urllib_transport(url: str, timeout: float) -> HttpResponse:
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
            return HttpResponse(status=resp.status, body=resp.read())
    except urllib.error.HTTPError as exc:
        # HTTPError carries a status and a readable body; surface both so the
        # retry/raise logic can decide based on the status code.
        body = b""
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - defensive
            pass
        return HttpResponse(status=exc.code, body=body)


class ElexonClient:
    """Thin client for the two datasets Phase 1 needs: FUELHH and WINDFOR."""

    def __init__(
        self,
        base_url: str = config.BASE_URL,
        transport: Transport | None = None,
        *,
        timeout: float = config.HTTP_TIMEOUT_SECONDS,
        max_attempts: int = config.HTTP_MAX_ATTEMPTS,
        backoff: float = config.HTTP_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _urllib_transport
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff = backoff
        self._sleep = sleep

    # -- low level ----------------------------------------------------------

    def _build_url(self, path: str, params: Sequence[tuple[str, str]]) -> str:
        query = urllib.parse.urlencode(list(params))
        return f"{self.base_url}{path}?{query}"

    def _get_json(self, path: str, params: Sequence[tuple[str, str]]) -> dict[str, Any]:
        """GET a URL and decode its JSON body, with bounded retries.

        Retries transient failures (network errors, timeouts, and the HTTP
        statuses in ``config.HTTP_RETRY_STATUS``) with exponential backoff.
        Non-retryable 4xx responses and malformed JSON raise immediately.
        """
        url = self._build_url(path, params)
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.transport(url, self.timeout)
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_error = exc
                self._maybe_backoff(attempt, reason=f"network error: {exc}")
                continue

            if response.status == 200:
                try:
                    return json.loads(response.body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ElexonAPIError(
                        f"malformed JSON from {url}: {exc}"
                    ) from exc

            if response.status in config.HTTP_RETRY_STATUS:
                last_error = ElexonAPIError(
                    f"HTTP {response.status} from {url}"
                )
                self._maybe_backoff(attempt, reason=f"HTTP {response.status}")
                continue

            # Non-retryable (e.g. 400 bad window, 404). Surface the body so the
            # caller sees the API's own validation message.
            detail = response.body.decode("utf-8", errors="replace")[:500]
            raise ElexonAPIError(
                f"HTTP {response.status} from {url}: {detail}"
            )

        raise ElexonAPIError(
            f"giving up after {self.max_attempts} attempts for {url}: {last_error}"
        )

    def _maybe_backoff(self, attempt: int, *, reason: str) -> None:
        if attempt < self.max_attempts:
            delay = self.backoff * (2 ** (attempt - 1))
            print(
                f"    ! request attempt {attempt} failed ({reason}); "
                f"retrying in {delay:.0f}s"
            )
            self._sleep(delay)

    @staticmethod
    def _extract_rows(payload: dict[str, Any], url_hint: str) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or "data" not in payload:
            raise ElexonAPIError(
                f"unexpected response shape (no 'data' key) for {url_hint}"
            )
        rows = payload["data"]
        if not isinstance(rows, list):
            raise ElexonAPIError(f"'data' is not a list for {url_hint}")
        return rows

    # -- datasets -----------------------------------------------------------

    def fetch_fuelhh_wind(
        self, settlement_date_from: str, settlement_date_to: str
    ) -> list[dict[str, Any]]:
        """Fetch FUELHH wind actuals for an inclusive settlement-date window.

        ``settlement_date_from``/``to`` are ``YYYY-MM-DD`` strings; the inclusive
        range must not exceed ``config.MAX_WINDOW_DAYS`` (enforced by the API).
        """
        params = [
            ("settlementDateFrom", settlement_date_from),
            ("settlementDateTo", settlement_date_to),
            ("fuelType", config.WIND_FUEL_TYPE),
            ("format", "json"),
        ]
        payload = self._get_json(config.FUELHH_PATH, params)
        return self._extract_rows(payload, config.FUELHH_PATH)

    def fetch_windfor(
        self, publish_from_iso: str, publish_to_iso: str
    ) -> list[dict[str, Any]]:
        """Fetch WINDFOR forecasts for an inclusive publish-time window.

        ``publish_from_iso``/``to`` are ISO-8601 UTC strings (``...Z``). WINDFOR
        has no target-time filter, so every vintage published in the window is
        returned and the caller must filter by target time afterwards.
        """
        params = [
            ("publishDateTimeFrom", publish_from_iso),
            ("publishDateTimeTo", publish_to_iso),
            ("format", "json"),
        ]
        payload = self._get_json(config.WINDFOR_PATH, params)
        return self._extract_rows(payload, config.WINDFOR_PATH)
