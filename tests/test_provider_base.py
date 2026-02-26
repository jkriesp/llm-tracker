"""Tests for providers/__init__.py — UsageMetric, ProviderStatus, BaseProvider."""

from __future__ import annotations

from providers import BaseProvider, ProviderStatus, UsageMetric


class TestUsageMetric:
    def test_defaults(self):
        m = UsageMetric(label="5-hour", utilization=42.5)
        assert m.label == "5-hour"
        assert m.utilization == 42.5
        assert m.resets_at is None
        assert m.is_primary is False

    def test_with_all_fields(self):
        m = UsageMetric(
            label="7-day",
            utilization=80.0,
            resets_at="2026-03-01T00:00:00Z",
            is_primary=True,
        )
        assert m.resets_at == "2026-03-01T00:00:00Z"
        assert m.is_primary is True


class TestProviderStatus:
    def test_empty_metrics(self):
        s = ProviderStatus(provider_name="Test")
        assert s.metrics == []
        assert s.error is None

    def test_with_error(self):
        s = ProviderStatus(provider_name="Test", error="401 Unauthorized")
        assert s.error == "401 Unauthorized"
        assert s.metrics == []

    def test_with_metrics(self):
        metrics = [
            UsageMetric(label="5-hour", utilization=30.0, is_primary=True),
            UsageMetric(label="7-day", utilization=10.0),
        ]
        s = ProviderStatus(provider_name="Claude", metrics=metrics)
        assert len(s.metrics) == 2
        assert s.metrics[0].is_primary is True


class TestBaseProvider:
    def test_class_attrs(self):
        assert BaseProvider.name == "Unknown"
        assert BaseProvider.short_name == "??"

    def test_methods_raise(self):
        p = BaseProvider()
        import pytest

        with pytest.raises(NotImplementedError):
            p.is_configured()
        with pytest.raises(NotImplementedError):
            p.fetch()
        with pytest.raises(NotImplementedError):
            p.get_config_fields()
        with pytest.raises(NotImplementedError):
            p.apply_config({})
        with pytest.raises(NotImplementedError):
            p.to_dict()
        with pytest.raises(NotImplementedError):
            BaseProvider.from_dict({})
