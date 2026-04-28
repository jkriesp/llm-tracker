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
