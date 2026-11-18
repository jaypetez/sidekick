"""Tests for the top-level argparse dispatcher in sidekick.cli.main."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from sidekick.cli import main as cli_main

from .conftest import CSRF_TOKEN, envelope_err, envelope_ok


def _stub_handler(response_data, status: int = 200, error_envelope=None):
    """Build an httpx handler that returns the same payload for any request."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = error_envelope if error_envelope else envelope_ok(response_data)
        return httpx.Response(status, json=payload)

    return handler


def _run(argv, response_data=None, *, status=200, error_envelope=None):
    """Invoke cli_main.main with argv, mocking ApiClient's transport."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_csrf":
            return httpx.Response(200, json={"csrf": CSRF_TOKEN})
        captured.append(request)
        if error_envelope is not None:
            return httpx.Response(status, json=error_envelope)
        return httpx.Response(status, json=envelope_ok(response_data))

    transport = httpx.MockTransport(handler)

    real_init = cli_main.ApiClient.__init__

    def patched_init(self, *, base_url=None, timeout=15.0):
        real_init(self, base_url=base_url or "http://test", timeout=timeout, token="")
        self._client.close()
        self._client = httpx.Client(base_url=self.base_url, transport=transport)

    with patch.object(cli_main.ApiClient, "__init__", patched_init):
        code = cli_main.main(argv)
    return code, captured


def test_help_returns_2_without_subcommand():
    with pytest.raises(SystemExit) as exc:
        cli_main.main([])
    # argparse exits 2 when a required subparser is missing
    assert exc.value.code == 2


def test_tasks_list_hits_correct_endpoint(capsys):
    code, requests = _run(
        ["tasks", "list"], response_data={"lists": [{"name": "A", "open_count": 2}]}
    )
    assert code == 0
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/api/tasks"
    out = capsys.readouterr().out
    assert "name" in out and "open_count" in out
    assert "A" in out


def test_tasks_add_sends_titles_list(capsys):
    code, requests = _run(
        ["tasks", "add", "Costco", "milk", "eggs"], response_data={"added": ["milk", "eggs"]}
    )
    assert code == 0
    body = requests[0].content.decode()
    assert '"titles"' in body
    assert "milk" in body and "eggs" in body
    assert requests[0].url.path == "/api/tasks/Costco/items"


def test_tasks_delete_item_uses_DELETE(capsys):
    code, requests = _run(
        ["tasks", "delete", "Costco", "--item", "milk"],
        response_data={"status": "deleted"},
    )
    assert code == 0
    assert requests[0].method == "DELETE"
    assert requests[0].url.path == "/api/tasks/Costco/items/milk"


def test_tasks_delete_without_item_deletes_list(capsys):
    code, requests = _run(["tasks", "delete", "Costco"], response_data={"status": "deleted"})
    assert code == 0
    assert requests[0].method == "DELETE"
    assert requests[0].url.path == "/api/tasks/Costco"


def test_settings_get_renders_table(capsys):
    snapshot = {
        "LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": {"set": True, "preview": "…abcd"},
        "OLLAMA_NUM_GPU": "",
    }
    code, _ = _run(
        ["settings", "get"],
        response_data={"settings": snapshot, "editable_keys": [], "secret_keys": []},
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "LLM_PROVIDER" in out
    assert "anthropic" in out
    # The raw redacted-secret dict shouldn't bleed through; preview should.
    assert "abcd" in out
    assert "OLLAMA_NUM_GPU" in out


def test_settings_set_sends_patch_body(capsys):
    code, requests = _run(
        ["settings", "set", "OLLAMA_NUM_GPU", "999"],
        response_data={"applied": ["OLLAMA_NUM_GPU"], "llm_reloaded": True, "settings": {}},
    )
    assert code == 0
    assert requests[0].method == "PATCH"
    body = requests[0].content.decode()
    assert '"OLLAMA_NUM_GPU"' in body
    assert '"999"' in body
    out = capsys.readouterr().out
    assert "Saved" in out and "LLM reloaded" in out


def test_chat_send_prints_assistant_reply(capsys):
    code, _ = _run(
        ["chat", "send", "hi"],
        response_data={"chat_id": "cli:default", "user": "hi", "assistant": "hello back"},
    )
    assert code == 0
    assert "hello back" in capsys.readouterr().out


def test_chat_send_uses_provided_chat_id():
    code, requests = _run(
        ["chat", "send", "hi", "--chat-id", "cli:experimentA"],
        response_data={"assistant": "ok"},
    )
    assert code == 0
    body = requests[0].content.decode()
    assert '"chat_id":' in body.replace(" ", "")
    assert "cli:experimentA" in body


def test_reminders_add_required_args():
    code, requests = _run(
        ["reminders", "add", "--message", "stretch", "--hour", "9", "--minute", "0"],
        response_data={"id": "reminder_1"},
    )
    assert code == 0
    body = requests[0].content.decode()
    assert '"hour":9' in body.replace(" ", "")
    assert '"minute":0' in body.replace(" ", "")


def test_envelope_error_exits_nonzero_and_writes_stderr(capsys):
    code, _ = _run(
        ["tasks", "list"],
        error_envelope=envelope_err("provider_error", "Chronary down"),
        status=502,
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "provider_error" in err
    assert "Chronary down" in err


def test_json_flag_emits_raw_envelope_data(capsys):
    code, _ = _run(
        ["--json", "tasks", "list"], response_data={"lists": [{"name": "A", "open_count": 1}]}
    )
    assert code == 0
    out = capsys.readouterr().out
    # Output is parseable JSON
    import json

    parsed = json.loads(out)
    assert parsed == {"lists": [{"name": "A", "open_count": 1}]}


def test_events_list_passes_days_query(capsys):
    code, requests = _run(
        ["events", "list", "--days", "7"], response_data={"events": [], "days": 7}
    )
    assert code == 0
    assert "days=7" in str(requests[0].url)


def test_settings_test_llm_renders_reply(capsys):
    code, _ = _run(
        ["settings", "test-llm"],
        response_data={
            "ok": True,
            "provider": "AnthropicClient",
            "model": "claude-haiku",
            "reply": "OK",
        },
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "AnthropicClient" in out
    assert "OK" in out


SYSTEM_OVERVIEW = {
    "version": "1.2.3",
    "uptime_seconds": 60,
    "status": {"scheduler": True, "mcp": False, "reminders": 3, "tools": 16},
    "llm": {"provider": "ollama", "model": "llama3.1:8b"},
    "platforms": {"telegram": "running", "slack": "disabled"},
    "web": {"host": "127.0.0.1", "port": 8080, "auth_enabled": False},
}

CONFIG_REPORT = {
    "groups": [
        {
            "group": "LLM",
            "settings": [
                {"key": "LLM_PROVIDER", "display": "ollama", "source": "override", "editable": True}
            ],
        },
        {
            "group": "Web dashboard",
            "settings": [
                {
                    "key": "SIDEKICK_WEB_PORT",
                    "display": "8080",
                    "source": "default",
                    "editable": False,
                }
            ],
        },
    ]
}


def test_system_status_human(capsys):
    rc, captured = _run(["system", "status"], SYSTEM_OVERVIEW)
    assert rc == 0
    assert captured[0].url.path == "/api/system"
    out = capsys.readouterr().out
    assert "1.2.3" in out
    assert "ollama · llama3.1:8b" in out
    assert "mcp" in out and "down" in out


def test_system_status_json(capsys):
    rc, _ = _run(["--json", "system", "status"], SYSTEM_OVERVIEW)
    assert rc == 0
    assert '"version": "1.2.3"' in capsys.readouterr().out


def test_system_config_table_and_group_filter(capsys):
    rc, captured = _run(["system", "config", "--group", "llm"], CONFIG_REPORT)
    assert rc == 0
    assert captured[0].url.path == "/api/config"
    out = capsys.readouterr().out
    assert "LLM_PROVIDER" in out
    assert "SIDEKICK_WEB_PORT" not in out


def test_system_config_unknown_group(capsys):
    rc, _ = _run(["system", "config", "--group", "nope"], CONFIG_REPORT)
    assert rc == 0
    assert "no matching group" in capsys.readouterr().out


def test_system_config_json(capsys):
    rc, _ = _run(["--json", "system", "config"], CONFIG_REPORT)
    assert rc == 0
    assert "SIDEKICK_WEB_PORT" in capsys.readouterr().out
