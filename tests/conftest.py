"""Shared fixtures for the test suite.

Mocks macOS-specific dependencies (AppKit, rumps, etc.) so tests run anywhere.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


# ── Mock macOS-only modules before any project imports ────────────────────────

def _install_mock_modules() -> None:
    """Install mock modules for AppKit, Foundation, rumps, and related deps."""
    mock_modules = [
        "AppKit",
        "Foundation",
        "objc",
        "rumps",
        "PyObjCTools",
        "PyObjCTools.Conversion",
    ]
    for name in mock_modules:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

    # rumps needs some concrete attributes
    rumps_mock = sys.modules["rumps"]
    rumps_mock.App = MagicMock
    rumps_mock.MenuItem = MagicMock
    rumps_mock.Timer = MagicMock
    rumps_mock.Window = MagicMock

    # Foundation needs NSMakeRect
    sys.modules["Foundation"].NSMakeRect = MagicMock(return_value=(0, 0, 200, 28))


_install_mock_modules()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_keyring(monkeypatch):
    """Patch keyring get/set/delete so tests never touch the real Keychain."""
    store: dict[tuple[str, str], str] = {}

    def _get(service, account):
        return store.get((service, account))

    def _set(service, account, value):
        store[(service, account)] = value

    def _delete(service, account):
        store.pop((service, account), None)

    import keyring as kr

    monkeypatch.setattr(kr, "get_password", _get)
    monkeypatch.setattr(kr, "set_password", _set)
    monkeypatch.setattr(kr, "delete_password", _delete)
    return store


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR / CONFIG_FILE to a temp directory."""
    import app as app_mod

    monkeypatch.setattr(app_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "CONFIG_FILE", tmp_path / "config.json")
    return tmp_path
