"""Codex (chatgpt.com / OpenAI Codex) usage provider."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

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

# NextAuth v4 splits session JWTs across multiple cookies when the value
# exceeds ALLOWED_COOKIE_SIZE (4096) - ESTIMATED_EMPTY_COOKIE_SIZE (163).
# chatgpt.com's session JWT is large enough to always be chunked.
NEXTAUTH_CHUNK_SIZE = 3933

KEYCHAIN_SERVICE = "cc-usage-tracker"
KEYCHAIN_ACCOUNT = "codex-session-key"

# A complete current Chrome-on-macOS UA. Cloudflare binds cf_clearance to the
# fingerprint that solved the challenge — sending a truncated UA invalidates it.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

SUPPORTED_BROWSERS = {
    "Brave": BrowserType.BRAVE,
    "Chrome": BrowserType.CHROME,
    "Chromium": BrowserType.CHROMIUM,
    "Firefox": BrowserType.FIREFOX,
}


def _reassemble_session_cookie(cookies: dict) -> str | None:
    """Return the NextAuth session value, reassembling chunks if present.

    Prefers the unsplit name when it exists (older deployments / small JWTs).
    Otherwise concatenates `${SESSION_COOKIE_NAME}.0`, `.1`, ... in numeric
    order — the same scheme NextAuth's server-side `SessionStore` uses to
    rejoin chunks.
    """
    unsplit = cookies.get(SESSION_COOKIE_NAME)
    if unsplit:
        return unsplit
    chunks: list[str] = []
    i = 0
    while True:
        value = cookies.get(f"{SESSION_COOKIE_NAME}.{i}")
        if value is None:
            break
        chunks.append(value)
        i += 1
    return "".join(chunks) if chunks else None


def extract_session_key(browser_name: str = "Brave") -> str | None:
    """Extract the chatgpt.com session cookie from the given browser."""
    browser_type = SUPPORTED_BROWSERS.get(browser_name)
    if not browser_type:
        raise ValueError(f"Unsupported browser: {browser_name}")

    cookies = get_cookies(API_BASE, browser=browser_type)
    return _reassemble_session_cookie(cookies)


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


DEFAULT_AUTHJSON_PATH = Path.home() / ".codex" / "auth.json"


def _load_authjson_token(path: Path | None = None) -> str | None:
    """Return the access_token from ~/.codex/auth.json, or None.

    The official `codex` CLI writes this file (mode 0600) when the user
    runs `codex login` and rotates the token there. We only ever read it
    — refresh is delegated to the CLI itself. Any error (file missing,
    malformed JSON, missing/blank token) returns None so the caller can
    fall back to the cookie path or surface a "not configured" error.

    Best-effort: this does not validate file mode, ownership, or whether
    the path is a symlink. The CLI owns the file; we just read it. A
    concurrent CLI rewrite that lands mid-read produces a JSONDecodeError
    here and we return None — the next poll picks up the new token.
    """
    p = path if path is not None else DEFAULT_AUTHJSON_PATH
    try:
        raw = p.read_text()
    except (FileNotFoundError, OSError, PermissionError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    token = tokens.get("access_token")
    return token if isinstance(token, str) and token else None


def _build_cookie_jar(session_key: str, browser_name: str | None = None) -> dict:
    """Cookies for a chatgpt.com API call.

    chatgpt.com is fronted by Cloudflare bot mitigation. Requests without
    cf_clearance / __cf_bm receive 403 with cf-mitigated=challenge, so we
    forward the full browser jar when available. The Keychain-cached session
    key wins over any stale browser-side session cookies — those are dropped
    before we re-emit the cached value as `.0`, `.1`, ... chunks at NextAuth's
    expected boundary so the server-side `SessionStore` can reassemble it.
    """
    jar: dict = {}
    browser_type = SUPPORTED_BROWSERS.get(browser_name) if browser_name else None
    if browser_type is not None:
        try:
            jar = dict(get_cookies(API_BASE, browser=browser_type))
        except Exception:
            jar = {}

    if session_key:
        for name in [
            n for n in jar
            if n == SESSION_COOKIE_NAME or n.startswith(f"{SESSION_COOKIE_NAME}.")
        ]:
            del jar[name]
        chunks = [
            session_key[i : i + NEXTAUTH_CHUNK_SIZE]
            for i in range(0, len(session_key), NEXTAUTH_CHUNK_SIZE)
        ] or [session_key]
        for idx, chunk in enumerate(chunks):
            jar[f"{SESSION_COOKIE_NAME}.{idx}"] = chunk
    return jar


def _get_access_token(session_key: str, browser: str | None = None) -> str:
    """Exchange the NextAuth session cookie for a short-lived Bearer token.

    chatgpt.com's /backend-api/* endpoints reject cookie-only requests; the
    session cookie alone returns 401. This helper performs the standard
    NextAuth session exchange.

    `allow_redirects=False` is critical: dict-sourced cookies have no domain
    binding and would be sent on any cross-origin 3xx, leaking the session
    cookie + cf_clearance to whatever host chatgpt.com redirected to.
    """
    resp = requests.get(
        SESSION_ENDPOINT,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        cookies=_build_cookie_jar(session_key, browser),
        allow_redirects=False,
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
        """True if either the official CLI's auth.json yields a token or we have
        a session key cached. auth.json takes precedence at fetch time."""
        if _load_authjson_token() is not None:
            return True
        return bool(self.session_key)

    def fetch(self) -> list[UsageMetric]:
        """Fetch usage metrics, preferring ~/.codex/auth.json over browser cookies.

        When the official `codex` CLI is logged in, auth.json yields a fresh
        JWT and the cookie path is skipped entirely. On 401 from the auth.json
        path, we surface a `codex login` hint rather than silently falling
        back — refresh is delegated to the CLI itself.
        """
        authjson_token = _load_authjson_token()
        if authjson_token is not None:
            try:
                return self._fetch_usage_with_bearer(authjson_token)
            except requests.exceptions.HTTPError as e:
                response = getattr(e, "response", None)
                if response is not None and response.status_code == 401:
                    raise RuntimeError(
                        "Codex auth.json token expired. Run `codex login` to refresh."
                    ) from e
                raise

        if not self.session_key:
            raise RuntimeError("CodexProvider not configured: session key missing")
        cookie_token = _get_access_token(self.session_key, self.browser)
        return self._fetch_usage_with_bearer(cookie_token)

    def _fetch_usage_with_bearer(self, access_token: str) -> list[UsageMetric]:
        """Issue the /wham/usage call with a bearer token and parse metrics.

        The token may come from either the NextAuth session exchange
        (cookie path) or from ~/.codex/auth.json (CLI path). Both produce
        JWTs the wham endpoint accepts.
        """
        resp = requests.get(
            USAGE_ENDPOINT,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Authorization": f"Bearer {access_token}",
            },
            allow_redirects=False,
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
        return [
            {
                "key": "session_key",
                "label": "Session Cookie",
                "message": (
                    "Enter your chatgpt.com session cookie value\n\n"
                    "1. Go to chatgpt.com in your browser\n"
                    "2. Open DevTools (⌘⌥I)\n"
                    "3. Application → Cookies → chatgpt.com\n"
                    f"4. Copy the '{SESSION_COOKIE_NAME}' value.\n"
                    "   If it's split into '.0', '.1', ... parts, paste\n"
                    "   them concatenated in order with no separator.\n\n"
                    "Tip: Auto Setup is easier — it reads the cookie\n"
                    "directly from your browser.\n\n"
                    "This will be stored in your macOS Keychain."
                ),
                "secure": True,
                "default": "",
            },
        ]

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
