"""Tests for login_item.py — LaunchAgent plist management."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import login_item
from login_item import BUNDLE_ID


# ── _get_app_path ─────────────────────────────────────────────────────────────


class TestGetAppPath:
    def test_inside_app_bundle(self, monkeypatch):
        fake_exec = "/Applications/CC Usage Tracker.app/Contents/MacOS/python"
        monkeypatch.setattr("sys.executable", fake_exec)
        # Patch Path.resolve to return itself (avoid filesystem resolution)
        monkeypatch.setattr(Path, "resolve", lambda self: self)

        result = login_item._get_app_path()
        assert result is not None
        assert result.suffix == ".app"
        assert "CC Usage Tracker" in result.name

    def test_outside_app_bundle(self, monkeypatch):
        fake_exec = "/usr/local/bin/python3"
        monkeypatch.setattr("sys.executable", fake_exec)
        monkeypatch.setattr(Path, "resolve", lambda self: self)

        result = login_item._get_app_path()
        assert result is None


# ── is_enabled ────────────────────────────────────────────────────────────────


class TestIsEnabled:
    def test_enabled_when_plist_exists(self, tmp_path, monkeypatch):
        plist_path = tmp_path / f"{BUNDLE_ID}.plist"
        plist_path.write_text("")
        monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)

        assert login_item.is_enabled() is True

    def test_disabled_when_plist_missing(self, tmp_path, monkeypatch):
        plist_path = tmp_path / f"{BUNDLE_ID}.plist"
        monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)

        assert login_item.is_enabled() is False


# ── enable ────────────────────────────────────────────────────────────────────


class TestEnable:
    @patch("login_item.subprocess.run")
    @patch("login_item._get_app_path")
    def test_creates_plist_and_loads(self, mock_app_path, mock_run, tmp_path, monkeypatch):
        app_path = Path("/Applications/CC Usage Tracker.app")
        mock_app_path.return_value = app_path
        plist_path = tmp_path / "LaunchAgents" / f"{BUNDLE_ID}.plist"
        monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)

        result = login_item.enable()

        assert result is True
        assert plist_path.exists()

        # Verify plist contents
        plist_data = plistlib.loads(plist_path.read_bytes())
        assert plist_data["Label"] == BUNDLE_ID
        assert plist_data["RunAtLoad"] is True
        assert str(app_path) in plist_data["ProgramArguments"]

        # Verify launchctl load was called
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "launchctl"
        assert args[1] == "load"

    @patch("login_item._get_app_path")
    def test_returns_false_when_not_bundled(self, mock_app_path):
        mock_app_path.return_value = None
        assert login_item.enable() is False


# ── disable ───────────────────────────────────────────────────────────────────


class TestDisable:
    @patch("login_item.subprocess.run")
    def test_unloads_and_removes_plist(self, mock_run, tmp_path, monkeypatch):
        plist_path = tmp_path / f"{BUNDLE_ID}.plist"
        plist_path.write_text("")
        monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)

        login_item.disable()

        assert not plist_path.exists()
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "launchctl"
        assert args[1] == "unload"

    @patch("login_item.subprocess.run")
    def test_noop_when_plist_missing(self, mock_run, tmp_path, monkeypatch):
        plist_path = tmp_path / f"{BUNDLE_ID}.plist"
        monkeypatch.setattr(login_item, "PLIST_PATH", plist_path)

        login_item.disable()  # Should not raise
        mock_run.assert_not_called()
