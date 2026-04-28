"""Codex (chatgpt.com / OpenAI Codex) usage provider."""

from __future__ import annotations

from datetime import datetime, timezone

import keyring
import requests
from pycookiecheat import BrowserType, get_cookies

from providers import BaseProvider, UsageMetric

API_BASE = "https://chatgpt.com"
SESSION_ENDPOINT = f"{API_BASE}/api/auth/session"
USAGE_ENDPOINT = f"{API_BASE}/backend-api/wham/usage"

# Cookie name verified 2026-04-28. chatgpt.com is a production NextAuth
# deployment, hence the __Secure- prefix.
SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"

KEYCHAIN_SERVICE = "cc-usage-tracker"
KEYCHAIN_ACCOUNT = "codex-session-key"

SUPPORTED_BROWSERS = {
    "Brave": BrowserType.BRAVE,
    "Chrome": BrowserType.CHROME,
    "Chromium": BrowserType.CHROMIUM,
    "Firefox": BrowserType.FIREFOX,
}


def extract_session_key(browser_name: str = "Brave") -> str | None:
    """Extract the chatgpt.com session cookie from the given browser."""
    browser_type = SUPPORTED_BROWSERS.get(browser_name)
    if not browser_type:
        raise ValueError(f"Unsupported browser: {browser_name}")

    cookies = get_cookies(API_BASE, browser=browser_type)
    return cookies.get(SESSION_COOKIE_NAME)


def _save_session_key(value: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, value)


def _load_session_key() -> str | None:
    return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)


def _delete_session_key() -> None:
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


def _unix_to_iso(epoch_seconds: int | float | None) -> str | None:
    """Convert a Unix epoch (seconds) to an ISO-8601 UTC string.

    Output format matches what app.time_remaining() expects (parseable by
    datetime.fromisoformat).
    """
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def _get_access_token(session_key: str) -> str:
    """Exchange the NextAuth session cookie for a short-lived Bearer token.

    chatgpt.com's /backend-api/* endpoints reject cookie-only requests; the
    session cookie alone returns 401. This helper performs the standard
    NextAuth session exchange.
    """
    resp = requests.get(
        SESSION_ENDPOINT,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
        cookies={SESSION_COOKIE_NAME: session_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("accessToken")
    if not token:
        raise RuntimeError("NextAuth session response missing accessToken")
    return token


class CodexProvider(BaseProvider):
    name = "Codex"
    short_name = "CX"
    supports_browser_auth = True

    def __init__(self, session_key: str = "", browser: str = "Brave"):
        self._session_key = session_key  # in-memory only
        self.browser = browser

    @property
    def session_key(self) -> str:
        if not self._session_key:
            self._session_key = _load_session_key() or ""
        return self._session_key

    @session_key.setter
    def session_key(self, value: str) -> None:
        self._session_key = value
        if value:
            _save_session_key(value)
        else:
            _delete_session_key()

    def is_configured(self) -> bool:
        return bool(self.session_key)

    def fetch(self) -> list[UsageMetric]:
        if not self.session_key:
            raise RuntimeError("CodexProvider not configured: session key missing")

        access_token = _get_access_token(self.session_key)

        resp = requests.get(
            USAGE_ENDPOINT,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Authorization": f"Bearer {access_token}",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        metrics: list[UsageMetric] = []

        rate_limit = data.get("rate_limit") or {}
        primary = rate_limit.get("primary_window")
        if primary:
            metrics.append(UsageMetric(
                label="5-hour",
                utilization=primary.get("used_percent") or 0,
                resets_at=_unix_to_iso(primary.get("reset_at")),
                is_primary=True,
            ))
        secondary = rate_limit.get("secondary_window")
        if secondary:
            metrics.append(UsageMetric(
                label="7-day",
                utilization=secondary.get("used_percent") or 0,
                resets_at=_unix_to_iso(secondary.get("reset_at")),
            ))

        for entry in data.get("additional_rate_limits") or []:
            limit_name = entry.get("limit_name", "Unknown")
            sub_rl = entry.get("rate_limit") or {}
            sub_secondary = sub_rl.get("secondary_window")
            if sub_secondary:
                metrics.append(UsageMetric(
                    label=f"7-day {limit_name}",
                    utilization=sub_secondary.get("used_percent") or 0,
                    resets_at=_unix_to_iso(sub_secondary.get("reset_at")),
                ))

        code_review = data.get("code_review_rate_limit")
        if code_review:
            cr_primary = code_review.get("primary_window")
            if cr_primary:
                metrics.append(UsageMetric(
                    label="Code review 5-hour",
                    utilization=cr_primary.get("used_percent") or 0,
                    resets_at=_unix_to_iso(cr_primary.get("reset_at")),
                ))
            cr_secondary = code_review.get("secondary_window")
            if cr_secondary:
                metrics.append(UsageMetric(
                    label="Code review 7-day",
                    utilization=cr_secondary.get("used_percent") or 0,
                    resets_at=_unix_to_iso(cr_secondary.get("reset_at")),
                ))

        return metrics

    def auto_setup(self) -> str:
        """Extract the chatgpt.com session cookie and save it.

        Unlike Claude there is no org-discovery step — Codex rate limits are
        user-level. Returns a status message; raises on failure.
        """
        key = extract_session_key(self.browser)
        if not key:
            raise RuntimeError(
                f"Could not find a session cookie for chatgpt.com in {self.browser}.\n"
                "Make sure you are logged into chatgpt.com."
            )
        self.session_key = key  # saves to Keychain via property setter
        return "Connected to Codex"

    def refresh_cookie(self) -> bool:
        try:
            key = extract_session_key(self.browser)
            if key:
                self.session_key = key
                return True
        except Exception:
            pass
        return False

    def get_config_fields(self) -> list[dict]:
        raise NotImplementedError  # implemented in Task 6

    def apply_config(self, values: dict) -> None:
        if "session_key" in values and values["session_key"]:
            self.session_key = values["session_key"]
        self.browser = values.get("browser", self.browser)

    def to_dict(self) -> dict:
        """Serialize non-sensitive config only. Session key is in Keychain."""
        return {"browser": self.browser}

    @classmethod
    def from_dict(cls, data: dict) -> CodexProvider:
        return cls(browser=data.get("browser", "Brave"))
