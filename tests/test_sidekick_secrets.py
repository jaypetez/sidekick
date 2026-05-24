"""Tests for the Azure Key Vault secret helpers in ``scripts/sidekick_secrets.py``.

These tests use ``unittest.mock`` exclusively — no live Azure calls.
The script lives outside ``src/sidekick`` so it isn't part of the coverage
gate; these tests exist purely to catch regressions in the parser, the
required/optional secret logic, and the CLI output formats.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make ``scripts/`` importable as a package on its own. The repo root is
# two parents up from this file.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import sidekick_secrets  # noqa: E402


@pytest.fixture
def dotenv_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text(
        """# A comment
TELEGRAM_BOT_TOKEN=real-telegram-value
CHRONARY_API_KEY=chr_ak_your_agent_key_here
CHRONARY_AGENT_ID=agt_replace_after_init
CHRONARY_CALENDAR_ID=cal_replace_after_init
ANTHROPIC_API_KEY=

# blank line above, quoted value below
SLACK_BOT_TOKEN="xoxb-real-value"
SLACK_APP_TOKEN='xapp-your-app-token'
TIMEZONE=America/Chicago
""",
        encoding="utf-8",
    )
    return path


class TestSecretSpec:
    def test_kv_name_replaces_underscores_with_hyphens(self) -> None:
        spec = sidekick_secrets.SecretSpec("CHRONARY_API_KEY", required=True, description="x")
        assert spec.kv_name == "CHRONARY-API-KEY"

    def test_known_specs_cover_all_documented_secrets(self) -> None:
        names = {s.env_var for s in sidekick_secrets.SECRET_SPECS}
        # If you add a new secret, update SECRET_SPECS *and* this assertion
        # so the wrapper-script docs and the actual upload set stay in sync.
        assert names == {
            "TELEGRAM_BOT_TOKEN",
            "CHRONARY_API_KEY",
            "CHRONARY_AGENT_ID",
            "CHRONARY_CALENDAR_ID",
            "ANTHROPIC_API_KEY",
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "SIDEKICK_WEB_AUTH_TOKEN",
            "SIDEKICK_WEB_SESSION_SECRET",
        }


class TestParseDotenv:
    def test_parses_assignments_skipping_comments_and_blanks(self, dotenv_file: Path) -> None:
        parsed = sidekick_secrets._parse_dotenv(dotenv_file)
        assert parsed["TELEGRAM_BOT_TOKEN"] == "real-telegram-value"
        assert parsed["TIMEZONE"] == "America/Chicago"

    def test_strips_double_and_single_quotes(self, dotenv_file: Path) -> None:
        parsed = sidekick_secrets._parse_dotenv(dotenv_file)
        assert parsed["SLACK_BOT_TOKEN"] == "xoxb-real-value"
        assert parsed["SLACK_APP_TOKEN"] == "xapp-your-app-token"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="not found"):
            sidekick_secrets._parse_dotenv(tmp_path / "does-not-exist")


class TestPush:
    def test_skips_blanks_and_placeholders(self, dotenv_file: Path) -> None:
        mock_client = MagicMock()
        with patch.object(sidekick_secrets, "_build_client", return_value=mock_client):
            written = sidekick_secrets.push("https://example.vault.azure.net/", dotenv_file)

        # Real values get written under the hyphenated KV name.
        assert "TELEGRAM-BOT-TOKEN" in written
        assert "SLACK-BOT-TOKEN" in written
        # Placeholders and blanks are skipped.
        assert "CHRONARY-API-KEY" not in written
        assert "ANTHROPIC-API-KEY" not in written
        assert "SLACK-APP-TOKEN" not in written
        # Non-secret env vars (TIMEZONE) are never uploaded even if real.
        assert all(not w.startswith("TIMEZONE") for w in written)

        # And the actual set_secret call gets the *real* value, not the literal.
        set_calls = {c.args[0]: c.args[1] for c in mock_client.set_secret.call_args_list}
        assert set_calls["TELEGRAM-BOT-TOKEN"] == "real-telegram-value"
        assert set_calls["SLACK-BOT-TOKEN"] == "xoxb-real-value"


class TestPull:
    def _make_client(self, available: dict[str, str]) -> MagicMock:
        from azure.core.exceptions import ResourceNotFoundError

        mock_client = MagicMock()

        def get_secret(name: str):
            if name in available:
                secret = MagicMock()
                secret.value = available[name]
                return secret
            raise ResourceNotFoundError(f"Secret {name} not found")

        mock_client.get_secret.side_effect = get_secret
        return mock_client

    def test_returns_dict_of_env_var_to_value(self) -> None:
        available = {
            "TELEGRAM-BOT-TOKEN": "t",
            "CHRONARY-API-KEY": "c",
            "CHRONARY-AGENT-ID": "a",
            "CHRONARY-CALENDAR-ID": "cal",
        }
        mock_client = self._make_client(available)
        with patch.object(sidekick_secrets, "_build_client", return_value=mock_client):
            result = sidekick_secrets.pull("https://example.vault.azure.net/")
        assert result["TELEGRAM_BOT_TOKEN"] == "t"
        assert result["CHRONARY_API_KEY"] == "c"
        # Optional secrets that aren't in the vault are silently absent.
        assert "ANTHROPIC_API_KEY" not in result

    def test_raises_when_required_secret_missing(self) -> None:
        # Only optional ones are present — the four required ones are gone.
        mock_client = self._make_client({"ANTHROPIC-API-KEY": "a"})
        with patch.object(sidekick_secrets, "_build_client", return_value=mock_client):
            with pytest.raises(SystemExit, match="Required Sidekick secrets are missing"):
                sidekick_secrets.pull("https://example.vault.azure.net/")


class TestCliPullFormats:
    def _patch_pull(self, secrets: dict[str, str]):
        return patch.object(sidekick_secrets, "pull", return_value=secrets)

    def test_env_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._patch_pull({"FOO": "bar", "BAZ": "qux"}):
            rc = sidekick_secrets.main(
                ["--vault-url", "https://x.vault.azure.net/", "pull", "--format", "env"]
            )
        assert rc == 0
        out = capsys.readouterr().out
        assert "FOO=bar" in out
        assert "BAZ=qux" in out

    def test_ps1_format_escapes_single_quotes(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._patch_pull({"WITH_QUOTE": "ab'cd"}):
            rc = sidekick_secrets.main(
                ["--vault-url", "https://x.vault.azure.net/", "pull", "--format", "ps1"]
            )
        assert rc == 0
        out = capsys.readouterr().out.strip()
        # PowerShell single-quoted strings escape ' as ''.
        assert out == "$env:WITH_QUOTE = 'ab''cd'"

    def test_json_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._patch_pull({"A": "1"}):
            rc = sidekick_secrets.main(
                ["--vault-url", "https://x.vault.azure.net/", "pull", "--format", "json"]
            )
        assert rc == 0
        out = capsys.readouterr().out
        assert '"A": "1"' in out


class TestCliVaultUrlRequired:
    def test_errors_when_no_vault_url_and_no_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_KEYVAULT_URL", raising=False)
        with pytest.raises(SystemExit):
            sidekick_secrets.main(["list"])

    def test_picks_up_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_KEYVAULT_URL", "https://from-env.vault.azure.net/")
        with patch.object(sidekick_secrets, "list_kv", return_value=[]) as mock_list:
            # Re-import is unnecessary because the default is read at parse time
            # inside main(), not at import time.
            rc = sidekick_secrets.main(["list"])
        assert rc == 0
        mock_list.assert_called_once_with("https://from-env.vault.azure.net/")
