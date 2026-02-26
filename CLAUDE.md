# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
source .venv/bin/activate
python app.py
```

Setup: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`

No tests or linter are configured yet.

## Architecture

This is a macOS menu bar app (using `rumps`) that polls the claude.ai usage API and displays rate limit utilization with native AppKit custom views.

### Key design decisions

- **Provider pattern**: `providers/` defines a `BaseProvider` interface. `ClaudeProvider` is the first implementation. New services (OpenAI, etc.) are added by subclassing `BaseProvider` and registering in `app.py`'s `self.providers` list. The menu bar shows multiple providers side by side (`CC 30% · OAI 45%`).

- **Secret storage**: Session cookies are stored in macOS Keychain via `keyring`, never in the config JSON. The `session_key` property on `ClaudeProvider` transparently reads/writes Keychain. `to_dict()` intentionally excludes the session key — only `org_id` and `browser` go to `~/.config/cc-usage-tracker/config.json`.

- **Cookie extraction**: Uses `pycookiecheat` to read browser cookies (Brave/Chrome/Chromium/Firefox). On 401 errors, the app automatically re-extracts a fresh cookie from the browser and retries.

- **Custom NSViews via pyobjc**: `views.py` subclasses `NSView` to draw colored progress bars and styled text in the dropdown menu. Methods that would clash with NSView selectors (like `update`, `clear`) must use the `@objc.python_method` decorator.

- **Menu item visibility**: Unused metric slots and error rows are toggled with `item._menuitem.setHidden_(True/False)` on the underlying `NSMenuItem`, since `rumps` doesn't expose this.
