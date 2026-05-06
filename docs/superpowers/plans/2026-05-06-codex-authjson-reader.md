# Codex auth.json Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CodexProvider` read its bearer token from `~/.codex/auth.json` (the official Codex CLI's auth file) when present, so users who are logged into the `codex` CLI no longer need browser-cookie scraping. Falls back to the existing cookie path when `auth.json` is absent.

**Architecture:** Add a read-only `_load_authjson_token(path)` helper to `providers/codex.py`. The provider's `fetch()` tries auth.json first; on a 401 it raises a clear "run `codex login`" error rather than silently falling back to cookies — refresh is delegated to the user via the official CLI. When `auth.json` is missing entirely, the provider falls back to the existing NextAuth cookie-exchange flow. No write-back to `auth.json`; the file remains owned by the official CLI.

**Tech Stack:** Python 3.13, pytest, requests, keyring. No new dependencies.

---

## File Structure

- **Modify:** `providers/codex.py` — add `_load_authjson_token()` helper, extract `_fetch_usage_with_bearer()` private method, update `fetch()` and `is_configured()`.
- **Modify:** `tests/test_codex_provider.py` — add an autouse fixture that defaults `_load_authjson_token` to `None`, plus three new test classes covering the helper, the auth.json fetch path, and the new `is_configured` logic.
- **Modify:** `CLAUDE.md` — one bullet documenting the auth-source priority.

---

## Task 1: Add `_load_authjson_token()` helper

The helper accepts an explicit path argument (defaulting to `~/.codex/auth.json`) so tests can pass `tmp_path / "auth.json"` and never touch the real file.

**Files:**
- Modify: `providers/codex.py` (add helper near other module-level helpers, after `_unix_to_iso`)
- Test: `tests/test_codex_provider.py` (new `TestLoadAuthjsonToken` class — append to the end of the file before the existing `TestGetConfigFields`)

- [ ] **Step 1: Write the failing tests**

At the top of `tests/test_codex_provider.py`, add this import alongside the existing ones:

```python
import json
```

Append this class to `tests/test_codex_provider.py` (place it just before `class TestGetConfigFields`):

```python
# ── _load_authjson_token ──────────────────────────────────────────────────────


class TestLoadAuthjsonToken:
    """`_load_authjson_token` reads the access_token from ~/.codex/auth.json."""

    def test_returns_token_when_well_formed(self, tmp_path):
        from providers.codex import _load_authjson_token
        p = tmp_path / "auth.json"
        # Mirrors the real shape the codex CLI writes: lowercase enum for
        # auth_mode, id_token as a raw JWT string (not an object).
        p.write_text(json.dumps({
            "tokens": {
                "access_token": "jwt-abc",
                "refresh_token": "rt-1",
                "id_token": "header.payload.sig",
                "account_id": "acc-1",
            },
            "auth_mode": "chatgpt",
        }))
        assert _load_authjson_token(p) == "jwt-abc"

    def test_returns_none_when_file_missing(self, tmp_path):
        from providers.codex import _load_authjson_token
        assert _load_authjson_token(tmp_path / "missing.json") is None

    def test_returns_none_when_json_malformed(self, tmp_path):
        from providers.codex import _load_authjson_token
        p = tmp_path / "auth.json"
        p.write_text("{ not json")
        assert _load_authjson_token(p) is None

    def test_returns_none_when_tokens_key_missing(self, tmp_path):
        from providers.codex import _load_authjson_token
        p = tmp_path / "auth.json"
        p.write_text(json.dumps({"auth_mode": "apikey"}))
        assert _load_authjson_token(p) is None

    def test_returns_none_when_access_token_missing(self, tmp_path):
        from providers.codex import _load_authjson_token
        p = tmp_path / "auth.json"
        p.write_text(json.dumps({"tokens": {"refresh_token": "rt"}}))
        assert _load_authjson_token(p) is None

    def test_returns_none_when_access_token_empty(self, tmp_path):
        from providers.codex import _load_authjson_token
        p = tmp_path / "auth.json"
        p.write_text(json.dumps({"tokens": {"access_token": ""}}))
        assert _load_authjson_token(p) is None

    def test_returns_none_when_tokens_not_dict(self, tmp_path):
        from providers.codex import _load_authjson_token
        p = tmp_path / "auth.json"
        p.write_text(json.dumps({"tokens": "garbage"}))
        assert _load_authjson_token(p) is None

    def test_returns_none_when_top_level_not_dict(self, tmp_path):
        from providers.codex import _load_authjson_token
        p = tmp_path / "auth.json"
        p.write_text(json.dumps(["not", "a", "dict"]))
        assert _load_authjson_token(p) is None

    def test_default_path_resolves_to_module_constant(self, tmp_path, monkeypatch):
        from providers import codex as mod
        fake_dir = tmp_path / ".codex"
        fake_dir.mkdir()
        fake_file = fake_dir / "auth.json"
        fake_file.write_text(json.dumps(
            {"tokens": {"access_token": "default-jwt"}}
        ))
        monkeypatch.setattr(mod, "DEFAULT_AUTHJSON_PATH", fake_file)
        assert mod._load_authjson_token() == "default-jwt"
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `pytest tests/test_codex_provider.py::TestLoadAuthjsonToken -v`
Expected: All 9 tests FAIL with `ImportError: cannot import name '_load_authjson_token' from 'providers.codex'`.

- [ ] **Step 3: Implement the helper**

In `providers/codex.py`, add these imports near the top (after the existing `from __future__ import annotations` block, alongside `import keyring`):

```python
import json
from pathlib import Path
```

Then add this constant + helper immediately after the existing `_unix_to_iso` function (around line 100):

```python
DEFAULT_AUTHJSON_PATH = Path.home() / ".codex" / "auth.json"


def _load_authjson_token(path: Path | None = None) -> str | None:
    """Return the access_token from ~/.codex/auth.json, or None.

    The official `codex` CLI writes this file (mode 0600) when the user
    runs `codex login` and rotates the token there. We only ever read it
    — refresh is delegated to the CLI itself. Any error (file missing,
    malformed JSON, missing/blank token) returns None so the caller can
    fall back to the cookie path or surface a "not configured" error.

    Best-effort: this does not validate file mode, ownership, or whether
    the path is a symlink. The CLI owns the file; we just read it. A
    concurrent CLI rewrite that lands mid-read produces a JSONDecodeError
    here and we return None — the next poll picks up the new token.
    """
    p = path if path is not None else DEFAULT_AUTHJSON_PATH
    try:
        raw = p.read_text()
    except (FileNotFoundError, OSError, PermissionError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    token = tokens.get("access_token")
    return token if isinstance(token, str) and token else None
```

- [ ] **Step 4: Run the new tests to confirm they pass**

Run: `pytest tests/test_codex_provider.py::TestLoadAuthjsonToken -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add providers/codex.py tests/test_codex_provider.py
git commit -m "Add _load_authjson_token helper for Codex CLI credentials"
```

---

## Task 2: Extract `_fetch_usage_with_bearer()` private method

Pure refactor — splits the GET call + metric parsing out of `fetch()` so both the auth.json and cookie paths can share it. No behavior change.

**Files:**
- Modify: `providers/codex.py` (`CodexProvider.fetch`)

- [ ] **Step 1: Refactor `fetch()` to extract a private method**

In `providers/codex.py`, replace the existing `CodexProvider.fetch` method (currently around lines 188–254) with:

```python
def fetch(self) -> list[UsageMetric]:
    if not self.session_key:
        raise RuntimeError("CodexProvider not configured: session key missing")

    access_token = _get_access_token(self.session_key, self.browser)
    return self._fetch_usage_with_bearer(access_token)

def _fetch_usage_with_bearer(self, access_token: str) -> list[UsageMetric]:
    """Issue the /wham/usage call with a bearer token and parse metrics.

    The token may come from either the NextAuth session exchange
    (cookie path) or from ~/.codex/auth.json (CLI path). Both produce
    JWTs the wham endpoint accepts.
    """
    resp = requests.get(
        USAGE_ENDPOINT,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {access_token}",
        },
        allow_redirects=False,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    metrics: list[UsageMetric] = []

    rate_limit = data.get("rate_limit") or {}
    primary = rate_limit.get("primary_window")
    if primary:
        metrics.append(UsageMetric(
            label="5-hour",
            utilization=primary.get("used_percent") or 0,
            resets_at=_unix_to_iso(primary.get("reset_at")),
            is_primary=True,
        ))
    secondary = rate_limit.get("secondary_window")
    if secondary:
        metrics.append(UsageMetric(
            label="7-day",
            utilization=secondary.get("used_percent") or 0,
            resets_at=_unix_to_iso(secondary.get("reset_at")),
        ))

    for entry in data.get("additional_rate_limits") or []:
        limit_name = entry.get("limit_name", "Unknown")
        sub_rl = entry.get("rate_limit") or {}
        sub_secondary = sub_rl.get("secondary_window")
        if sub_secondary:
            metrics.append(UsageMetric(
                label=f"7-day {limit_name}",
                utilization=sub_secondary.get("used_percent") or 0,
                resets_at=_unix_to_iso(sub_secondary.get("reset_at")),
            ))

    code_review = data.get("code_review_rate_limit")
    if code_review:
        cr_primary = code_review.get("primary_window")
        if cr_primary:
            metrics.append(UsageMetric(
                label="Code review 5-hour",
                utilization=cr_primary.get("used_percent") or 0,
                resets_at=_unix_to_iso(cr_primary.get("reset_at")),
            ))
        cr_secondary = code_review.get("secondary_window")
        if cr_secondary:
            metrics.append(UsageMetric(
                label="Code review 7-day",
                utilization=cr_secondary.get("used_percent") or 0,
                resets_at=_unix_to_iso(cr_secondary.get("reset_at")),
            ))

    return metrics
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests still pass — this is a behavior-preserving refactor. The existing `TestFetch` and `TestFetchTwoStepFlow` classes exercise `fetch()` end-to-end and should continue to pass unchanged.

- [ ] **Step 3: Commit**

```bash
git add providers/codex.py
git commit -m "Extract _fetch_usage_with_bearer in CodexProvider"
```

---

## Task 3: Wire the auth.json path into `fetch()` and `is_configured()`

**Files:**
- Modify: `providers/codex.py` (`CodexProvider.fetch`, `CodexProvider.is_configured`)
- Modify: `tests/test_codex_provider.py` (add module-level autouse fixture, plus new `TestFetchAuthjsonPath` and `TestIsConfiguredAuthjson` classes)

The new `fetch()` tries auth.json first; on 401 it raises a clear "run `codex login`" error; if `_load_authjson_token()` returns None it falls through to the existing cookie path.

The autouse fixture is the safety net: it points `DEFAULT_AUTHJSON_PATH` at a guaranteed-non-existent path for every test in this file. The real `_load_authjson_token` parser still runs (so Task 1's `TestLoadAuthjsonToken` tests, which pass their own paths, are unaffected) — but any caller that doesn't pass an explicit path gets None. Tests that exercise the auth.json path through `fetch()` or `is_configured()` patch `_load_authjson_token` explicitly to return a token.

- [ ] **Step 1: Add the autouse fixture**

In `tests/test_codex_provider.py`, add this fixture near the top of the module — immediately after the imports and before `class TestCodexProviderInit`:

```python
@pytest.fixture(autouse=True)
def _no_authjson_by_default(monkeypatch, tmp_path):
    """Default: tests don't see a real ~/.codex/auth.json on the dev box.

    Redirects the module's default path to a non-existent file under tmp_path.
    The real loader still runs — so Task 1's TestLoadAuthjsonToken (which
    passes its own paths) is unaffected. Tests that need to exercise the
    auth.json path through fetch()/is_configured() should patch
    `providers.codex._load_authjson_token` explicitly.
    """
    monkeypatch.setattr(
        "providers.codex.DEFAULT_AUTHJSON_PATH",
        tmp_path / "no-such-authjson.json",
    )
```

- [ ] **Step 2: Confirm existing tests still pass with the fixture**

Run: `pytest tests/test_codex_provider.py -v`
Expected: All existing tests still pass (the fixture is a no-op for tests that don't touch auth.json).

- [ ] **Step 3: Write the failing tests**

Append these two classes to `tests/test_codex_provider.py` (place them just before `class TestGetConfigFields`):

```python
# ── fetch with auth.json ──────────────────────────────────────────────────────


class TestFetchAuthjsonPath:
    """fetch() prefers ~/.codex/auth.json when readable."""

    @patch("providers.codex._load_authjson_token", return_value="jwt-from-authjson")
    @patch("providers.codex.requests.get")
    def test_uses_authjson_token_when_available(
        self, mock_get, _mock_load, mock_keyring,
    ):
        p = CodexProvider()  # no session key set
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: WHAM_USAGE_FIXTURE,
        )
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()

        # Only one HTTP call — the wham endpoint, with the auth.json bearer.
        assert mock_get.call_count == 1
        url = mock_get.call_args[0][0]
        assert "wham/usage" in url
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer jwt-from-authjson"
        assert len(metrics) == 3

    @patch("providers.codex._load_authjson_token", return_value="jwt-from-authjson")
    @patch("providers.codex.requests.get")
    def test_authjson_skips_session_endpoint(
        self, mock_get, _mock_load, mock_keyring,
    ):
        """When auth.json is used, the /api/auth/session exchange is skipped."""
        p = CodexProvider()
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: WHAM_USAGE_FIXTURE,
        )
        mock_get.return_value.raise_for_status = MagicMock()

        p.fetch()

        for call in mock_get.call_args_list:
            assert "api/auth/session" not in call[0][0]

    @patch("providers.codex._load_authjson_token", return_value="expired-jwt")
    @patch("providers.codex.requests.get")
    def test_authjson_401_raises_codex_login_hint(
        self, mock_get, _mock_load, mock_keyring,
    ):
        from requests.exceptions import HTTPError

        p = CodexProvider()
        resp = MagicMock(status_code=401)
        err = HTTPError("401 Unauthorized")
        err.response = resp
        resp.raise_for_status.side_effect = err
        mock_get.return_value = resp

        with pytest.raises(RuntimeError, match=r"codex login"):
            p.fetch()

    @patch("providers.codex._load_authjson_token", return_value="jwt")
    @patch("providers.codex.requests.get")
    def test_authjson_500_propagates(
        self, mock_get, _mock_load, mock_keyring,
    ):
        """Non-401 errors bubble up — they aren't cured by re-running codex login."""
        from requests.exceptions import HTTPError

        p = CodexProvider()
        resp = MagicMock(status_code=500)
        err = HTTPError("500 Server Error")
        err.response = resp
        resp.raise_for_status.side_effect = err
        mock_get.return_value = resp

        with pytest.raises(HTTPError):
            p.fetch()

    @patch("providers.codex._load_authjson_token", return_value=None)
    @patch("providers.codex._get_access_token", return_value="bearer-from-cookie")
    @patch("providers.codex.requests.get")
    def test_falls_back_to_cookie_path_when_authjson_absent(
        self, mock_get, _mock_token, _mock_load, mock_keyring,
    ):
        p = CodexProvider(session_key="sk-1")
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: WHAM_USAGE_FIXTURE,
        )
        mock_get.return_value.raise_for_status = MagicMock()

        metrics = p.fetch()

        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer bearer-from-cookie"
        assert len(metrics) == 3

    def test_no_authjson_no_cookie_raises_not_configured(self, mock_keyring):
        # Autouse fixture already stubs auth.json to None.
        p = CodexProvider()  # no session key
        with pytest.raises(RuntimeError, match="not configured"):
            p.fetch()


# ── is_configured with auth.json ──────────────────────────────────────────────


class TestIsConfiguredAuthjson:
    @patch("providers.codex._load_authjson_token", return_value="jwt-abc")
    def test_true_when_authjson_provides_token(self, _mock_load, mock_keyring):
        p = CodexProvider()  # no session key
        assert p.is_configured() is True

    def test_false_when_neither_authjson_nor_session_key(self, mock_keyring):
        # Autouse fixture stubs auth.json to None.
        p = CodexProvider()
        assert p.is_configured() is False

    def test_true_when_only_session_key(self, mock_keyring):
        # Autouse fixture stubs auth.json to None.
        p = CodexProvider(session_key="sk-1")
        assert p.is_configured() is True
```

- [ ] **Step 4: Run the new tests to confirm they fail**

Run: `pytest tests/test_codex_provider.py::TestFetchAuthjsonPath tests/test_codex_provider.py::TestIsConfiguredAuthjson -v`
Expected: All 9 tests FAIL — `fetch()` doesn't yet read auth.json, `is_configured()` doesn't yet check it.

- [ ] **Step 5: Implement the new fetch + is_configured**

In `providers/codex.py`, replace `CodexProvider.is_configured` and `CodexProvider.fetch` with:

```python
def is_configured(self) -> bool:
    """True if either the official CLI's auth.json yields a token or we have
    a session key cached. auth.json takes precedence at fetch time."""
    if _load_authjson_token() is not None:
        return True
    return bool(self.session_key)

def fetch(self) -> list[UsageMetric]:
    """Fetch usage metrics, preferring ~/.codex/auth.json over browser cookies.

    When the official `codex` CLI is logged in, auth.json yields a fresh
    JWT and the cookie path is skipped entirely. On 401 from the auth.json
    path, we surface a `codex login` hint rather than silently falling
    back — refresh is delegated to the CLI itself.
    """
    authjson_token = _load_authjson_token()
    if authjson_token is not None:
        try:
            return self._fetch_usage_with_bearer(authjson_token)
        except requests.exceptions.HTTPError as e:
            response = getattr(e, "response", None)
            if response is not None and response.status_code == 401:
                raise RuntimeError(
                    "Codex auth.json access token is invalid or expired. "
                    "Run `codex login` to refresh."
                ) from e
            raise

    if not self.session_key:
        raise RuntimeError("CodexProvider not configured: session key missing")
    cookie_token = _get_access_token(self.session_key, self.browser)
    return self._fetch_usage_with_bearer(cookie_token)
```

- [ ] **Step 6: Run the new tests to confirm they pass**

Run: `pytest tests/test_codex_provider.py::TestFetchAuthjsonPath tests/test_codex_provider.py::TestIsConfiguredAuthjson -v`
Expected: All 9 tests PASS.

- [ ] **Step 7: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 8: Manual smoke test (optional but recommended)**

Run from the repo root:

```bash
source .venv/bin/activate
python -c "from providers.codex import CodexProvider; p = CodexProvider(); print('configured:', p.is_configured()); print('metrics:', p.fetch())"
```

Expected (with the user logged into Codex CLI): prints `configured: True` and a list of three `UsageMetric` objects with non-None utilization values. If the user is logged out (auth.json missing) and has no browser cookie configured, expect `configured: False` and a `RuntimeError: CodexProvider not configured`.

- [ ] **Step 9: Commit**

```bash
git add providers/codex.py tests/test_codex_provider.py
git commit -m "CodexProvider: prefer ~/.codex/auth.json over browser cookies"
```

---

## Task 4: Document the auth-source priority in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — amend the existing "Cookie extraction" bullet (it currently claims the app re-extracts on 401, which is no longer true for the Codex auth.json path) and add a new "Codex auth source priority" bullet immediately after it.

- [ ] **Step 1: Amend the Cookie extraction bullet**

In `CLAUDE.md`, find the existing bullet:

```markdown
- **Cookie extraction**: Uses `pycookiecheat` to read browser cookies (Brave/Chrome/Chromium/Firefox). On 401 errors, the app automatically re-extracts a fresh cookie from the browser and retries.
```

Replace it with:

```markdown
- **Cookie extraction**: Uses `pycookiecheat` to read browser cookies (Brave/Chrome/Chromium/Firefox). For Claude, on 401 errors the app automatically re-extracts a fresh cookie from the browser and retries. For Codex, cookie scraping is the fallback path only — see "Codex auth source priority" below.
```

- [ ] **Step 2: Add the new auth-priority bullet immediately after**

```markdown
- **Codex auth source priority**: `CodexProvider.fetch()` reads `~/.codex/auth.json` first when present — the file the official `codex` CLI maintains via `codex login` under its default `file` storage mode. On 401 the user is prompted to re-run `codex login` rather than silently falling back; refresh is delegated to the CLI. Browser-cookie scraping is the fallback only when `auth.json` is absent or unreadable. Note: the codex CLI also supports `keyring`, `auto`, and `ephemeral` storage modes which this provider does not (yet) read — users on those modes will continue to use the cookie path. The app never writes to `auth.json`.
```

- [ ] **Step 3: Run the suite once more**

Run: `pytest tests/ -v`
Expected: All green (CLAUDE.md edits don't affect tests, this is a final sanity check before opening the PR).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Document Codex auth source priority"
```

---

## Out of scope (future PRs)

- **Token refresh** — explicitly delegated to `codex login`; not implemented here.
- **Cookie-jar narrowing** — separate hardening PR; applies to both providers.
- **`curl_cffi` transport swap** — separate PR.
- **UA-staleness CI check** — separate PR.
- **Anthropic Claude provider changes** — held pending ToS clarification.
- **Concurrent-write coordination with the codex CLI** — not needed under read-only design.

---

## Self-Review Notes

- All `_load_authjson_token` failure modes covered: missing file, bad JSON, missing keys, blank token, non-dict tokens, non-dict top level.
- auth.json fetch path tested for: success, no session-endpoint call, 401-with-hint, 500-passthrough, fallback when None.
- Type consistency verified: helper signature `_load_authjson_token(path: Path | None = None) -> str | None` is referenced identically in implementation and all tests.
- Refactor task (Task 2) is behavior-preserving — verified by re-running existing test suite without modification.
- Autouse fixture in Task 3 redirects `DEFAULT_AUTHJSON_PATH` to a missing file rather than stubbing the loader. This keeps Task 1's helper tests (which pass their own paths) functional while still preventing the dev machine's real `~/.codex/auth.json` from leaking into other tests.

## Post-Review Acknowledgments (Codex review applied)

- **Concurrent CLI rotation read-tearing**: If the codex CLI rotates the token mid-read, `_load_authjson_token` returns None on `JSONDecodeError` and we fall through to the cookie path (or "not configured"). Acceptable: the next poll re-reads and succeeds. Not worth retry logic for a sub-second window.
- **File mode / ownership / symlinks**: Not validated. The CLI owns the file; this app is best-effort. Documented in the helper's docstring.
- **CLI keyring/auto/ephemeral storage modes**: Not supported in this PR. Users on those modes continue to use the cookie path. Documented in the new CLAUDE.md bullet.
- **Fixture data realism**: `auth_mode` lowercased and `id_token` represented as a JWT string in test fixtures, matching the real shape the codex CLI writes. The helper doesn't depend on either field, but realistic fixtures prevent reviewer confusion.
