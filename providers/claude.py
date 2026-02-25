"""Claude (claude.ai) usage provider."""

from __future__ import annotations

import keyring
import requests
from pycookiecheat import BrowserType, get_cookies

from providers import BaseProvider, UsageMetric

# Mapping of API keys to human-readable labels
METRIC_LABELS = {
    "five_hour": ("5-hour", True),  # (label, is_primary)
    "seven_day": ("7-day", False),
    "seven_day_sonnet": ("7-day Sonnet", False),
    "seven_day_opus": ("7-day Opus", False),
    "seven_day_cowork": ("7-day Cowork", False),
    "seven_day_oauth_apps": ("7-day OAuth", False),
    "extra_usage": ("Extra Usage", False),
}

API_BASE = "https://claude.ai"
KEYCHAIN_SERVICE = "cc-usage-tracker"
KEYCHAIN_ACCOUNT = "claude-session-key"

# Browser types we can extract cookies from (Chromium-based + Firefox)
SUPPORTED_BROWSERS = {
    "Brave": BrowserType.BRAVE,
    "Chrome": BrowserType.CHROME,
    "Chromium": BrowserType.CHROMIUM,
    "Firefox": BrowserType.FIREFOX,
}


def extract_session_key(browser_name: str = "Brave") -> str | None:
    """Extract the sessionKey cookie for claude.ai from the given browser.

    Returns the cookie value, or None if not found.
    Raises on Keychain/permission errors.
    """
    browser_type = SUPPORTED_BROWSERS.get(browser_name)
    if not browser_type:
        raise ValueError(f"Unsupported browser: {browser_name}")

    cookies = get_cookies(API_BASE, browser=browser_type)
    return cookies.get("sessionKey")


def discover_organizations(session_key: str) -> list[dict]:
    """Fetch the list of organizations the user belongs to.

    Returns list of dicts with at least 'uuid' and 'name' keys.
    """
    resp = requests.get(
        f"{API_BASE}/api/organizations",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
        cookies={"sessionKey": session_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _save_session_key(value: str) -> None:
    """Store the session key in macOS Keychain."""
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, value)


def _load_session_key() -> str | None:
    """Retrieve the session key from macOS Keychain."""
    return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)


def _delete_session_key() -> None:
    """Remove the session key from macOS Keychain."""
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


class ClaudeProvider(BaseProvider):
    name = "Claude"
    short_name = "CC"

    def __init__(self, org_id: str = "", session_key: str = "", browser: str = "Brave"):
        self.org_id = org_id
        self._session_key = session_key  # in-memory only
        self.browser = browser

    @property
    def session_key(self) -> str:
        """Load session key from Keychain if not in memory."""
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
        return bool(self.org_id and self.session_key)

    def fetch(self) -> list[UsageMetric]:
        url = f"{API_BASE}/api/organizations/{self.org_id}/usage"
        resp = requests.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            },
            cookies={"sessionKey": self.session_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        metrics = []
        for key, (label, is_primary) in METRIC_LABELS.items():
            entry = data.get(key)
            if entry is None:
                continue
            metrics.append(
                UsageMetric(
                    label=label,
                    utilization=entry.get("utilization", 0),
                    resets_at=entry.get("resets_at"),
                    is_primary=is_primary,
                )
            )
        return metrics

    def auto_setup(self) -> str:
        """Automatically extract cookie and discover org.

        Returns a human-readable status message.
        Raises on failure.
        """
        # Step 1: Extract cookie from browser
        key = extract_session_key(self.browser)
        if not key:
            raise RuntimeError(
                f"Could not find a sessionKey cookie for claude.ai in {self.browser}.\n"
                "Make sure you are logged into claude.ai."
            )
        self.session_key = key  # saves to Keychain via property setter

        # Step 2: Discover organization
        orgs = discover_organizations(self.session_key)
        if not orgs:
            raise RuntimeError("No organizations found for this account.")

        # Use the first org (most users have one)
        org = orgs[0]
        self.org_id = org.get("uuid", "")
        org_name = org.get("name", "Unknown")

        return f"Connected as '{org_name}'"

    def refresh_cookie(self) -> bool:
        """Re-extract the cookie from the browser. Returns True if successful."""
        try:
            key = extract_session_key(self.browser)
            if key:
                self.session_key = key  # saves to Keychain
                return True
        except Exception:
            pass
        return False

    def get_config_fields(self) -> list[dict]:
        return [
            {
                "key": "org_id",
                "label": "Organization ID",
                "message": (
                    "Enter your Organization ID\n\n"
                    "Find it in the API URL:\n"
                    "claude.ai/api/organizations/{THIS_PART}/usage"
                ),
                "secure": False,
                "default": self.org_id,
            },
            {
                "key": "session_key",
                "label": "Session Key",
                "message": (
                    "Enter your sessionKey cookie value\n\n"
                    "1. Go to claude.ai in your browser\n"
                    "2. Open DevTools (\u2318\u2325I)\n"
                    "3. Go to Application \u2192 Cookies \u2192 claude.ai\n"
                    "4. Copy the 'sessionKey' value\n\n"
                    "This will be stored in your macOS Keychain."
                ),
                "secure": True,
                "default": "",
            },
        ]

    def apply_config(self, values: dict) -> None:
        self.org_id = values.get("org_id", self.org_id)
        if "session_key" in values and values["session_key"]:
            self.session_key = values["session_key"]  # saves to Keychain
        self.browser = values.get("browser", self.browser)

    def to_dict(self) -> dict:
        """Serialize non-sensitive config only. Session key is in Keychain."""
        return {
            "org_id": self.org_id,
            "browser": self.browser,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ClaudeProvider:
        return cls(
            org_id=data.get("org_id", ""),
            browser=data.get("browser", "Brave"),
            # session_key loaded from Keychain on demand via property
        )
