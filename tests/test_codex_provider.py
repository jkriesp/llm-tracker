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
