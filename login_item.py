"""Manage Launch at Login via a LaunchAgent plist."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

BUNDLE_ID = "com.cc-usage-tracker.app"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"


def _get_app_path() -> Path | None:
    """Find the .app bundle containing the running executable.

    Walks up from sys.executable looking for a directory ending in '.app'.
    Returns None when running from source (not bundled).
    """
    path = Path(sys.executable).resolve()
    for parent in path.parents:
        if parent.suffix == ".app":
            return parent
    return None


def is_enabled() -> bool:
    """Check whether the LaunchAgent plist exists."""
    return PLIST_PATH.exists()


def enable() -> bool:
    """Create the LaunchAgent plist and load it.

    Returns True on success, False if not running as a .app bundle.
    """
    app_path = _get_app_path()
    if app_path is None:
        return False

    plist = {
        "Label": BUNDLE_ID,
        "ProgramArguments": ["/usr/bin/open", str(app_path)],
        "RunAtLoad": True,
    }

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plistlib.dumps(plist))

    subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True,
    )
    return True


def disable() -> None:
    """Unload and remove the LaunchAgent plist."""
    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True,
        )
        PLIST_PATH.unlink(missing_ok=True)
