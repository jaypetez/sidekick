#!/usr/bin/env bash
# Pull Sidekick secrets from Azure Key Vault into the current shell as
# environment variables, then exec a command (default: docker compose up).
#
# Linux/macOS twin of scripts/run-with-kv.ps1. Uses DefaultAzureCredential
# (i.e. `az login`) under the hood.
#
# Usage:
#   AZURE_KEYVAULT_URL=https://my-kv.vault.azure.net/ ./scripts/run-with-kv.sh
#   ./scripts/run-with-kv.sh https://my-kv.vault.azure.net/ -- sidekick

set -euo pipefail

VAULT_URL="${AZURE_KEYVAULT_URL:-}"
if [[ "${1:-}" == https://* ]]; then
    VAULT_URL="$1"
    shift
fi
if [[ "${1:-}" == "--" ]]; then
    shift
fi
if [[ -z "$VAULT_URL" ]]; then
    echo "ERROR: vault URL required. Pass as first arg or set AZURE_KEYVAULT_URL." >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "Pulling Sidekick secrets from $VAULT_URL ..." >&2

# Pull as `KEY=value` lines and export them. `set -a` causes every
# subsequent assignment to be auto-exported; `set +a` turns it off again.
TMP_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV"' EXIT

python -m scripts.sidekick_secrets --vault-url "$VAULT_URL" pull --format env > "$TMP_ENV"

set -a
# shellcheck disable=SC1090
source "$TMP_ENV"
set +a

COUNT=$(wc -l < "$TMP_ENV" | tr -d ' ')
echo "Loaded $COUNT secret(s) into the current session." >&2

if [[ $# -eq 0 ]]; then
    set -- docker compose --profile ollama up -d
fi
echo "Running: $*" >&2
echo "" >&2
exec "$@"
