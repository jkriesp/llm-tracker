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
        raise NotImplementedError  # implemented in Task 4

    def auto_setup(self) -> str:
        raise NotImplementedError  # implemented in Task 5

    def refresh_cookie(self) -> bool:
        return False  # implemented in Task 5

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
