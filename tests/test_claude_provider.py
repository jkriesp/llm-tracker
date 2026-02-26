"""Tests for providers/claude.py — ClaudeProvider and module-level helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from providers.claude import (
    ClaudeProvider,
    KEYCHAIN_ACCOUNT,
    KEYCHAIN_SERVICE,
    discover_organizations,
    extract_session_key,
)


# ── ClaudeProvider init & properties ──────────────────────────────────────────


class TestClaudeProviderInit:
    def test_defaults(self):
        p = ClaudeProvider()
        assert p.org_id == ""
        assert p._session_key == ""
        assert p.browser == "Brave"
        assert p.name == "Claude"
        assert p.short_name == "CC"

    def test_custom_values(self):
        p = ClaudeProvider(org_id="org-1", session_key="sk-1", browser="Chrome")
        assert p.org_id == "org-1"
        assert p._session_key == "sk-1"
        assert p.browser == "Chrome"


class TestIsConfigured:
    def test_false_when_empty(self, mock_keyring):
        p = ClaudeProvider()
        assert p.is_configured() is False

    def test_false_when_only_org(self, mock_keyring):
        p = ClaudeProvider(org_id="org-1")
        assert p.is_configured() is False

    def test_true_when_both_set(self, mock_keyring):
        p = ClaudeProvider(org_id="org-1", session_key="sk-1")
        assert p.is_configured() is True


class TestSessionKeyProperty:
    def test_reads_from_keyring(self, mock_keyring):
        mock_keyring[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] = "from-keyring"
        p = ClaudeProvider(org_id="org-1")
        assert p.session_key == "from-keyring"

    def test_writes_to_keyring(self, mock_keyring):
        p = ClaudeProvider()
        p.session_key = "new-key"
        assert mock_keyring[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] == "new-key"

    def test_clear_deletes_from_keyring(self, mock_keyring):
        mock_keyring[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] = "old-key"
        p = ClaudeProvider()
        p.session_key = ""
        assert (KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) not in mock_keyring


# ── Serialization ─────────────────────────────────────────────────────────────


class TestToDict:
    def test_excludes_session_key(self):
        p = ClaudeProvider(org_id="org-1", session_key="secret", browser="Chrome")
        d = p.to_dict()
        assert d == {"org_id": "org-1", "browser": "Chrome"}
        assert "session_key" not in d


class TestFromDict:
    def test_roundtrip(self):
        original = ClaudeProvider(org_id="org-1", browser="Firefox")
        restored = ClaudeProvider.from_dict(original.to_dict())
        assert restored.org_id == "org-1"
        assert restored.browser == "Firefox"
        assert restored._session_key == ""  # not persisted

    def test_missing_keys_use_defaults(self):
        p = ClaudeProvider.from_dict({})
        assert p.org_id == ""
        assert p.browser == "Brave"


# ── apply_config ──────────────────────────────────────────────────────────────


class TestApplyConfig:
    def test_updates_fields(self, mock_keyring):
        p = ClaudeProvider()
        p.apply_config({"org_id": "new-org", "session_key": "new-sk", "browser": "Chrome"})
        assert p.org_id == "new-org"
        assert p.session_key == "new-sk"
        assert p.browser == "Chrome"

    def test_partial_update(self, mock_keyring):
        p = ClaudeProvider(org_id="keep-this", browser="Brave")
        p.apply_config({"org_id": "changed"})
        assert p.org_id == "changed"
        assert p.browser == "Brave"

    def test_empty_session_key_not_overwritten(self, mock_keyring):
        p = ClaudeProvider(session_key="keep")
        p.apply_config({"session_key": ""})
        assert p._session_key == "keep"


# ── get_config_fields ─────────────────────────────────────────────────────────


class TestGetConfigFields:
    def test_returns_expected_fields(self):
        p = ClaudeProvider()
        fields = p.get_config_fields()
        assert len(fields) == 2
        keys = [f["key"] for f in fields]
        assert "org_id" in keys
        assert "session_key" in keys
        for f in fields:
            assert "label" in f
            assert "message" in f
            assert "secure" in f


# ── extract_session_key ───────────────────────────────────────────────────────


class TestExtractSessionKey:
    @patch("providers.claude.get_cookies")
    def test_returns_session_key(self, mock_get_cookies):
        mock_get_cookies.return_value = {"sessionKey": "sk-abc"}
        result = extract_session_key("Brave")
        assert result == "sk-abc"

    @patch("providers.claude.get_cookies")
    def test_returns_none_when_missing(self, mock_get_cookies):
        mock_get_cookies.return_value = {}
        result = extract_session_key("Chrome")
        assert result is None

    def test_raises_for_unsupported_browser(self):
        with pytest.raises(ValueError, match="Unsupported browser"):
            extract_session_key("Safari")


# ── discover_organizations ────────────────────────────────────────────────────


class TestDiscoverOrganizations:
    @patch("providers.claude.requests.get")
    def test_success(self, mock_get):
        orgs = [{"uuid": "org-1", "name": "My Org"}]
        mock_get.return_value = MagicMock(status_code=200, json=lambda: orgs)
        mock_get.return_value.raise_for_status = MagicMock()
        result = discover_organizations("sk-test")
        assert result == orgs

    @patch("providers.claude.requests.get")
    def test_http_error(self, mock_get):
        from requests.exceptions import HTTPError

        mock_get.return_value.raise_for_status.side_effect = HTTPError("401")
        with pytest.raises(HTTPError):
            discover_organizations("bad-key")


# ── fetch ─────────────────────────────────────────────────────────────────────


class TestFetch:
    def _make_provider(self, mock_keyring):
        p = ClaudeProvider(org_id="org-1", session_key="sk-1")
        return p

    @patch("providers.claude.requests.get")
    def test_parses_usage_response(self, mock_get, mock_keyring):
        p = self._make_provider(mock_keyring)
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "five_hour": {"utilization": 30.0, "resets_at": "2026-03-01T00:00:00Z"},
                "seven_day": {"utilization": 10.0, "resets_at": None},
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()
        assert len(metrics) == 2
        assert metrics[0].label == "5-hour"
        assert metrics[0].utilization == 30.0
        assert metrics[0].is_primary is True
        assert metrics[1].label == "7-day"
        assert metrics[1].is_primary is False

    @patch("providers.claude.requests.get")
    def test_skips_unknown_keys(self, mock_get, mock_keyring):
        p = self._make_provider(mock_keyring)
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"unknown_metric": {"utilization": 50.0}},
        )
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()
        assert len(metrics) == 0

    @patch("providers.claude.requests.get")
    def test_401_raises(self, mock_get, mock_keyring):
        from requests.exceptions import HTTPError

        p = self._make_provider(mock_keyring)
        resp = MagicMock(status_code=401)
        resp.raise_for_status.side_effect = HTTPError("401 Unauthorized")
        mock_get.return_value = resp

        with pytest.raises(HTTPError):
            p.fetch()


# ── auto_setup ────────────────────────────────────────────────────────────────


class TestAutoSetup:
    @patch("providers.claude.discover_organizations")
    @patch("providers.claude.extract_session_key")
    def test_success(self, mock_extract, mock_discover, mock_keyring):
        mock_extract.return_value = "sk-extracted"
        mock_discover.return_value = [{"uuid": "org-1", "name": "My Org"}]

        p = ClaudeProvider(browser="Brave")
        result = p.auto_setup()

        assert "My Org" in result
        assert p.org_id == "org-1"
        assert p._session_key == "sk-extracted"

    @patch("providers.claude.extract_session_key")
    def test_no_cookie_raises(self, mock_extract, mock_keyring):
        mock_extract.return_value = None
        p = ClaudeProvider(browser="Brave")
        with pytest.raises(RuntimeError, match="Could not find"):
            p.auto_setup()

    @patch("providers.claude.discover_organizations")
    @patch("providers.claude.extract_session_key")
    def test_no_orgs_raises(self, mock_extract, mock_discover, mock_keyring):
        mock_extract.return_value = "sk-extracted"
        mock_discover.return_value = []
        p = ClaudeProvider(browser="Brave")
        with pytest.raises(RuntimeError, match="No organizations"):
            p.auto_setup()


# ── refresh_cookie ────────────────────────────────────────────────────────────


class TestRefreshCookie:
    @patch("providers.claude.extract_session_key")
    def test_success(self, mock_extract, mock_keyring):
        mock_extract.return_value = "fresh-key"
        p = ClaudeProvider(browser="Chrome")
        assert p.refresh_cookie() is True
        assert p._session_key == "fresh-key"

    @patch("providers.claude.extract_session_key")
    def test_returns_false_on_none(self, mock_extract, mock_keyring):
        mock_extract.return_value = None
        p = ClaudeProvider(browser="Chrome")
        assert p.refresh_cookie() is False

    @patch("providers.claude.extract_session_key")
    def test_returns_false_on_exception(self, mock_extract, mock_keyring):
        mock_extract.side_effect = Exception("Keychain denied")
        p = ClaudeProvider(browser="Chrome")
        assert p.refresh_cookie() is False
