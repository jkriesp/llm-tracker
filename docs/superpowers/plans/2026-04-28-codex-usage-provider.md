# Codex Usage Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `CodexProvider` that reports OpenAI Codex (chatgpt.com) usage in the existing macOS menu bar app, alongside `ClaudeProvider`.

**Architecture:** Mirrors the existing `ClaudeProvider` pattern with one extra step: chatgpt.com's `/backend-api/*` rejects cookie-only requests, so each fetch first exchanges the NextAuth session cookie for a short-lived Bearer token via `GET https://chatgpt.com/api/auth/session`, then calls `GET https://chatgpt.com/backend-api/wham/usage` with `Authorization: Bearer <token>`. Maps the response to `UsageMetric` objects (5-hour primary window, 7-day secondary window, plus per-model `additional_rate_limits` and optional `code_review_rate_limit`). A small refactor adds `supports_browser_auth: bool` to `BaseProvider` so `app.py` can wire the Configure submenu and 401 recovery without `isinstance` proliferation.

**Tech Stack:** Python 3, `requests`, `pycookiecheat` (cookie extraction), `keyring` (macOS Keychain), `rumps` (menu bar UI), `pytest` (tests). All deps already pinned in `requirements.txt`. macOS-only at runtime; tests are platform-independent (mocks in `tests/conftest.py`).

**Spec:** [docs/superpowers/specs/2026-04-28-codex-usage-provider-design.md](../specs/2026-04-28-codex-usage-provider-design.md)

**Branch:** `feat/codex-provider` (already created, spec already committed)

---

## File Structure

**New files:**
- `providers/codex.py` — `CodexProvider` class and module-level helpers
- `tests/test_codex_provider.py` — unit tests for the provider

**Modified files:**
- `providers/__init__.py` — add `supports_browser_auth` flag and stub `auto_setup`/`refresh_cookie` on `BaseProvider`
- `providers/claude.py` — set `supports_browser_auth = True` on `ClaudeProvider`
- `app.py` — register `CodexProvider`, replace `isinstance(provider, ClaudeProvider)` checks with the capability flag, parameterise `_run_auto_setup(provider)`
- `tests/test_provider_base.py` — assert the new flag and stub methods exist
- `tests/test_claude_provider.py` — assert `supports_browser_auth=True` on `ClaudeProvider`

**Out of scope:** Reading `~/.codex/auth.json`. Tracking ChatGPT chat usage. Tracking platform.openai.com API usage. Surfacing `credits.balance` / `spend_control`. Refactoring Claude/Codex into a shared `CookieAuthProvider` base.

---

## Task 0: Preflight — verify the chatgpt.com auth flow ✅ COMPLETED 2026-04-28

**Findings (recorded for downstream tasks):**

- **Session cookie name:** `__Secure-next-auth.session-token` ✓ (verified against Brave)
- **`/backend-api/wham/usage` cannot be called with the cookie directly** — returns `401 {"detail":"Unauthorized"}`
- **Required flow:** two-step NextAuth exchange:
  1. `GET https://chatgpt.com/api/auth/session` with `Cookie: __Secure-next-auth.session-token=<value>` → JSON response with top-level keys including `accessToken`, `expires`, `user`, `account`
  2. `GET https://chatgpt.com/backend-api/wham/usage` with `Authorization: Bearer <accessToken>` (no cookie required on this call) → usage JSON
- **`used_percent` scale:** integer 0–100 (verified — primary_window.used_percent is `1` of type `int`)
- **No additional headers required** beyond `Accept` and `User-Agent` on both endpoints

These findings drive the implementation in Task 2 (constants) and Task 4 (fetch). No commit; this task produced no code, only confirmed facts.

---

## Task 1: Add `supports_browser_auth` flag to `BaseProvider`

**Files:**
- Modify: `providers/__init__.py:27-66`
- Modify: `providers/claude.py:88-90` (add one line)
- Test: `tests/test_provider_base.py`
- Test: `tests/test_claude_provider.py:21-28` (extend `TestClaudeProviderInit.test_defaults`)

- [ ] **Step 1: Write the failing test for the new flag and stub methods**

Edit `tests/test_provider_base.py`. Replace the `TestBaseProvider` class with the version below (additions at the end).

```python
class TestBaseProvider:
    def test_class_attrs(self):
        assert BaseProvider.name == "Unknown"
        assert BaseProvider.short_name == "??"
        assert BaseProvider.supports_browser_auth is False

    def test_methods_raise(self):
        p = BaseProvider()
        import pytest

        with pytest.raises(NotImplementedError):
            p.is_configured()
        with pytest.raises(NotImplementedError):
            p.fetch()
        with pytest.raises(NotImplementedError):
            p.get_config_fields()
        with pytest.raises(NotImplementedError):
            p.apply_config({})
        with pytest.raises(NotImplementedError):
            p.to_dict()
        with pytest.raises(NotImplementedError):
            BaseProvider.from_dict({})
        with pytest.raises(NotImplementedError):
            p.auto_setup()

    def test_refresh_cookie_default_returns_false(self):
        p = BaseProvider()
        assert p.refresh_cookie() is False
```

- [ ] **Step 2: Run the failing test**

```bash
source /Users/daudir/Projects/cc-usage-tracker/.venv/bin/activate
pytest tests/test_provider_base.py -v
```

Expected: `test_class_attrs`, `test_methods_raise`, and `test_refresh_cookie_default_returns_false` FAIL with `AttributeError` on `supports_browser_auth`, and `auto_setup`/`refresh_cookie` not being defined.

- [ ] **Step 3: Add the flag and stubs to `BaseProvider`**

Edit `providers/__init__.py`. Replace the `BaseProvider` class with:

```python
class BaseProvider:
    """Base class for usage providers.

    To add a new provider (e.g., OpenAI):
    1. Create a new file in providers/ (e.g., openai.py)
    2. Subclass BaseProvider
    3. Implement all methods
    4. Register it in PROVIDERS in app.py
    """

    name: str = "Unknown"
    short_name: str = "??"  # 2-3 char abbreviation for menu bar
    supports_browser_auth: bool = False  # True if Auto Setup / Refresh Cookie apply

    def is_configured(self) -> bool:
        raise NotImplementedError

    def fetch(self) -> list[UsageMetric]:
        """Fetch current usage metrics. Raises on error."""
        raise NotImplementedError

    def get_config_fields(self) -> list[dict]:
        """Return list of config fields for the setup dialog.

        Each field: {"key": str, "label": str, "message": str, "secure": bool}
        """
        raise NotImplementedError

    def apply_config(self, values: dict) -> None:
        """Apply configuration values from user input."""
        raise NotImplementedError

    def to_dict(self) -> dict:
        """Serialize provider config for persistence."""
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data: dict) -> BaseProvider:
        """Deserialize provider config."""
        raise NotImplementedError

    # ── Browser-auth capability (override in subclasses) ──────────────────────

    def auto_setup(self) -> str:
        """Cookie + auto-discover. Override in browser-auth providers.

        Returns a human-readable status message. Raises on failure.
        """
        raise NotImplementedError

    def refresh_cookie(self) -> bool:
        """Re-extract the cookie from the browser. Returns True on success.

        Default returns False so non-browser providers can still be polled.
        """
        return False
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_provider_base.py -v
```

Expected: PASS.

- [ ] **Step 5: Set `supports_browser_auth = True` on `ClaudeProvider`**

Edit `providers/claude.py`. Find the class definition (line 88):

```python
class ClaudeProvider(BaseProvider):
    name = "Claude"
    short_name = "CC"

    def __init__(self, org_id: str = "", session_key: str = "", browser: str = "Brave"):
```

Insert one line so it reads:

```python
class ClaudeProvider(BaseProvider):
    name = "Claude"
    short_name = "CC"
    supports_browser_auth = True

    def __init__(self, org_id: str = "", session_key: str = "", browser: str = "Brave"):
```

- [ ] **Step 6: Extend the Claude defaults test**

Edit `tests/test_claude_provider.py`. In `TestClaudeProviderInit.test_defaults`, append one assertion:

```python
class TestClaudeProviderInit:
    def test_defaults(self):
        p = ClaudeProvider()
        assert p.org_id == ""
        assert p._session_key == ""
        assert p.browser == "Brave"
        assert p.name == "Claude"
        assert p.short_name == "CC"
        assert p.supports_browser_auth is True
```

- [ ] **Step 7: Run all tests**

```bash
pytest tests/ -v
```

Expected: all green. No regressions.

- [ ] **Step 8: Commit**

```bash
git add providers/__init__.py providers/claude.py tests/test_provider_base.py tests/test_claude_provider.py
git commit -m "Add supports_browser_auth capability flag to BaseProvider"
```

---

## Task 2: Create `CodexProvider` skeleton — init, properties, serialization

**Files:**
- Create: `providers/codex.py`
- Create: `tests/test_codex_provider.py`

- [ ] **Step 1: Write the failing tests for init, is_configured, session_key, to_dict, from_dict, apply_config**

Create `tests/test_codex_provider.py` with:

```python
"""Tests for providers/codex.py — CodexProvider and module-level helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from providers.codex import (
    CodexProvider,
    KEYCHAIN_ACCOUNT,
    KEYCHAIN_SERVICE,
    extract_session_key,
)


# ── CodexProvider init & properties ───────────────────────────────────────────


class TestCodexProviderInit:
    def test_defaults(self):
        p = CodexProvider()
        assert p._session_key == ""
        assert p.browser == "Brave"
        assert p.name == "Codex"
        assert p.short_name == "CX"
        assert p.supports_browser_auth is True

    def test_custom_values(self):
        p = CodexProvider(session_key="sk-1", browser="Chrome")
        assert p._session_key == "sk-1"
        assert p.browser == "Chrome"


class TestIsConfigured:
    def test_false_when_empty(self, mock_keyring):
        p = CodexProvider()
        assert p.is_configured() is False

    def test_true_when_session_key_set(self, mock_keyring):
        p = CodexProvider(session_key="sk-1")
        assert p.is_configured() is True


class TestSessionKeyProperty:
    def test_reads_from_keyring(self, mock_keyring):
        mock_keyring[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] = "from-keyring"
        p = CodexProvider()
        assert p.session_key == "from-keyring"

    def test_writes_to_keyring(self, mock_keyring):
        p = CodexProvider()
        p.session_key = "new-key"
        assert mock_keyring[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] == "new-key"

    def test_clear_deletes_from_keyring(self, mock_keyring):
        mock_keyring[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] = "old-key"
        p = CodexProvider()
        p.session_key = ""
        assert (KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) not in mock_keyring

    def test_uses_distinct_keychain_account_from_claude(self):
        # Guard against accidentally sharing the Claude session entry.
        from providers.claude import KEYCHAIN_ACCOUNT as CLAUDE_ACCOUNT
        assert KEYCHAIN_ACCOUNT != CLAUDE_ACCOUNT


# ── Serialization ─────────────────────────────────────────────────────────────


class TestToDict:
    def test_excludes_session_key(self):
        p = CodexProvider(session_key="secret", browser="Chrome")
        d = p.to_dict()
        assert d == {"browser": "Chrome"}
        assert "session_key" not in d


class TestFromDict:
    def test_roundtrip(self):
        original = CodexProvider(browser="Firefox")
        restored = CodexProvider.from_dict(original.to_dict())
        assert restored.browser == "Firefox"
        assert restored._session_key == ""

    def test_missing_keys_use_defaults(self):
        p = CodexProvider.from_dict({})
        assert p.browser == "Brave"


# ── apply_config ──────────────────────────────────────────────────────────────


class TestApplyConfig:
    def test_updates_fields(self, mock_keyring):
        p = CodexProvider()
        p.apply_config({"session_key": "new-sk", "browser": "Chrome"})
        assert p.session_key == "new-sk"
        assert p.browser == "Chrome"

    def test_partial_update(self, mock_keyring):
        p = CodexProvider(browser="Brave")
        p.apply_config({"browser": "Chrome"})
        assert p.browser == "Chrome"

    def test_empty_session_key_not_overwritten(self, mock_keyring):
        p = CodexProvider(session_key="keep")
        p.apply_config({"session_key": ""})
        assert p._session_key == "keep"
```

- [ ] **Step 2: Run the failing tests**

```bash
pytest tests/test_codex_provider.py -v
```

Expected: ImportError because `providers/codex.py` doesn't exist.

- [ ] **Step 3: Create `providers/codex.py` with the skeleton**

Create the file with:

```python
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

# Cookie name verified in Task 0 preflight. Production NextAuth deployments
# (chatgpt.com is one) use the __Secure- prefix.
SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"

KEYCHAIN_SERVICE = "cc-usage-tracker"
KEYCHAIN_ACCOUNT = "codex-session-key"

# Same browser set as the Claude provider — pycookiecheat supports these.
SUPPORTED_BROWSERS = {
    "Brave": BrowserType.BRAVE,
    "Chrome": BrowserType.CHROME,
    "Chromium": BrowserType.CHROMIUM,
    "Firefox": BrowserType.FIREFOX,
}


def extract_session_key(browser_name: str = "Brave") -> str | None:
    """Extract the chatgpt.com session cookie from the given browser.

    Returns the cookie value, or None if not found.
    """
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

    Returns None if input is None. The output format matches what
    `app.time_remaining()` expects (parseable by datetime.fromisoformat).
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_codex_provider.py -v
```

Expected: PASS for all tests in `TestCodexProviderInit`, `TestIsConfigured`, `TestSessionKeyProperty`, `TestToDict`, `TestFromDict`, `TestApplyConfig`.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
pytest tests/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add providers/codex.py tests/test_codex_provider.py
git commit -m "Add CodexProvider skeleton with cookie/keychain plumbing"
```

---

## Task 3: Implement `_unix_to_iso()` and `extract_session_key()` tests

The functions are already in `providers/codex.py` from Task 2. This task adds tests for them.

**Files:**
- Modify: `tests/test_codex_provider.py` (append new test classes)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_codex_provider.py`:

```python
# ── extract_session_key ───────────────────────────────────────────────────────


class TestExtractSessionKey:
    @patch("providers.codex.get_cookies")
    def test_returns_session_key(self, mock_get_cookies):
        mock_get_cookies.return_value = {"__Secure-next-auth.session-token": "sk-abc"}
        result = extract_session_key("Brave")
        assert result == "sk-abc"

    @patch("providers.codex.get_cookies")
    def test_returns_none_when_missing(self, mock_get_cookies):
        mock_get_cookies.return_value = {"some-other-cookie": "x"}
        result = extract_session_key("Chrome")
        assert result is None

    def test_raises_for_unsupported_browser(self):
        with pytest.raises(ValueError, match="Unsupported browser"):
            extract_session_key("Safari")


# ── _unix_to_iso ──────────────────────────────────────────────────────────────


class TestUnixToIso:
    def test_returns_none_for_none(self):
        from providers.codex import _unix_to_iso
        assert _unix_to_iso(None) is None

    def test_converts_epoch_seconds_to_iso(self):
        from providers.codex import _unix_to_iso
        # epoch 1777680000 → 2026-05-02T00:00:00+00:00 (verified)
        result = _unix_to_iso(1777680000)
        assert result == "2026-05-02T00:00:00+00:00"
        # Round-trip via datetime.fromisoformat (what app.time_remaining uses)
        from datetime import datetime
        parsed = datetime.fromisoformat(result)
        assert parsed.year == 2026
        assert parsed.month == 5
        assert parsed.day == 2

    def test_round_trip_with_time_remaining(self):
        """The output must be parseable by app.time_remaining()."""
        from providers.codex import _unix_to_iso
        from app import time_remaining
        from datetime import datetime, timezone, timedelta

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        iso = _unix_to_iso(int(future.timestamp()))
        result = time_remaining(iso)
        # Should contain "h" since we set it 2 hours ahead
        assert "h" in result or "m" in result
```

The expected string `"2026-05-02T00:00:00+00:00"` was verified against `python -c "from datetime import datetime, timezone; print(datetime.fromtimestamp(1777680000, tz=timezone.utc).isoformat())"`. If your Python version emits a different format (e.g. without the `+00:00` suffix), match what it actually outputs.

- [ ] **Step 2: Run the tests**

```bash
pytest tests/test_codex_provider.py -v
```

Expected: PASS. Both `extract_session_key` and `_unix_to_iso` already exist from Task 2; this task just adds coverage.

If `test_converts_epoch_seconds_to_iso` fails because the expected ISO string doesn't match, fix the expected string to whatever the function actually returns and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_codex_provider.py
git commit -m "Add tests for Codex extract_session_key and _unix_to_iso helpers"
```

---

## Task 4: Implement `_get_access_token()` and `fetch()`

The chatgpt.com backend rejects cookie-only requests to `/backend-api/*`. Each fetch must first exchange the NextAuth session cookie for a short-lived Bearer token via `GET /api/auth/session`, then call the usage endpoint with `Authorization: Bearer <token>`. We extract the exchange into a `_get_access_token(session_key)` helper so the two-step flow is testable in isolation.

**Files:**
- Modify: `providers/codex.py` (add `_get_access_token` helper, replace the `fetch` stub)
- Modify: `tests/test_codex_provider.py` (append `TestGetAccessToken` and `TestFetch`)

- [ ] **Step 1: Write the failing tests for `_get_access_token`**

Append to `tests/test_codex_provider.py`:

```python
# ── _get_access_token ─────────────────────────────────────────────────────────


class TestGetAccessToken:
    @patch("providers.codex.requests.get")
    def test_returns_token_from_session_response(self, mock_get):
        from providers.codex import _get_access_token, SESSION_COOKIE_NAME
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "user": {"email": "test@example.com"},
                "expires": "2026-04-28T13:00:00.000Z",
                "accessToken": "bearer-xyz",
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        token = _get_access_token("sk-1")

        assert token == "bearer-xyz"
        # Verify the cookie was sent on the call
        _, kwargs = mock_get.call_args
        assert kwargs["cookies"] == {SESSION_COOKIE_NAME: "sk-1"}

    @patch("providers.codex.requests.get")
    def test_raises_when_token_missing(self, mock_get):
        from providers.codex import _get_access_token
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"user": {}})
        mock_get.return_value.raise_for_status = MagicMock()

        with pytest.raises(RuntimeError, match="accessToken"):
            _get_access_token("sk-1")

    @patch("providers.codex.requests.get")
    def test_propagates_401(self, mock_get):
        from providers.codex import _get_access_token
        from requests.exceptions import HTTPError

        resp = MagicMock(status_code=401)
        resp.raise_for_status.side_effect = HTTPError("401 Unauthorized")
        mock_get.return_value = resp

        with pytest.raises(HTTPError):
            _get_access_token("expired-cookie")


# ── fetch ─────────────────────────────────────────────────────────────────────


# Real response shape captured from the chatgpt.com Network tab on 2026-04-28.
# Plan type "prolite", one additional rate limit (GPT-5.3-Codex-Spark).
WHAM_USAGE_FIXTURE = {
    "user_id": "user-test",
    "account_id": "user-test",
    "email": "test@example.com",
    "plan_type": "prolite",
    "rate_limit": {
        "allowed": True,
        "limit_reached": False,
        "primary_window": {
            "used_percent": 1,
            "limit_window_seconds": 18000,
            "reset_after_seconds": 16184,
            "reset_at": 1777376345,
        },
        "secondary_window": {
            "used_percent": 0,
            "limit_window_seconds": 604800,
            "reset_after_seconds": 602984,
            "reset_at": 1777963145,
        },
    },
    "code_review_rate_limit": None,
    "additional_rate_limits": [
        {
            "limit_name": "GPT-5.3-Codex-Spark",
            "metered_feature": "codex_bengalfox",
            "rate_limit": {
                "allowed": True,
                "limit_reached": False,
                "primary_window": {
                    "used_percent": 0,
                    "limit_window_seconds": 18000,
                    "reset_after_seconds": 18000,
                    "reset_at": 1777378162,
                },
                "secondary_window": {
                    "used_percent": 0,
                    "limit_window_seconds": 604800,
                    "reset_after_seconds": 604800,
                    "reset_at": 1777964962,
                },
            },
        },
    ],
    "credits": {"has_credits": False, "balance": "0"},
    "spend_control": {"reached": False},
    "rate_limit_reached_type": None,
}


class TestFetch:
    """Tests for CodexProvider.fetch() — `_get_access_token` is patched out
    so we focus on the wham/usage parsing. The end-to-end two-step flow is
    covered separately by `TestFetchTwoStepFlow` below."""

    def _make_provider(self, mock_keyring):
        return CodexProvider(session_key="sk-1")

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_parses_canonical_response(self, mock_get, _mock_token, mock_keyring):
        p = self._make_provider(mock_keyring)
        mock_get.return_value = MagicMock(status_code=200, json=lambda: WHAM_USAGE_FIXTURE)
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()

        assert len(metrics) == 3

        assert metrics[0].label == "5-hour"
        assert metrics[0].utilization == 1
        assert metrics[0].is_primary is True
        assert metrics[0].resets_at == "2026-04-28T11:39:05+00:00"  # 1777376345 → ISO
        # Sanity: parseable by datetime.fromisoformat (what app.time_remaining uses)
        from datetime import datetime
        datetime.fromisoformat(metrics[0].resets_at)

        assert metrics[1].label == "7-day"
        assert metrics[1].utilization == 0
        assert metrics[1].is_primary is False

        assert metrics[2].label == "7-day GPT-5.3-Codex-Spark"
        assert metrics[2].utilization == 0
        assert metrics[2].is_primary is False

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_sends_bearer_authorization(self, mock_get, _mock_token, mock_keyring):
        p = self._make_provider(mock_keyring)
        mock_get.return_value = MagicMock(status_code=200, json=lambda: WHAM_USAGE_FIXTURE)
        mock_get.return_value.raise_for_status = MagicMock()

        p.fetch()

        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer bearer-xyz"
        # No cookies on the wham/usage call — only the bearer token authorises it
        assert "cookies" not in kwargs or not kwargs["cookies"]

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_handles_empty_additional_rate_limits(self, mock_get, _mock_token, mock_keyring):
        p = self._make_provider(mock_keyring)
        data = {**WHAM_USAGE_FIXTURE, "additional_rate_limits": []}
        mock_get.return_value = MagicMock(status_code=200, json=lambda: data)
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()
        assert len(metrics) == 2  # 5h + 7d only

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_handles_null_additional_rate_limits(self, mock_get, _mock_token, mock_keyring):
        p = self._make_provider(mock_keyring)
        data = {**WHAM_USAGE_FIXTURE, "additional_rate_limits": None}
        mock_get.return_value = MagicMock(status_code=200, json=lambda: data)
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()
        assert len(metrics) == 2

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_handles_null_used_percent(self, mock_get, _mock_token, mock_keyring):
        """Mirror the historical Claude bug — None utilization must coerce to 0."""
        p = self._make_provider(mock_keyring)
        data = {
            **WHAM_USAGE_FIXTURE,
            "rate_limit": {
                "primary_window": {"used_percent": None, "reset_at": 1777376345},
                "secondary_window": {"used_percent": None, "reset_at": 1777963145},
            },
            "additional_rate_limits": [],
        }
        mock_get.return_value = MagicMock(status_code=200, json=lambda: data)
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()
        assert metrics[0].utilization == 0
        assert metrics[1].utilization == 0

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_surfaces_code_review_rate_limit_when_present(self, mock_get, _mock_token, mock_keyring):
        p = self._make_provider(mock_keyring)
        data = {
            **WHAM_USAGE_FIXTURE,
            "code_review_rate_limit": {
                "primary_window": {"used_percent": 5, "reset_at": 1777378000},
                "secondary_window": {"used_percent": 12, "reset_at": 1777964000},
            },
            "additional_rate_limits": [],
        }
        mock_get.return_value = MagicMock(status_code=200, json=lambda: data)
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()
        labels = [m.label for m in metrics]
        assert "Code review 5-hour" in labels
        assert "Code review 7-day" in labels

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_wham_401_raises(self, mock_get, _mock_token, mock_keyring):
        from requests.exceptions import HTTPError

        p = self._make_provider(mock_keyring)
        resp = MagicMock(status_code=401)
        resp.raise_for_status.side_effect = HTTPError("401 Unauthorized")
        mock_get.return_value = resp

        with pytest.raises(HTTPError):
            p.fetch()

    def test_session_401_propagates(self, mock_keyring):
        """If the session exchange fails (cookie expired), fetch surfaces it."""
        from requests.exceptions import HTTPError
        p = self._make_provider(mock_keyring)
        with patch("providers.codex._get_access_token", side_effect=HTTPError("401")):
            with pytest.raises(HTTPError):
                p.fetch()


class TestFetchTwoStepFlow:
    """End-to-end test that both endpoints are called in the right order
    with the right credentials, no patching of `_get_access_token`."""

    @patch("providers.codex.requests.get")
    def test_full_flow_session_then_wham(self, mock_get, mock_keyring):
        from requests.exceptions import HTTPError

        def side_effect(url, **kwargs):
            if "api/auth/session" in url:
                resp = MagicMock(status_code=200)
                resp.json.return_value = {"accessToken": "bearer-from-session"}
                resp.raise_for_status = MagicMock()
                # Capture the cookie sent to session endpoint
                side_effect.session_cookies = kwargs.get("cookies")
                return resp
            if "wham/usage" in url:
                resp = MagicMock(status_code=200)
                resp.json.return_value = WHAM_USAGE_FIXTURE
                resp.raise_for_status = MagicMock()
                # Capture the auth header sent to wham
                side_effect.wham_auth = kwargs["headers"].get("Authorization")
                return resp
            raise ValueError(f"Unexpected URL: {url}")
        side_effect.session_cookies = None
        side_effect.wham_auth = None
        mock_get.side_effect = side_effect

        p = CodexProvider(session_key="sk-1")
        metrics = p.fetch()

        # Both endpoints were called
        assert mock_get.call_count == 2
        # Session endpoint got the cookie
        assert side_effect.session_cookies == {"__Secure-next-auth.session-token": "sk-1"}
        # wham/usage got the bearer token from the session response
        assert side_effect.wham_auth == "Bearer bearer-from-session"
        # Response was parsed
        assert len(metrics) == 3
```

- [ ] **Step 2: Run the failing tests**

```bash
pytest tests/test_codex_provider.py::TestGetAccessToken tests/test_codex_provider.py::TestFetch tests/test_codex_provider.py::TestFetchTwoStepFlow -v
```

Expected: `TestGetAccessToken` tests fail with `ImportError` (helper doesn't exist yet). `TestFetch` and `TestFetchTwoStepFlow` tests fail with `NotImplementedError` from the stub or `AttributeError` on the patched helper.

- [ ] **Step 3: Implement `_get_access_token()` and `fetch()`**

Edit `providers/codex.py`. Add the helper just above the `CodexProvider` class:

```python
def _get_access_token(session_key: str) -> str:
    """Exchange the NextAuth session cookie for a short-lived Bearer token.

    chatgpt.com's /backend-api/* endpoints require Bearer auth; the session
    cookie alone returns 401. This helper performs the standard NextAuth
    session exchange.
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
```

Then replace the `fetch` method on `CodexProvider` with:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_codex_provider.py::TestGetAccessToken tests/test_codex_provider.py::TestFetch tests/test_codex_provider.py::TestFetchTwoStepFlow -v
```

Expected: all PASS.

- [ ] **Step 5: Run the full suite**

```bash
pytest tests/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add providers/codex.py tests/test_codex_provider.py
git commit -m "Implement CodexProvider.fetch with NextAuth bearer-token exchange"
```

---

## Task 5: Implement `auto_setup()` and `refresh_cookie()`

**Files:**
- Modify: `providers/codex.py` (replace the two stubs)
- Modify: `tests/test_codex_provider.py` (append `TestAutoSetup`, `TestRefreshCookie`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_codex_provider.py`:

```python
# ── auto_setup ────────────────────────────────────────────────────────────────


class TestAutoSetup:
    @patch("providers.codex.extract_session_key")
    def test_success(self, mock_extract, mock_keyring):
        mock_extract.return_value = "sk-extracted"
        p = CodexProvider(browser="Brave")

        result = p.auto_setup()

        assert "Codex" in result or "Connected" in result
        assert p._session_key == "sk-extracted"
        # Saved to Keychain via the property setter
        assert mock_keyring[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] == "sk-extracted"

    @patch("providers.codex.extract_session_key")
    def test_no_cookie_raises(self, mock_extract, mock_keyring):
        mock_extract.return_value = None
        p = CodexProvider(browser="Brave")
        with pytest.raises(RuntimeError, match="Could not find"):
            p.auto_setup()


# ── refresh_cookie ────────────────────────────────────────────────────────────


class TestRefreshCookie:
    @patch("providers.codex.extract_session_key")
    def test_success(self, mock_extract, mock_keyring):
        mock_extract.return_value = "fresh-key"
        p = CodexProvider(browser="Chrome")
        assert p.refresh_cookie() is True
        assert p._session_key == "fresh-key"

    @patch("providers.codex.extract_session_key")
    def test_returns_false_on_none(self, mock_extract, mock_keyring):
        mock_extract.return_value = None
        p = CodexProvider(browser="Chrome")
        assert p.refresh_cookie() is False

    @patch("providers.codex.extract_session_key")
    def test_returns_false_on_exception(self, mock_extract, mock_keyring):
        mock_extract.side_effect = Exception("Keychain denied")
        p = CodexProvider(browser="Chrome")
        assert p.refresh_cookie() is False
```

- [ ] **Step 2: Run the failing tests**

```bash
pytest tests/test_codex_provider.py::TestAutoSetup tests/test_codex_provider.py::TestRefreshCookie -v
```

Expected: all FAIL — stubs raise NotImplementedError or return False unconditionally.

- [ ] **Step 3: Implement `auto_setup()` and `refresh_cookie()`**

Edit `providers/codex.py`. Replace the two stubs on `CodexProvider` with:

```python
    def auto_setup(self) -> str:
        """Extract the chatgpt.com session cookie and save it.

        Returns a human-readable status message. Raises on failure.
        Unlike Claude there is no org-discovery step — Codex rate limits
        are user-level.
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_codex_provider.py::TestAutoSetup tests/test_codex_provider.py::TestRefreshCookie -v
```

Expected: all PASS.

- [ ] **Step 5: Run the full suite**

```bash
pytest tests/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add providers/codex.py tests/test_codex_provider.py
git commit -m "Implement CodexProvider.auto_setup and refresh_cookie"
```

---

## Task 6: Implement `get_config_fields()`

**Files:**
- Modify: `providers/codex.py` (replace the `get_config_fields` stub)
- Modify: `tests/test_codex_provider.py` (append `TestGetConfigFields`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codex_provider.py`:

```python
# ── get_config_fields ─────────────────────────────────────────────────────────


class TestGetConfigFields:
    def test_returns_session_key_field_only(self):
        p = CodexProvider()
        fields = p.get_config_fields()
        # Codex has no org id, so only one field
        assert len(fields) == 1
        f = fields[0]
        assert f["key"] == "session_key"
        assert f["secure"] is True
        assert "label" in f
        assert "message" in f
```

- [ ] **Step 2: Run the failing test**

```bash
pytest tests/test_codex_provider.py::TestGetConfigFields -v
```

Expected: FAIL with NotImplementedError.

- [ ] **Step 3: Implement `get_config_fields()`**

Edit `providers/codex.py`. Replace the `get_config_fields` stub with:

```python
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
                    f"4. Copy the '{SESSION_COOKIE_NAME}' value\n\n"
                    "This will be stored in your macOS Keychain."
                ),
                "secure": True,
                "default": "",
            },
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_codex_provider.py::TestGetConfigFields -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

```bash
pytest tests/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add providers/codex.py tests/test_codex_provider.py
git commit -m "Implement CodexProvider.get_config_fields"
```

---

## Task 7: Wire `CodexProvider` into `app.py`

**Files:**
- Modify: `app.py` — three locations:
  - Imports + provider registration (`app.py:21` and `app.py:104-106`)
  - Configure submenu (`app.py:306-323`)
  - 401 cookie-refresh branch (`app.py:343-356`)
  - `_run_auto_setup` parameterisation (`app.py:198-245`)
- Modify: `tests/test_app.py` — extend the existing tests (none of the existing test bodies change shape)

- [ ] **Step 1: Add the import and register the provider**

Edit `app.py`. Replace the line:

```python
from providers.claude import ClaudeProvider, SUPPORTED_BROWSERS
```

with:

```python
from providers.claude import ClaudeProvider, SUPPORTED_BROWSERS
from providers.codex import CodexProvider
```

Then in `UsageTrackerApp.__init__`, replace:

```python
        # ── Providers ─────────────────────────────────────────────────────
        self.providers: list[tuple[BaseProvider, str]] = [
            (ClaudeProvider(), "claude"),
        ]
```

with:

```python
        # ── Providers ─────────────────────────────────────────────────────
        self.providers: list[tuple[BaseProvider, str]] = [
            (ClaudeProvider(), "claude"),
            (CodexProvider(), "codex"),
        ]
```

- [ ] **Step 2: Replace the Configure-submenu `isinstance` check with the capability flag**

Edit `app.py`. Find `_build_menu` (around line 287). Replace this block:

```python
        configure_menu = rumps.MenuItem("Configure")
        for provider, _key in self.providers:
            provider_menu = rumps.MenuItem(provider.name)
            if isinstance(provider, ClaudeProvider):
                provider_menu["Auto Setup"] = rumps.MenuItem(
                    "Auto Setup",
                    callback=lambda _, p=provider: self._run_auto_setup(),
                )
                provider_menu["Refresh Cookie"] = rumps.MenuItem(
                    "Refresh Cookie",
                    callback=lambda _, p=provider: self._on_refresh_cookie(p),
                )
            provider_menu["Manual Setup"] = rumps.MenuItem(
                "Manual Setup",
                callback=lambda _, p=provider: self._on_configure_manual(p),
            )
            configure_menu[provider.name] = provider_menu
        all_items.append(configure_menu)
```

with:

```python
        configure_menu = rumps.MenuItem("Configure")
        for provider, _key in self.providers:
            provider_menu = rumps.MenuItem(provider.name)
            if provider.supports_browser_auth:
                provider_menu["Auto Setup"] = rumps.MenuItem(
                    "Auto Setup",
                    callback=lambda _, p=provider: self._run_auto_setup(p),
                )
                provider_menu["Refresh Cookie"] = rumps.MenuItem(
                    "Refresh Cookie",
                    callback=lambda _, p=provider: self._on_refresh_cookie(p),
                )
            provider_menu["Manual Setup"] = rumps.MenuItem(
                "Manual Setup",
                callback=lambda _, p=provider: self._on_configure_manual(p),
            )
            configure_menu[provider.name] = provider_menu
        all_items.append(configure_menu)
```

The two changes: `isinstance(provider, ClaudeProvider)` → `provider.supports_browser_auth`, and `self._run_auto_setup()` → `self._run_auto_setup(p)`.

- [ ] **Step 3: Replace the 401 cookie-refresh `isinstance` check with the capability flag**

Edit `app.py`. Find `_refresh_all` (around line 334). Replace this block:

```python
            # Auto-refresh cookie on 401 (once per timer cycle)
            if (
                status.error
                and "401" in status.error
                and isinstance(provider, ClaudeProvider)
                and not self._cookie_refreshed_this_cycle
            ):
                self._cookie_refreshed_this_cycle = True
                if provider.refresh_cookie():
                    # Retry with new cookie
                    config = load_config()
                    config[key] = provider.to_dict()
                    save_config(config)
                    status = self._fetch_provider(provider)
```

with:

```python
            # Auto-refresh cookie on 401 (once per timer cycle)
            if (
                status.error
                and "401" in status.error
                and provider.supports_browser_auth
                and not self._cookie_refreshed_this_cycle
            ):
                self._cookie_refreshed_this_cycle = True
                if provider.refresh_cookie():
                    # Retry with new cookie
                    config = load_config()
                    config[key] = provider.to_dict()
                    save_config(config)
                    status = self._fetch_provider(provider)
```

- [ ] **Step 4: Parameterise `_run_auto_setup` to accept a provider**

Edit `app.py`. Find `_run_auto_setup` (around line 198). Replace the entire method:

```python
    def _run_auto_setup(self) -> None:
        """Extract cookie from browser and auto-discover org."""
        browser = self._pick_browser()
        if not browser:
            return

        # Find the Claude provider
        claude_provider: ClaudeProvider | None = None
        provider_key: str = ""
        for p, k in self.providers:
            if isinstance(p, ClaudeProvider):
                claude_provider = p
                provider_key = k
                break

        if not claude_provider:
            return

        claude_provider.browser = browser
        self.title = "Usage ..."

        try:
            status_msg = claude_provider.auto_setup()
        except Exception as e:
            rumps.alert(
                title="Setup Failed",
                message=(
                    f"{e}\n\n"
                    "You can try again from the menu:\n"
                    "Configure → Claude → Auto Setup"
                ),
                ok="OK",
            )
            self.title = "Usage ⚙️"
            return

        # Save config
        config = load_config()
        config[provider_key] = claude_provider.to_dict()
        config["refresh_interval"] = self.refresh_interval
        save_config(config)

        # Start polling
        if not self.timer.is_alive:
            self.timer.start()

        self._refresh_all()
        rumps.notification("Usage Tracker", "Setup Complete", status_msg)
```

with:

```python
    def _run_auto_setup(self, provider: BaseProvider | None = None) -> None:
        """Extract cookie from browser and run the provider's auto setup.

        If `provider` is None, defaults to the first browser-auth provider
        (used by the first-launch onboarding flow).
        """
        if provider is None:
            for p, _k in self.providers:
                if p.supports_browser_auth:
                    provider = p
                    break
            if provider is None:
                return

        browser = self._pick_browser()
        if not browser:
            return

        provider_key = next(
            (k for p, k in self.providers if p is provider), ""
        )
        if not provider_key:
            return

        provider.browser = browser
        self.title = "Usage ..."

        try:
            status_msg = provider.auto_setup()
        except Exception as e:
            rumps.alert(
                title="Setup Failed",
                message=(
                    f"{e}\n\n"
                    "You can try again from the menu:\n"
                    f"Configure → {provider.name} → Auto Setup"
                ),
                ok="OK",
            )
            self.title = "Usage ⚙️"
            return

        config = load_config()
        config[provider_key] = provider.to_dict()
        config["refresh_interval"] = self.refresh_interval
        save_config(config)

        if not self.timer.is_alive:
            self.timer.start()

        self._refresh_all()
        rumps.notification("Usage Tracker", "Setup Complete", status_msg)
```

- [ ] **Step 5: Run the existing test suite**

```bash
pytest tests/ -v
```

Expected: all green. None of the existing tests target `_build_menu` or `_run_auto_setup` directly — they test isolated helpers.

- [ ] **Step 6: Add a small wiring test**

Append to `tests/test_app.py`:

```python
class TestProviderRegistration:
    """Smoke test: both Claude and Codex are registered, config keys distinct."""

    def test_both_providers_registered(self, mock_keyring, config_dir):
        from app import UsageTrackerApp
        from providers.claude import ClaudeProvider
        from providers.codex import CodexProvider

        # Bypass __init__ to avoid the rumps.App side effects.
        app = object.__new__(UsageTrackerApp)
        # Re-create just the provider list construction.
        app.providers = [
            (ClaudeProvider(), "claude"),
            (CodexProvider(), "codex"),
        ]

        keys = [k for _p, k in app.providers]
        assert "claude" in keys
        assert "codex" in keys
        # Each gets its own config bucket
        assert len(set(keys)) == len(keys)
```

- [ ] **Step 7: Run the test**

```bash
pytest tests/test_app.py::TestProviderRegistration -v
```

Expected: PASS.

- [ ] **Step 8: Run the full suite**

```bash
pytest tests/ -v
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Wire CodexProvider into app.py via supports_browser_auth flag"
```

---

## Task 8: Manual end-to-end verification (running app)

**Why:** Tests use mocked HTTP and Keychain. This task confirms the provider works against the real chatgpt.com endpoint with real Keychain access.

**Files:**
- No code changes unless something breaks.

- [ ] **Step 1: Run the app from source**

```bash
cd /Users/daudir/Projects/cc-usage-tracker
source .venv/bin/activate
python app.py
```

Expected: a menu bar item appears showing `CC <pct>%` (Claude already configured) or `Usage ⚙️` (nothing configured yet).

- [ ] **Step 2: Trigger Codex Auto Setup**

In the menu: Configure → Codex → Auto Setup. Pick the browser you're logged into chatgpt.com in. macOS will prompt for Keychain access — allow it.

Expected: notification "Setup Complete — Connected to Codex". Menu bar title becomes `CC <pct>% · CX <pct>%`. Dropdown shows the Codex section with 5-hour, 7-day, and 7-day GPT-5.3-Codex-Spark rows.

- [ ] **Step 3: Open the dropdown and verify each metric**

For each Codex row:
- Label is human-readable
- Percentage is plausible (matches what you see on chatgpt.com/codex/cloud/settings/analytics#usage)
- "resets in …" is a sensible duration

If the percentage is way off (e.g. 0.01 when it should be 1, or 100 when it should be 1), the `used_percent` scale assumption (0–100) is wrong. Fix in `providers/codex.py` by multiplying by 100, then re-run pytest and the app.

- [ ] **Step 4: Verify `~/.config/cc-usage-tracker/config.json`**

```bash
cat ~/.config/cc-usage-tracker/config.json
```

Expected: contains both `claude` and `codex` keys; the `codex` entry has only `browser` (no session_key).

- [ ] **Step 5: Verify the cookie is in Keychain**

```bash
security find-generic-password -s cc-usage-tracker -a codex-session-key -g 2>&1 | grep -E "(service|account)"
```

Expected: prints lines containing `cc-usage-tracker` and `codex-session-key`. (The actual cookie value is in the output but you don't need to copy it.)

- [ ] **Step 6: Quit the app**

In the menu: Quit.

- [ ] **Step 7: No commit**

If everything worked, no code changes. If anything broke, fix and commit per the failure mode.

---

## Task 9: Build verification (.app bundle)

**Files:**
- No code changes.

- [ ] **Step 1: Build the .app bundle**

```bash
cd /Users/daudir/Projects/cc-usage-tracker
source .venv/bin/activate
./build.sh
```

Expected: `dist/CC Usage Tracker.app` is rebuilt. py2app should pick up `providers/codex.py` automatically (it's imported by `app.py`).

- [ ] **Step 2: Launch the bundled app**

```bash
open "dist/CC Usage Tracker.app"
```

Expected: menu bar item appears. Both providers (`CC … · CX …`) reflect current usage. Quit any source-run instance first if it's still running.

- [ ] **Step 3: Quit and verify clean shutdown**

Menu → Quit.

- [ ] **Step 4: No commit**

If the build worked, nothing to commit. If py2app missed `pycookiecheat`'s C extensions for the new provider import path (unlikely — same module), add the package to `setup.py`'s `packages` list and commit that change.

---

## Task 10: Push branch and open PR

**Files:**
- No code changes.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/codex-provider
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "Add Codex usage provider" --body "$(cat <<'EOF'
## Summary

- Adds `CodexProvider` polling `chatgpt.com/backend-api/wham/usage`
- Menu bar title now shows both providers, e.g. `CC 30% · CX 1%`
- Dropdown surfaces 5-hour primary window, 7-day secondary window, and per-model `additional_rate_limits`
- Reuses the cookie-from-browser → Keychain → polling flow from `ClaudeProvider`
- Adds `BaseProvider.supports_browser_auth` capability flag so `app.py` no longer hard-codes `isinstance(provider, ClaudeProvider)`

Spec: `docs/superpowers/specs/2026-04-28-codex-usage-provider-design.md`
Plan: `docs/superpowers/plans/2026-04-28-codex-usage-provider.md`

## Test plan

- [ ] `pytest tests/ -v` passes
- [ ] `python app.py` from source: Configure → Codex → Auto Setup connects and shows usage
- [ ] `./build.sh` then `open "dist/CC Usage Tracker.app"` runs the bundled app with both providers

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Note the PR URL** so the user can review.

---

## Self-review checklist (already run)

- **Spec coverage:** Every section of the spec maps to a task — endpoint+response mapping (Task 4), auth+secrets (Tasks 0/2/5), Configure UX (Tasks 5/6/7), config-on-disk shape (Task 7), capability flag refactor (Task 1), tests (Tasks 2–7), risks (Task 0 preflight + Task 8 manual verify).
- **No placeholders:** Every step has either complete code, an exact command with expected output, or a manual verification step.
- **Type consistency:** `KEYCHAIN_ACCOUNT`, `SESSION_COOKIE_NAME`, `SUPPORTED_BROWSERS`, `extract_session_key`, `_unix_to_iso` named identically across tasks. Provider class is `CodexProvider` everywhere. Method signatures (`auto_setup() -> str`, `refresh_cookie() -> bool`, `fetch() -> list[UsageMetric]`) match `BaseProvider`.
- **TDD rhythm:** Each implementation task has a failing-test step before code, a passing-test step after, and a commit at the end.
- **Frequent commits:** 8 commits across the work (one per task that produces code).
