# Codex Usage Provider — Design

**Date:** 2026-04-28
**Status:** Approved
**Topic:** Add OpenAI Codex usage tracking to CC Usage Tracker

## Goal

Track Codex (CLI / chatgpt.com) usage alongside Claude in the same macOS menu bar app, so the title shows e.g. `CC 30% · CX 1%` and the dropdown shows both providers' rate-limit windows.

## Approach

Verbatim mirror of the existing `ClaudeProvider` pattern. A new `CodexProvider` calls a different endpoint, maps the response into `UsageMetric` objects, and otherwise reuses the cookie-from-browser → Keychain → polling flow already in place. No shared base class for cookie auth — the duplication between two providers is small and an abstraction would obscure differences. Refactor when a third provider arrives.

## Architecture

A new module `providers/codex.py` defines `CodexProvider(BaseProvider)`. It is registered in `app.py`'s `self.providers` list alongside `ClaudeProvider`.

- **`name`**: `"Codex"`
- **`short_name`**: `"CX"` (renders as `CC 30% · CX 1%` in the menu bar title)
- **Auth:** chatgpt.com session cookie, extracted from a Chromium-based browser (or Firefox) via `pycookiecheat`, stored in macOS Keychain
- **Endpoint:** `GET https://chatgpt.com/backend-api/wham/usage`
- **No org concept:** Codex rate limits are user-level. The configuration only stores `browser` (and the cookie in Keychain).

### Files

**New:**
- `providers/codex.py` — `CodexProvider` class
- `tests/test_codex_provider.py` — unit tests

**Modified:**
- `providers/__init__.py` — add `supports_browser_auth: bool = False` flag and stub `auto_setup() -> str` / `refresh_cookie() -> bool` on `BaseProvider`, so the menu wiring and 401-recovery can use a capability check instead of `isinstance`
- `providers/claude.py` — set `supports_browser_auth = True` (no behaviour change; `auto_setup` and `refresh_cookie` are already implemented)
- `app.py`:
  - Register `CodexProvider()` in `self.providers`
  - Replace `isinstance(provider, ClaudeProvider)` checks in `_build_menu` and `_refresh_all` with `provider.supports_browser_auth`
  - Parameterise `_run_auto_setup(provider)` rather than searching for the Claude provider; existing first-launch flow keeps targeting Claude

## Data flow

1. App polls every `refresh_interval` seconds (default 300s)
2. For each configured provider, `_fetch_provider` calls `provider.fetch()`
3. `CodexProvider.fetch()` issues `GET chatgpt.com/backend-api/wham/usage` with the cookie; raises on non-2xx
4. Response is mapped to `UsageMetric` objects (see "Response mapping")
5. On 401, `_refresh_all` calls `provider.refresh_cookie()` once per cycle (same de-duplication as Claude) and retries

## Response mapping

The endpoint returns:

```json
{
  "rate_limit": {
    "primary_window":   {"used_percent": 1, "reset_at": 1777376345, "limit_window_seconds": 18000},
    "secondary_window": {"used_percent": 0, "reset_at": 1777963145, "limit_window_seconds": 604800}
  },
  "code_review_rate_limit": null,
  "additional_rate_limits": [
    {
      "limit_name": "GPT-5.3-Codex-Spark",
      "rate_limit": {
        "primary_window":   {"used_percent": 0, "reset_at": 1777378162, "limit_window_seconds": 18000},
        "secondary_window": {"used_percent": 0, "reset_at": 1777964962, "limit_window_seconds": 604800}
      }
    }
  ],
  "credits": { "...": "..." },
  "spend_control": { "...": "..." }
}
```

Mapping:

| Source | UsageMetric |
|---|---|
| `rate_limit.primary_window` | `label="5-hour"`, `is_primary=True`, `resets_at=<iso>` |
| `rate_limit.secondary_window` | `label="7-day"`, `is_primary=False` |
| For each `additional_rate_limits[i].rate_limit.secondary_window` | `label=f"7-day {limit_name}"`, `is_primary=False` |
| `code_review_rate_limit.primary_window` (if non-null) | `label="Code review 5-hour"` |
| `code_review_rate_limit.secondary_window` (if non-null) | `label="Code review 7-day"` |

Notes:
- `used_percent` is already in 0–100 range. Map directly to `UsageMetric.utilization` (no scaling)
- `reset_at` is a Unix epoch in seconds. Convert to ISO-with-UTC-tzinfo before constructing `UsageMetric` so the existing `time_remaining()` helper in `app.py` (which does `datetime.fromisoformat`) works unchanged
- The menu has 6 metric slots per provider. Default response has 3 metrics (5h, 7d, 7d Codex-Spark). Headroom of 3 covers most realistic future expansion.
- `credits` and `spend_control` are intentionally not surfaced. On subscription plans they read zero/inactive. Revisit when relevant.

## Auth & secrets

- **Cookie name:** `__Secure-next-auth.session-token`. The exact name will be verified during implementation by inspecting `pycookiecheat`'s output in a smoke test. If different, the constant in `providers/codex.py` is the only change.
- **Keychain service:** `cc-usage-tracker` (same as Claude — a single-app namespace)
- **Keychain account:** `codex-session-key` (distinct from `claude-session-key`)
- `to_dict()` exposes only `browser`. Cookie value never written to `~/.config/cc-usage-tracker/config.json`

## Configure UX

The Configure submenu in the menu bar gains a Codex entry with:

- **Auto Setup** — extract chatgpt.com session cookie from selected browser, store in Keychain, immediately refresh
- **Refresh Cookie** — re-extract cookie from browser
- **Manual Setup** — single field (cookie value), since there is no org id

Browser is selected via the existing `_pick_browser()` flow.

First-launch onboarding remains Claude-focused — the Codex flow is reached via Configure → Codex from the menu bar. (Adding a second forced onboarding step would be poor UX for users who don't have a Codex subscription.)

## Configuration on disk

`~/.config/cc-usage-tracker/config.json`:

```json
{
  "claude": {"org_id": "...", "browser": "Brave"},
  "codex":  {"browser": "Brave"},
  "refresh_interval": 300
}
```

The `codex` key is absent until the user configures the provider; `is_configured()` returns false in that state and the polling loop skips it.

## BaseProvider capability flag

To keep the menu wiring and 401-recovery clean, add a small flag and stub methods:

```python
# providers/__init__.py
class BaseProvider:
    name: str = "Unknown"
    short_name: str = "??"
    supports_browser_auth: bool = False

    # ...existing abstract methods...

    def auto_setup(self) -> str:
        raise NotImplementedError

    def refresh_cookie(self) -> bool:
        return False
```

Both `ClaudeProvider` and `CodexProvider` set `supports_browser_auth = True`. `_build_menu` and the 401 branch in `_refresh_all` switch from `isinstance(provider, ClaudeProvider)` to `provider.supports_browser_auth`.

This is the minimum change to support multiple cookie-auth providers without `isinstance` proliferation. Not a wholesale extraction into a shared base class — that's deferred until justified by a third provider.

## Testing

`tests/test_codex_provider.py` (mirror of `tests/test_claude_provider.py`):

- `test_fetch_parses_full_response` — feed the user-supplied JSON via `requests_mock` (or equivalent), expect three metrics in order: `5-hour` (primary), `7-day`, `7-day GPT-5.3-Codex-Spark`. `is_primary=True` only on `5-hour`. `resets_at` strings round-trip through `time_remaining()`.
- `test_fetch_handles_null_code_review_rate_limit` — null doesn't crash; no Code-review metric emitted.
- `test_fetch_handles_empty_additional_rate_limits` — empty list emits only 5h + 7d.
- `test_fetch_handles_code_review_rate_limit_present` — synthetic non-null `code_review_rate_limit` produces two extra metrics.
- `test_fetch_raises_on_401` — surfaces upstream so the app's 401-recovery branch can run
- `test_to_dict_excludes_session_key` — only `browser` is serialised
- `test_unix_epoch_to_iso_conversion` — utility test for the timestamp helper
- `test_used_percent_is_zero_when_zero` — guard against the historical Claude bug where `None` utilization crashed; defensive on `used_percent` field

All AppKit/Keychain dependencies are already mocked in `tests/conftest.py`.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cookie name (`__Secure-next-auth.session-token`) differs from assumption | Verify during implementation; constant is in one place |
| `used_percent` turns out to be 0–1 instead of 0–100 | First implementation step is a smoke run against the real endpoint to confirm |
| `reset_at` is in milliseconds, not seconds | Same smoke run confirms |
| `wham/usage` requires an additional header (CSRF, beta cohort) | Cookie alone may not be sufficient; if so, replicate browser headers (User-Agent, Accept, possibly `OAI-Device-Id`) by inspecting the Network tab again |
| `code_review_rate_limit` shape is unknown until non-null | Treat as identical to `rate_limit` based on naming; defensive parsing |
| Cookie expires more aggressively than Claude's | Same Refresh Cookie path as Claude; revisit `~/.codex/auth.json` token approach if it becomes painful |

## Non-goals

- Reading `~/.codex/auth.json` for shared auth (deferred; cookie path is proven)
- Tracking ChatGPT chat usage (different endpoint, not Codex)
- Tracking `platform.openai.com` API-key billing (different auth, different endpoint, different account model)
- Surfacing `credits.balance` or `spend_control` (zero/inactive on subscription plans)
- Onboarding-first flow for Codex (Configure menu only — avoids forcing the flow on Claude-only users)
- Refactoring Claude/Codex into a shared `CookieAuthProvider` base class (deferred until a third cookie-auth provider arrives)
