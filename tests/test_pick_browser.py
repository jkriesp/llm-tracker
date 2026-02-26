"""Tests for app.py._pick_browser() — verifies NSPopUpButton dropdown is used."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestPickBrowser:
    """Verify the browser picker uses an NSPopUpButton dropdown (not text input)."""

    def _make_app_instance(self):
        """Create a minimal UsageTrackerApp-like object with _pick_browser bound."""
        from app import UsageTrackerApp

        # We only need the method, not the full app init
        instance = object.__new__(UsageTrackerApp)
        return instance

    @patch("app.NSMakeRect", return_value=(0, 0, 200, 28))
    @patch("app.NSPopUpButton")
    @patch("app.NSAlert")
    def test_creates_popup_button(self, MockAlert, MockPopUp, _mock_rect):
        alert_instance = MagicMock()
        MockAlert.alloc.return_value.init.return_value = alert_instance
        alert_instance.runModal.return_value = 1000  # Continue

        popup_instance = MagicMock()
        popup_instance.indexOfSelectedItem.return_value = 0
        MockPopUp.alloc.return_value.initWithFrame_pullsDown_.return_value = popup_instance

        app = self._make_app_instance()
        result = app._pick_browser()

        # NSPopUpButton was created
        MockPopUp.alloc.return_value.initWithFrame_pullsDown_.assert_called_once()
        # It was set as the alert's accessory view
        alert_instance.setAccessoryView_.assert_called_once_with(popup_instance)
        assert result is not None

    @patch("app.NSMakeRect", return_value=(0, 0, 200, 28))
    @patch("app.NSPopUpButton")
    @patch("app.NSAlert")
    def test_returns_selected_browser(self, MockAlert, MockPopUp, _mock_rect):
        alert_instance = MagicMock()
        MockAlert.alloc.return_value.init.return_value = alert_instance
        alert_instance.runModal.return_value = 1000

        popup_instance = MagicMock()
        popup_instance.indexOfSelectedItem.return_value = 1  # Chrome (second item)
        MockPopUp.alloc.return_value.initWithFrame_pullsDown_.return_value = popup_instance

        app = self._make_app_instance()
        result = app._pick_browser()

        from providers.claude import SUPPORTED_BROWSERS

        browsers = list(SUPPORTED_BROWSERS.keys())
        assert result == browsers[1]

    @patch("app.NSMakeRect", return_value=(0, 0, 200, 28))
    @patch("app.NSPopUpButton")
    @patch("app.NSAlert")
    def test_cancel_returns_none(self, MockAlert, MockPopUp, _mock_rect):
        alert_instance = MagicMock()
        MockAlert.alloc.return_value.init.return_value = alert_instance
        alert_instance.runModal.return_value = 1001  # Cancel

        popup_instance = MagicMock()
        MockPopUp.alloc.return_value.initWithFrame_pullsDown_.return_value = popup_instance

        app = self._make_app_instance()
        result = app._pick_browser()

        assert result is None
