"""Usage providers for tracking API usage across services."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UsageMetric:
    """A single usage metric from a provider."""

    label: str
    utilization: float  # 0-100
    resets_at: str | None = None
    is_primary: bool = False  # Show this metric in the menu bar title


@dataclass
class ProviderStatus:
    """Result of a provider fetch."""

    provider_name: str
    metrics: list[UsageMetric] = field(default_factory=list)
    error: str | None = None


class BaseProvider:
    """Base class for usage providers.

    To add a new provider (e.g., OpenAI):
    1. Create a new file in providers/ (e.g., openai.py)
    2. Subclass BaseProvider
    3. Implement all methods
    4. Register it in PROVIDERS in app.py
    """

    name: str = "Unknown"
    short_name: str = "??"  # 2-3 char abbreviation for menu bar

    def is_configured(self) -> bool:
        raise NotImplementedError

    def fetch(self) -> list[UsageMetric]:
        """Fetch current usage metrics. Raises on error."""
        raise NotImplementedError

    def get_config_fields(self) -> list[dict]:
        """Return list of config fields for the setup dialog.

        Each field: {"key": str, "label": str, "message": str, "secure": bool}
        """
        raise NotImplementedError

    def apply_config(self, values: dict) -> None:
        """Apply configuration values from user input."""
        raise NotImplementedError

    def to_dict(self) -> dict:
        """Serialize provider config for persistence."""
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data: dict) -> BaseProvider:
        """Deserialize provider config."""
        raise NotImplementedError
