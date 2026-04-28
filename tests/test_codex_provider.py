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
        assert "h" in result or "m" in result


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
        _, kwargs = mock_get.call_args
        assert kwargs["cookies"][SESSION_COOKIE_NAME] == "sk-1"

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

    @patch("providers.codex.get_cookies")
    @patch("providers.codex.requests.get")
    def test_forwards_cloudflare_cookies_from_browser(self, mock_get, mock_get_cookies):
        """chatgpt.com is behind Cloudflare bot mitigation. Without cf_clearance
        and __cf_bm in the request, the session exchange returns 403."""
        from providers.codex import _get_access_token, SESSION_COOKIE_NAME

        mock_get_cookies.return_value = {
            SESSION_COOKIE_NAME: "stale-browser-value",
            "cf_clearance": "cf-clearance-token",
            "__cf_bm": "cf-bm-token",
            "_cfuvid": "cfuvid-token",
        }
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"accessToken": "bearer"}
        )
        mock_get.return_value.raise_for_status = MagicMock()

        _get_access_token("sk-keychain", browser="Brave")

        _, kwargs = mock_get.call_args
        sent = kwargs["cookies"]
        assert sent["cf_clearance"] == "cf-clearance-token"
        assert sent["__cf_bm"] == "cf-bm-token"
        assert sent["_cfuvid"] == "cfuvid-token"
        # The Keychain-cached session cookie wins over the browser-supplied one
        assert sent[SESSION_COOKIE_NAME] == "sk-keychain"

    @patch("providers.codex.get_cookies", side_effect=Exception("browser locked"))
    @patch("providers.codex.requests.get")
    def test_falls_back_to_session_only_when_browser_unavailable(self, mock_get, _mock_cookies):
        """If pycookiecheat fails (browser closed, keychain denied, etc.),
        fall back to sending the session cookie alone — no regression vs. today."""
        from providers.codex import _get_access_token, SESSION_COOKIE_NAME

        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"accessToken": "bearer"}
        )
        mock_get.return_value.raise_for_status = MagicMock()

        _get_access_token("sk-1", browser="Brave")

        _, kwargs = mock_get.call_args
        assert kwargs["cookies"] == {SESSION_COOKIE_NAME: "sk-1"}

    @patch("providers.codex.requests.get")
    def test_uses_realistic_chrome_user_agent(self, mock_get):
        """Cloudflare's cf_clearance is fingerprint-bound — a UA missing the
        Chrome/Safari version suffix can invalidate the clearance cookie."""
        from providers.codex import _get_access_token

        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"accessToken": "bearer"}
        )
        mock_get.return_value.raise_for_status = MagicMock()

        _get_access_token("sk-1")

        _, kwargs = mock_get.call_args
        ua = kwargs["headers"]["User-Agent"]
        assert "Chrome/" in ua
        assert "Safari/" in ua

    @patch("providers.codex.requests.get")
    def test_disables_redirect_following(self, mock_get):
        """dict-sourced cookies have no domain binding — they would be sent on
        any cross-origin redirect. Disable redirect following to prevent
        session cookie exfiltration if chatgpt.com ever 3xx'd to a third party."""
        from providers.codex import _get_access_token

        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"accessToken": "bearer"}
        )
        mock_get.return_value.raise_for_status = MagicMock()

        _get_access_token("sk-1")

        _, kwargs = mock_get.call_args
        assert kwargs.get("allow_redirects") is False


# ── fetch ─────────────────────────────────────────────────────────────────────


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
    """fetch() tests with `_get_access_token` patched out."""

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
        assert metrics[0].resets_at == "2026-04-28T11:39:05+00:00"
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
        assert "cookies" not in kwargs or not kwargs["cookies"]

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_wham_disables_redirect_following(self, mock_get, _mock_token, mock_keyring):
        """Bearer must not follow redirects — even Authorization-stripped, a
        redirect away from chatgpt.com is unexpected and worth surfacing."""
        p = self._make_provider(mock_keyring)
        mock_get.return_value = MagicMock(status_code=200, json=lambda: WHAM_USAGE_FIXTURE)
        mock_get.return_value.raise_for_status = MagicMock()

        p.fetch()

        _, kwargs = mock_get.call_args
        assert kwargs.get("allow_redirects") is False

    @patch("providers.codex._get_access_token", return_value="bearer-xyz")
    @patch("providers.codex.requests.get")
    def test_handles_empty_additional_rate_limits(self, mock_get, _mock_token, mock_keyring):
        p = self._make_provider(mock_keyring)
        data = {**WHAM_USAGE_FIXTURE, "additional_rate_limits": []}
        mock_get.return_value = MagicMock(status_code=200, json=lambda: data)
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()
        assert len(metrics) == 2

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
        p = CodexProvider(session_key="sk-1")
        with patch("providers.codex._get_access_token", side_effect=HTTPError("401")):
            with pytest.raises(HTTPError):
                p.fetch()


class TestFetchTwoStepFlow:
    """End-to-end test: both endpoints called in order with right credentials."""

    @patch("providers.codex.requests.get")
    def test_full_flow_session_then_wham(self, mock_get, mock_keyring):
        def side_effect(url, **kwargs):
            if "api/auth/session" in url:
                resp = MagicMock(status_code=200)
                resp.json.return_value = {"accessToken": "bearer-from-session"}
                resp.raise_for_status = MagicMock()
                side_effect.session_cookies = kwargs.get("cookies")
                return resp
            if "wham/usage" in url:
                resp = MagicMock(status_code=200)
                resp.json.return_value = WHAM_USAGE_FIXTURE
                resp.raise_for_status = MagicMock()
                side_effect.wham_auth = kwargs["headers"].get("Authorization")
                return resp
            raise ValueError(f"Unexpected URL: {url}")
        side_effect.session_cookies = None
        side_effect.wham_auth = None
        mock_get.side_effect = side_effect

        p = CodexProvider(session_key="sk-1")
        metrics = p.fetch()

        assert mock_get.call_count == 2
        assert side_effect.session_cookies == {"__Secure-next-auth.session-token": "sk-1"}
        assert side_effect.wham_auth == "Bearer bearer-from-session"
        assert len(metrics) == 3


# ── auto_setup ────────────────────────────────────────────────────────────────


class TestAutoSetup:
    @patch("providers.codex.extract_session_key")
    def test_success(self, mock_extract, mock_keyring):
        mock_extract.return_value = "sk-extracted"
        p = CodexProvider(browser="Brave")

        result = p.auto_setup()

        assert "Codex" in result or "Connected" in result
        assert p._session_key == "sk-extracted"
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


# ── get_config_fields ─────────────────────────────────────────────────────────


class TestGetConfigFields:
    def test_returns_session_key_field_only(self):
        p = CodexProvider()
        fields = p.get_config_fields()
        assert len(fields) == 1
        f = fields[0]
        assert f["key"] == "session_key"
        assert f["secure"] is True
        assert "label" in f
        assert "message" in f
