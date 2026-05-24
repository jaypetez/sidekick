"""Shared helpers for managing Sidekick secrets in Azure Key Vault.

This module is the single source of truth for:
  * which env vars Sidekick treats as "secrets",
  * how each env var maps to a Key Vault secret name (Key Vault disallows
    underscores, so ``CHRONARY_API_KEY`` becomes ``CHRONARY-API-KEY``),
  * which secrets are required vs. optional so the wrapper can fail loud
    when the bot would have no chance of starting.

The companion PowerShell / Bash wrappers (``scripts/run-with-kv.ps1``,
``scripts/run-with-kv.sh``) and the uploader (``scripts/secrets-push.ps1``)
delegate to this module so behaviour stays consistent across platforms.

Usage:
    python -m scripts.sidekick_secrets pull --vault-url https://my-kv.vault.azure.net/
    python -m scripts.sidekick_secrets push --vault-url https://my-kv.vault.azure.net/ --env-file .env
    python -m scripts.sidekick_secrets list  --vault-url https://my-kv.vault.azure.net/

Authentication uses ``azure.identity.DefaultAzureCredential``, which picks
up an existing ``az login`` session on developer machines and Managed
Identity in Azure-hosted environments. No service principal is required
for local dev once you've run ``az login``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from azure.keyvault.secrets import SecretClient


@dataclass(frozen=True)
class SecretSpec:
    """Maps a Sidekick env var to its Key Vault secret name."""

    env_var: str
    required: bool
    description: str

    @property
    def kv_name(self) -> str:
        # Key Vault secret names accept only [A-Za-z0-9-]; collapse underscores.
        return self.env_var.replace("_", "-")


# Edit this list when Sidekick gains/loses a secret-bearing env var.
# Non-secret config (TIMEZONE, OLLAMA_MODEL, etc.) deliberately stays in
# the .env file — only true secrets belong in Key Vault.
SECRET_SPECS: tuple[SecretSpec, ...] = (
    SecretSpec("TELEGRAM_BOT_TOKEN", required=True, description="Telegram BotFather token"),
    SecretSpec("CHRONARY_API_KEY", required=True, description="Chronary agent API key"),
    SecretSpec(
        "CHRONARY_AGENT_ID", required=True, description="Chronary agent id (set by sidekick-init)"
    ),
    SecretSpec(
        "CHRONARY_CALENDAR_ID",
        required=True,
        description="Chronary calendar id (set by sidekick-init)",
    ),
    SecretSpec(
        "ANTHROPIC_API_KEY",
        required=False,
        description="Anthropic key (required when LLM_PROVIDER=anthropic)",
    ),
    SecretSpec("SLACK_BOT_TOKEN", required=False, description="Slack bot token (optional adapter)"),
    SecretSpec(
        "SLACK_APP_TOKEN", required=False, description="Slack app-level token (optional adapter)"
    ),
    SecretSpec(
        "SIDEKICK_WEB_AUTH_TOKEN",
        required=False,
        description="Dashboard bearer token (required for non-loopback bind)",
    ),
    SecretSpec(
        "SIDEKICK_WEB_SESSION_SECRET",
        required=False,
        description="Dashboard session-cookie signing key (auto-generated if unset)",
    ),
)


def _build_client(vault_url: str) -> SecretClient:
    """Construct a Key Vault SecretClient using DefaultAzureCredential."""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "Missing azure SDK packages. Install with:\n"
            "    pip install azure-identity azure-keyvault-secrets"
        ) from exc

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    return SecretClient(vault_url=vault_url, credential=credential)


def pull(vault_url: str, *, skip_missing_optional: bool = True) -> dict[str, str]:
    """Fetch every Sidekick secret from Key Vault and return as a dict.

    Required secrets that are missing raise ``SystemExit``.  Optional
    secrets that are missing are silently skipped (so adapters the user
    hasn't enabled don't force them to upload empty placeholders).
    """
    from azure.core.exceptions import ResourceNotFoundError

    client = _build_client(vault_url)
    out: dict[str, str] = {}
    missing_required: list[str] = []

    for spec in SECRET_SPECS:
        try:
            out[spec.env_var] = client.get_secret(spec.kv_name).value or ""
        except ResourceNotFoundError:
            if spec.required:
                missing_required.append(spec.env_var)
            elif not skip_missing_optional:
                out[spec.env_var] = ""

    if missing_required:
        raise SystemExit(
            "Required Sidekick secrets are missing from the vault:\n  - "
            + "\n  - ".join(missing_required)
            + f"\nUpload them first with:\n    python -m scripts.sidekick_secrets push --vault-url {vault_url} --env-file .env"
        )
    return out


def push(vault_url: str, env_file: Path) -> list[str]:
    """Upload every known-secret env var found in ``env_file`` to Key Vault.

    Returns the list of secret names written. Skips blank values and
    placeholder values (``your_*_here``, ``chr_ak_your_*``, ``agt_replace_after_init``,
    ``cal_replace_after_init``, ``xoxb-your-*``, ``xapp-your-*``) so we
    never overwrite real vault entries with example data.
    """
    pairs = _parse_dotenv(env_file)
    client = _build_client(vault_url)
    written: list[str] = []

    placeholder_prefixes = (
        "your_",
        "chr_ak_your",
        "agt_replace_after_init",
        "cal_replace_after_init",
        "xoxb-your-",
        "xapp-your-",
    )
    known_envs = {s.env_var: s for s in SECRET_SPECS}

    for env_var, value in pairs.items():
        spec = known_envs.get(env_var)
        if spec is None:
            continue
        if not value or value.startswith(placeholder_prefixes):
            print(f"  skip {env_var} (blank or placeholder)", file=sys.stderr)
            continue
        client.set_secret(spec.kv_name, value)
        written.append(spec.kv_name)
        print(f"  wrote {spec.kv_name}", file=sys.stderr)

    return written


def list_kv(vault_url: str) -> list[dict[str, str | None]]:
    """List every Sidekick-relevant secret already in the vault."""
    client = _build_client(vault_url)
    known = {s.kv_name: s.env_var for s in SECRET_SPECS}
    rows: list[dict[str, str | None]] = []
    for prop in client.list_properties_of_secrets():
        if prop.name in known:
            rows.append(
                {
                    "kv_name": prop.name,
                    "env_var": known[prop.name],
                    "updated_on": prop.updated_on.isoformat() if prop.updated_on else None,
                    "enabled": str(prop.enabled),
                }
            )
    return rows


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE per line, ignores comments and blanks.

    Strips surrounding single/double quotes from values. Does not handle
    multi-line values or escape sequences — Sidekick secrets are all
    single-line tokens so the simple parser is sufficient.
    """
    out: dict[str, str] = {}
    if not path.exists():
        raise SystemExit(f"Env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        out[key] = value
    return out


def _cmd_pull(args: argparse.Namespace) -> int:
    secrets = pull(args.vault_url, skip_missing_optional=True)
    if args.format == "env":
        for env_var, value in secrets.items():
            print(f"{env_var}={value}")
    elif args.format == "ps1":
        # PowerShell session-scope assignments; the wrapper script dot-sources this.
        for env_var, value in secrets.items():
            escaped = value.replace("'", "''")
            print(f"$env:{env_var} = '{escaped}'")
    elif args.format == "json":
        print(json.dumps(secrets, indent=2))
    return 0


def _cmd_push(args: argparse.Namespace) -> int:
    written = push(args.vault_url, Path(args.env_file))
    print(f"\nWrote {len(written)} secret(s) to {args.vault_url}", file=sys.stderr)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    rows = list_kv(args.vault_url)
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        if not rows:
            print("(no Sidekick secrets found in this vault)")
            return 0
        widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in rows[0]}
        header = "  ".join(k.ljust(widths[k]) for k in rows[0])
        print(header)
        print("  ".join("-" * widths[k] for k in rows[0]))
        for row in rows:
            print("  ".join(str(row.get(k, "")).ljust(widths[k]) for k in rows[0]))
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Sidekick secrets in Azure Key Vault")
    parser.add_argument(
        "--vault-url",
        default=os.environ.get("AZURE_KEYVAULT_URL"),
        help="Key Vault URL, e.g. https://my-kv.vault.azure.net/ (or set AZURE_KEYVAULT_URL).",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull", help="Fetch all Sidekick secrets from the vault.")
    p_pull.add_argument("--format", choices=("env", "ps1", "json"), default="env")
    p_pull.set_defaults(func=_cmd_pull)

    p_push = sub.add_parser("push", help="Upload secrets from a .env file to the vault.")
    p_push.add_argument("--env-file", default=".env")
    p_push.set_defaults(func=_cmd_push)

    p_list = sub.add_parser("list", help="List Sidekick secrets present in the vault.")
    p_list.add_argument("--format", choices=("table", "json"), default="table")
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.vault_url:
        parser.error("--vault-url is required (or set the AZURE_KEYVAULT_URL env var).")
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
