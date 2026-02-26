"""Tests for UsageTrackerApp core logic — _fetch_provider and menu title formatting."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from providers import ProviderStatus, UsageMetric


class TestFetchProvider:
    def _make_app_instance(self):
        """Create a bare UsageTrackerApp without running __init__."""
        from app import UsageTrackerApp

        return object.__new__(UsageTrackerApp)

    def test_returns_metrics_on_success(self):
        app = self._make_app_instance()
        provider = MagicMock()
        provider.name = "Claude"
        provider.fetch.return_value = [
            UsageMetric(label="5-hour", utilization=30.0, is_primary=True),
        ]

        status = app._fetch_provider(provider)

        assert status.provider_name == "Claude"
        assert len(status.metrics) == 1
        assert status.error is None

    def test_returns_error_on_exception(self):
        app = self._make_app_instance()
        provider = MagicMock()
        provider.name = "Claude"
        provider.fetch.side_effect = Exception("Connection failed")

        status = app._fetch_provider(provider)

        assert status.provider_name == "Claude"
        assert status.metrics == []
        assert "Connection failed" in status.error

    def test_truncates_long_error(self):
        app = self._make_app_instance()
        provider = MagicMock()
        provider.name = "Claude"
        provider.fetch.side_effect = Exception("x" * 200)

        status = app._fetch_provider(provider)
        assert len(status.error) <= 80


class TestMenuTitleFormatting:
    """Test the title construction logic from _refresh_all (extracted behavior)."""

    def test_single_provider_title(self):
        from app import indicator

        metrics = [UsageMetric(label="5-hour", utilization=30.0, is_primary=True)]
        status = ProviderStatus(provider_name="Claude", metrics=metrics)

        # Simulate the title-building logic from _refresh_all
        title_parts = []
        for m in status.metrics:
            if m.is_primary:
                icon = indicator(m.utilization)
                title_parts.append(f"CC {icon}{m.utilization:.0f}%")

        title = " \u00b7 ".join(title_parts)
        assert title == "CC 30%"

    def test_high_usage_shows_icon(self):
        from app import indicator

        metrics = [UsageMetric(label="5-hour", utilization=95.0, is_primary=True)]
        status = ProviderStatus(provider_name="Claude", metrics=metrics)

        title_parts = []
        for m in status.metrics:
            if m.is_primary:
                icon = indicator(m.utilization)
                title_parts.append(f"CC {icon}{m.utilization:.0f}%")

        title = " \u00b7 ".join(title_parts)
        assert "\U0001f534" in title
        assert "95%" in title
