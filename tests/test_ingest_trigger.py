"""
tests/test_ingest_trigger.py — Tests for POST /ingest/trigger and GET /ingest/status.

Uses Flask's built-in test client and monkeypatches the module-level
_ingest_process handle so no real subprocess is ever spawned.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as app_module
from app import app as flask_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_ingest_process(monkeypatch):
    """Ensure _ingest_process is always None before and after each test."""
    monkeypatch.setattr(app_module, "_ingest_process", None)
    yield
    monkeypatch.setattr(app_module, "_ingest_process", None)


@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _make_mock_process(*, exited: bool = False) -> MagicMock:
    """Return a MagicMock that behaves like a running or finished Popen handle."""
    proc = MagicMock()
    proc.poll.return_value = None if not exited else 0
    return proc


# ---------------------------------------------------------------------------
# POST /ingest/trigger — happy path
# ---------------------------------------------------------------------------

class TestIngestTrigger:
    def test_returns_202_when_idle(self, client, monkeypatch):
        """Trigger while idle should start a subprocess and return 202."""
        spawned = []

        def mock_popen(cmd, **kwargs):
            spawned.append(cmd)
            return _make_mock_process()

        monkeypatch.setattr(app_module.subprocess, "Popen", mock_popen)
        resp = client.post("/ingest/trigger")
        assert resp.status_code == 202
        assert len(spawned) == 1

    def test_response_is_html_partial(self, client, monkeypatch):
        """202 response body should be the running HTML partial."""
        monkeypatch.setattr(
            app_module.subprocess, "Popen", lambda *a, **kw: _make_mock_process()
        )
        resp = client.post("/ingest/trigger")
        body = resp.data.decode()
        assert "ingest-status" in body
        assert "Running" in body

    def test_default_hours_is_25(self, client, monkeypatch):
        """When no hours param is submitted, --hours 25 should be in the command."""
        spawned = []

        def mock_popen(cmd, **kwargs):
            spawned.append(cmd)
            return _make_mock_process()

        monkeypatch.setattr(app_module.subprocess, "Popen", mock_popen)
        client.post("/ingest/trigger")
        assert "--hours" in spawned[0]
        assert "25" in spawned[0]

    def test_custom_hours_forwarded(self, client, monkeypatch):
        """Submitting hours=48 should produce --hours 48 in the command."""
        spawned = []

        def mock_popen(cmd, **kwargs):
            spawned.append(cmd)
            return _make_mock_process()

        monkeypatch.setattr(app_module.subprocess, "Popen", mock_popen)
        client.post("/ingest/trigger", data={"hours": "48"})
        assert "48" in spawned[0]

    def test_rescore_flag_forwarded_when_checked(self, client, monkeypatch):
        """Submitting rescore=1 should append --rescore to the command."""
        spawned = []

        def mock_popen(cmd, **kwargs):
            spawned.append(cmd)
            return _make_mock_process()

        monkeypatch.setattr(app_module.subprocess, "Popen", mock_popen)
        client.post("/ingest/trigger", data={"rescore": "1"})
        assert "--rescore" in spawned[0]

    def test_rescore_flag_absent_when_unchecked(self, client, monkeypatch):
        """Omitting the rescore field should NOT include --rescore in the command."""
        spawned = []

        def mock_popen(cmd, **kwargs):
            spawned.append(cmd)
            return _make_mock_process()

        monkeypatch.setattr(app_module.subprocess, "Popen", mock_popen)
        client.post("/ingest/trigger")
        assert "--rescore" not in spawned[0]

    def test_invalid_hours_falls_back_to_25(self, client, monkeypatch):
        """Non-numeric hours input should silently fall back to the default 25."""
        spawned = []

        def mock_popen(cmd, **kwargs):
            spawned.append(cmd)
            return _make_mock_process()

        monkeypatch.setattr(app_module.subprocess, "Popen", mock_popen)
        client.post("/ingest/trigger", data={"hours": "not-a-number"})
        assert "25" in spawned[0]

    def test_uses_sys_executable(self, client, monkeypatch):
        """The subprocess must be started with sys.executable, not a hardcoded path."""
        spawned = []

        def mock_popen(cmd, **kwargs):
            spawned.append(cmd)
            return _make_mock_process()

        monkeypatch.setattr(app_module.subprocess, "Popen", mock_popen)
        client.post("/ingest/trigger")
        assert spawned[0][0] == sys.executable

    def test_popen_failure_returns_500(self, client, monkeypatch):
        """If Popen raises OSError (e.g. executable not found), the route returns 500."""
        def failing_popen(cmd, **kwargs):
            raise OSError("python not found")
        monkeypatch.setattr(app_module.subprocess, "Popen", failing_popen)
        resp = client.post("/ingest/trigger")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /ingest/trigger — concurrent run rejected
# ---------------------------------------------------------------------------

class TestIngestTriggerConflict:
    def test_returns_409_when_already_running(self, client, monkeypatch):
        """Triggering while a process is running should return 409."""
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process())
        resp = client.post("/ingest/trigger")
        assert resp.status_code == 409

    def test_409_body_is_json_error(self, client, monkeypatch):
        """The 409 response body should be JSON with an 'error' key."""
        import json
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process())
        resp = client.post("/ingest/trigger")
        data = json.loads(resp.data)
        assert data.get("error") == "already running"

    def test_no_second_popen_when_already_running(self, client, monkeypatch):
        """A second call while running must not spawn another subprocess."""
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process())
        popen_calls = []
        monkeypatch.setattr(
            app_module.subprocess,
            "Popen",
            lambda *a, **kw: popen_calls.append(1) or _make_mock_process(),
        )
        client.post("/ingest/trigger")
        assert popen_calls == []


# ---------------------------------------------------------------------------
# GET /ingest/status
# ---------------------------------------------------------------------------

class TestIngestStatus:
    def test_returns_200(self, client):
        resp = client.get("/ingest/status")
        assert resp.status_code == 200

    def test_idle_returns_button(self, client):
        """With no running process the response should contain the idle button."""
        resp = client.get("/ingest/status")
        body = resp.data.decode()
        assert "Run Ingestion" in body

    def test_running_returns_running_partial(self, client, monkeypatch):
        """While a process is active the response should contain the running indicator."""
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process())
        resp = client.get("/ingest/status")
        body = resp.data.decode()
        assert "Running" in body

    def test_running_partial_contains_polling_trigger(self, client, monkeypatch):
        """The running partial must carry hx-trigger so HTMX keeps polling."""
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process())
        resp = client.get("/ingest/status")
        body = resp.data.decode()
        assert "every 2s" in body

    def test_completed_process_resets_to_idle(self, client, monkeypatch):
        """Once poll() returns non-None the handle is cleared and idle HTML is returned."""
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process(exited=True))
        resp = client.get("/ingest/status")
        body = resp.data.decode()
        assert "Run Ingestion" in body
        # Handle must be cleared.
        assert app_module._ingest_process is None

    def test_idle_response_carries_hx_trigger_header(self, client):
        """When returning idle state, HX-Trigger header signals ingestComplete."""
        resp = client.get("/ingest/status")
        assert resp.headers.get("HX-Trigger") == "ingestComplete"

    def test_running_response_has_no_hx_trigger_header(self, client, monkeypatch):
        """While still running, HX-Trigger must not be present."""
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process())
        resp = client.get("/ingest/status")
        assert "HX-Trigger" not in resp.headers


# ---------------------------------------------------------------------------
# _ingest_running helper — unit tests
# ---------------------------------------------------------------------------

class TestIngestRunningHelper:
    def test_returns_false_when_no_handle(self, monkeypatch):
        monkeypatch.setattr(app_module, "_ingest_process", None)
        assert app_module._ingest_running() is False

    def test_returns_true_while_running(self, monkeypatch):
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process())
        assert app_module._ingest_running() is True

    def test_returns_false_and_clears_handle_after_exit(self, monkeypatch):
        monkeypatch.setattr(app_module, "_ingest_process", _make_mock_process(exited=True))
        result = app_module._ingest_running()
        assert result is False
        assert app_module._ingest_process is None
