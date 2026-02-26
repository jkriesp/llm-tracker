"""Tests for app.py helper functions: time_remaining, indicator, load/save_config."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def test_time_remaining_none():
    from app import time_remaining

    assert time_remaining(None) == "N/A"


def test_time_remaining_empty_string():
    from app import time_remaining

    assert time_remaining("") == "N/A"


def test_time_remaining_past():
    from app import time_remaining

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert time_remaining(past) == "now"


def test_time_remaining_future_hours(monkeypatch):
    from app import time_remaining

    fixed_now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.datetime", type("FakeDT", (datetime,), {
        "now": classmethod(lambda cls, tz=None: fixed_now),
        "fromisoformat": datetime.fromisoformat,
    }))
    target = fixed_now + timedelta(hours=2, minutes=30)
    result = time_remaining(target.isoformat())
    assert result == "2h 30m"


def test_time_remaining_future_days(monkeypatch):
    from app import time_remaining

    fixed_now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.datetime", type("FakeDT", (datetime,), {
        "now": classmethod(lambda cls, tz=None: fixed_now),
        "fromisoformat": datetime.fromisoformat,
    }))
    target = fixed_now + timedelta(days=1, hours=3)
    result = time_remaining(target.isoformat())
    assert result == "1d 3h"


def test_time_remaining_less_than_one_minute():
    from app import time_remaining

    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert time_remaining(future) == "<1m"


def test_indicator_low():
    from app import indicator

    assert indicator(0) == ""
    assert indicator(50) == ""
    assert indicator(69) == ""


def test_indicator_medium():
    from app import indicator

    assert indicator(70) == "\U0001f7e1"
    assert indicator(80) == "\U0001f7e1"
    assert indicator(89) == "\U0001f7e1"


def test_indicator_high():
    from app import indicator

    assert indicator(90) == "\U0001f534"
    assert indicator(99) == "\U0001f534"
    assert indicator(100) == "\U0001f534"


def test_load_config_missing_file(config_dir):
    from app import load_config

    assert load_config() == {}


def test_save_and_load_config_roundtrip(config_dir):
    from app import load_config, save_config

    data = {"refresh_interval": 120, "claude": {"org_id": "abc"}}
    save_config(data)
    assert load_config() == data


def test_save_config_creates_directory(tmp_path, monkeypatch):
    import app as app_mod

    nested = tmp_path / "a" / "b"
    monkeypatch.setattr(app_mod, "CONFIG_DIR", nested)
    monkeypatch.setattr(app_mod, "CONFIG_FILE", nested / "config.json")

    from app import save_config

    save_config({"key": "value"})
    assert (nested / "config.json").exists()
    assert json.loads((nested / "config.json").read_text()) == {"key": "value"}
