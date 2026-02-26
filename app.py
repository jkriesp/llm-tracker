#!/usr/bin/env python3
"""Claude Code Usage Tracker - macOS Menu Bar App.

Displays API usage stats from Claude (and other providers) in the macOS menu bar.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import rumps

from AppKit import NSAlert, NSPopUpButton
from Foundation import NSMakeRect

import login_item
from providers import BaseProvider, ProviderStatus
from providers.claude import ClaudeProvider, SUPPORTED_BROWSERS
from views import ErrorView, HeaderView, MetricView, MENU_WIDTH, METRIC_HEIGHT

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".config" / "cc-usage-tracker"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_REFRESH = 300  # seconds


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


# ── Helpers ───────────────────────────────────────────────────────────────────


def time_remaining(iso_timestamp: str | None) -> str:
    if not iso_timestamp:
        return "N/A"
    target = datetime.fromisoformat(iso_timestamp)
    now = datetime.now(timezone.utc)
    delta = target - now
    if delta.total_seconds() <= 0:
        return "now"
    total = int(delta.total_seconds())
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}m")
    return " ".join(parts) or "<1m"


def indicator(pct: float) -> str:
    if pct >= 90:
        return "\U0001f534"
    if pct >= 70:
        return "\U0001f7e1"
    return ""


# ── App ───────────────────────────────────────────────────────────────────────


class UsageTrackerApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Usage: --", quit_button=None)

        config = load_config()
        self.refresh_interval: int = config.get("refresh_interval", DEFAULT_REFRESH)

        # ── Providers ─────────────────────────────────────────────────────
        self.providers: list[tuple[BaseProvider, str]] = [
            (ClaudeProvider(), "claude"),
        ]

        # Hydrate providers from saved config
        for provider, key in self.providers:
            provider_cfg = config.get(key, {})
            if provider_cfg:
                provider.apply_config(provider_cfg)

        # ── Build menu ────────────────────────────────────────────────────
        self.provider_sections: dict[str, list[rumps.MenuItem]] = {}
        self.metric_views: dict[str, list[MetricView]] = {}
        self.error_views: dict[str, ErrorView] = {}
        self.updated_item = rumps.MenuItem("")

        for provider, _key in self.providers:
            items = self._create_provider_menu_items(provider)
            self.provider_sections[provider.name] = items

        self._build_menu()

        # ── Start refresh timer ───────────────────────────────────────────
        self.timer = rumps.Timer(self._on_tick, self.refresh_interval)
        has_any_configured = any(p.is_configured() for p, _ in self.providers)
        if has_any_configured:
            self.timer.start()
            self._refresh_all()
        else:
            self.title = "Usage \u2699\ufe0f"
            # Trigger onboarding after the run loop starts
            rumps.Timer(self._trigger_onboarding, 1).start()

    # ── Onboarding ─────────────────────────────────────────────────────────

    def _trigger_onboarding(self, timer: rumps.Timer) -> None:
        """Fires once after app launch to show the welcome dialog."""
        timer.stop()
        self._show_onboarding()

    def _show_onboarding(self) -> None:
        """Guide the user through automatic setup."""
        welcome = rumps.alert(
            title="Welcome to Usage Tracker",
            message=(
                "This app shows your Claude API usage in the menu bar.\n\n"
                "To get started, it needs your session cookie from your browser. "
                "Here's what will happen:\n\n"
                "\u2460  The app reads the 'sessionKey' cookie for claude.ai\n"
                "     from your browser's cookie store.\n\n"
                "\u2461  macOS will ask you to allow Keychain access\n"
                "     (this is how browsers protect stored cookies).\n\n"
                "\u2462  The cookie is stored securely in your macOS Keychain\n"
                "     \u2014 never saved in a plaintext file.\n\n"
                "\u2463  The cookie is used only to check your usage at\n"
                "     claude.ai \u2014 nothing else.\n\n"
                "Non-sensitive settings stored at:\n"
                f"  {CONFIG_FILE}\n\n"
                "You need to be logged into claude.ai in your browser."
            ),
            ok="Set Up Automatically",
            cancel="Manual Setup",
        )

        if welcome == 1:  # "Set Up Automatically"
            self._run_auto_setup()
        else:
            self._run_manual_setup()

    def _pick_browser(self) -> str | None:
        """Let the user choose which browser to extract cookies from."""
        browsers = list(SUPPORTED_BROWSERS.keys())

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Choose Browser")
        alert.setInformativeText_(
            "Which browser are you logged into claude.ai with?"
        )
        alert.addButtonWithTitle_("Continue")
        alert.addButtonWithTitle_("Cancel")

        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(0, 0, 200, 28), False
        )
        for name in browsers:
            popup.addItemWithTitle_(name)
        alert.setAccessoryView_(popup)

        if alert.runModal() != 1000:  # NSAlertFirstButtonReturn
            return None
        return browsers[popup.indexOfSelectedItem()]

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
                    "Configure \u2192 Claude \u2192 Auto Setup"
                ),
                ok="OK",
            )
            self.title = "Usage \u2699\ufe0f"
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

    def _run_manual_setup(self) -> None:
        """Fall back to the manual field-by-field configuration."""
        for provider, _key in self.providers:
            self._on_configure_manual(provider)

    # ── Menu construction ─────────────────────────────────────────────────

    def _create_provider_menu_items(self, provider: BaseProvider) -> list[rumps.MenuItem]:
        # Header with custom view
        header = rumps.MenuItem("")
        header.set_callback(None)
        header_view = HeaderView.alloc().initWithTitle_(provider.name)
        header._menuitem.setView_(header_view)
        items = [header]

        # Error row (hidden by default)
        err_item = rumps.MenuItem("")
        err_item.set_callback(None)
        err_view = ErrorView.alloc().initWithFrame_(NSMakeRect(0, 0, MENU_WIDTH, 28))
        err_item._menuitem.setView_(err_view)
        err_item._menuitem.setHidden_(True)
        self.error_views[provider.name] = err_view
        items.append(err_item)

        # Metric rows with custom views
        views: list[MetricView] = []
        for _ in range(6):
            item = rumps.MenuItem("")
            item.set_callback(None)
            view = MetricView.alloc().initWithFrame_(
                NSMakeRect(0, 0, MENU_WIDTH, METRIC_HEIGHT)
            )
            item._menuitem.setView_(view)
            item._menuitem.setHidden_(True)
            items.append(item)
            views.append(view)
        self.metric_views[provider.name] = views

        return items

    def _build_menu(self) -> None:
        all_items: list[rumps.MenuItem | None] = []

        for provider, _key in self.providers:
            section = self.provider_sections[provider.name]
            all_items.extend(section)
            all_items.append(None)  # separator

        all_items.append(self.updated_item)
        all_items.append(rumps.MenuItem("Refresh", callback=self._on_refresh))

        self.login_item = rumps.MenuItem(
            "Launch at Login", callback=self._on_toggle_login
        )
        self.login_item.state = login_item.is_enabled()
        all_items.append(self.login_item)
        all_items.append(None)

        # Configure sub-menu per provider with auto + manual options
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

        all_items.append(rumps.MenuItem("Quit", callback=self._on_quit))
        self.menu = all_items

    # ── Data refresh ──────────────────────────────────────────────────────

    def _on_tick(self, _: rumps.Timer) -> None:
        self._refresh_all()

    def _refresh_all(self) -> None:
        title_parts: list[str] = []

        for provider, key in self.providers:
            if not provider.is_configured():
                continue

            status = self._fetch_provider(provider)

            # Auto-refresh cookie on 401
            if (
                status.error
                and "401" in status.error
                and isinstance(provider, ClaudeProvider)
            ):
                if provider.refresh_cookie():
                    # Retry with new cookie
                    config = load_config()
                    config[key] = provider.to_dict()
                    save_config(config)
                    status = self._fetch_provider(provider)

            self._update_provider_section(provider.name, status)

            for m in status.metrics:
                if m.is_primary:
                    icon = indicator(m.utilization)
                    title_parts.append(f"{provider.short_name} {icon}{m.utilization:.0f}%")

        if title_parts:
            self.title = " \u00b7 ".join(title_parts)
        else:
            self.title = "Usage \u2699\ufe0f"

        self.updated_item.title = f"Updated: {datetime.now().strftime('%H:%M:%S')}"

    def _fetch_provider(self, provider: BaseProvider) -> ProviderStatus:
        try:
            metrics = provider.fetch()
            return ProviderStatus(provider_name=provider.name, metrics=metrics)
        except Exception as e:
            err = str(e)[:80]
            return ProviderStatus(provider_name=provider.name, error=err)

    def _update_provider_section(self, name: str, status: ProviderStatus) -> None:
        items = self.provider_sections[name]
        views = self.metric_views[name]
        err_view = self.error_views[name]

        if status.error:
            # Show error, hide metrics
            err_view.update(status.error)
            items[1]._menuitem.setHidden_(False)
            for i, view in enumerate(views):
                view.clear()
                items[i + 2]._menuitem.setHidden_(True)
            return

        # Hide error row
        err_view.clear()
        items[1]._menuitem.setHidden_(True)

        # Update metric views
        for i, view in enumerate(views):
            if i < len(status.metrics):
                m = status.metrics[i]
                resets = time_remaining(m.resets_at)
                view.update(m.label, m.utilization, f"resets in {resets}")
                items[i + 2]._menuitem.setHidden_(False)
            else:
                view.clear()
                items[i + 2]._menuitem.setHidden_(True)

    # ── Callbacks ─────────────────────────────────────────────────────────

    def _on_refresh(self, _: rumps.MenuItem) -> None:
        self.title = "Usage ..."
        self._refresh_all()

    def _on_toggle_login(self, sender: rumps.MenuItem) -> None:
        if login_item.is_enabled():
            login_item.disable()
            sender.state = False
        else:
            if login_item.enable():
                sender.state = True
            else:
                rumps.alert(
                    title="Not Running as .app",
                    message=(
                        "Launch at Login requires a bundled .app.\n\n"
                        "Build it first:\n"
                        "  ./build.sh\n\n"
                        "Then open:\n"
                        "  dist/CC Usage Tracker.app"
                    ),
                    ok="OK",
                )

    def _on_refresh_cookie(self, provider: ClaudeProvider) -> None:
        """Re-extract the cookie from the browser without full re-setup."""
        self.title = "Usage ..."
        if provider.refresh_cookie():
            config = load_config()
            provider_key = next(k for p, k in self.providers if p is provider)
            config[provider_key] = provider.to_dict()
            save_config(config)
            self._refresh_all()
            rumps.notification("Usage Tracker", "Cookie Refreshed", "Session key updated from browser.")
        else:
            self._refresh_all()
            rumps.notification("Usage Tracker", "Cookie Refresh Failed", "Could not read cookie. Try Auto Setup.")

    def _on_configure_manual(self, provider: BaseProvider) -> None:
        fields = provider.get_config_fields()
        values: dict[str, str] = {}

        for field in fields:
            window = rumps.Window(
                message=field["message"],
                title=f"Configure {provider.name} \u2014 {field['label']}",
                default_text=field.get("default", ""),
                ok="Next" if field != fields[-1] else "Save",
                cancel="Cancel",
            )
            response = window.run()
            if not response.clicked:
                return
            values[field["key"]] = response.text.strip()

        provider.apply_config(values)

        config = load_config()
        provider_key = next(k for p, k in self.providers if p is provider)
        config[provider_key] = provider.to_dict()
        config["refresh_interval"] = self.refresh_interval
        save_config(config)

        if not self.timer.is_alive:
            self.timer.start()

        self._refresh_all()
        rumps.notification("Usage Tracker", f"{provider.name} configured", "Fetching usage data...")

    def _on_quit(self, _: rumps.MenuItem) -> None:
        rumps.quit_application()


if __name__ == "__main__":
    UsageTrackerApp().run()
