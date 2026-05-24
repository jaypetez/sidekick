# Storing Sidekick Secrets in Azure Key Vault

This page covers the **recommended** secret-storage workflow for operators
who already have an Azure subscription. If you want something simpler (no
cloud round-trip), see the "Alternatives" section at the bottom — the
shipped `.env` flow is still fully supported.

## What this gives you

- **No plaintext `.env` with live tokens** on the host. Your `.env` shrinks
  to non-secret config (`TIMEZONE`, `OLLAMA_MODEL`, `SIDEKICK_WEB_HOST`, …).
- **Rotation in one place**: change a value in Key Vault, restart the
  container, you're done.
- **Audit trail**: Key Vault logs every `Get`/`Set` against the secret
  (enable diagnostic settings to your Log Analytics workspace).
- **Containers stay clean**: the Azure SDK and your `az` credentials live
  on the host. The wrapper extracts secrets to env vars, then exec's
  `docker compose` — the container only ever sees env vars, never the
  vault URL or your tenant.

## Prerequisites

1. **Azure CLI** signed in to the tenant that owns the vault:
   ```powershell
   az login
   az account set --subscription "<SUBSCRIPTION_NAME_OR_ID>"
   ```
2. **A Key Vault in RBAC mode** (the default for new vaults). If yours is
   in legacy access-policy mode, switch it:
   ```powershell
   az keyvault update --name <your-vault> --enable-rbac-authorization true
   ```
3. **Role assignments on yourself.** The shipped scripts read and write
   secrets, so the user identity needs:
   - **Key Vault Secrets Officer** — to push (run `secrets-push.ps1`).
   - **Key Vault Secrets User** — to pull (run `run-with-kv.ps1`).
   Both can be added in one shot:
   ```powershell
   $me = (az ad signed-in-user show --query id -o tsv)
   $vaultId = (az keyvault show --name <your-vault> --query id -o tsv)
   az role assignment create --assignee $me --role "Key Vault Secrets Officer" --scope $vaultId
   az role assignment create --assignee $me --role "Key Vault Secrets User"    --scope $vaultId
   ```
4. **Python SDKs** (already a dev dependency on a developer box, but if
   you're on a fresh machine):
   ```powershell
   pip install azure-identity azure-keyvault-secrets
   ```

## One-time setup: push secrets from `.env` to Key Vault

Fill out a `.env` (or `.env.local`) the way you normally would, then run:

```powershell
.\scripts\secrets-push.ps1 -VaultUrl https://<your-vault>.vault.azure.net/
```

The uploader walks the known-secret list, skips blank values and example
placeholders, and writes each non-empty value to the vault. Underscores
in env var names become hyphens in vault names (Key Vault disallows `_`),
so `CHRONARY_API_KEY` becomes the vault secret `CHRONARY-API-KEY`.

**After uploading, you can delete the secrets from `.env` and keep only
non-secret config.** Recommended trimmed `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
TIMEZONE=America/Chicago
MORNING_REMINDER_TIME=07:30
PRE_EVENT_REMINDER_MINUTES=30
SIDEKICK_WEB_ENABLED=true
SIDEKICK_WEB_HOST=0.0.0.0
SIDEKICK_WEB_PORT=8080
```

## Daily use: run the bot

```powershell
$env:AZURE_KEYVAULT_URL = 'https://<your-vault>.vault.azure.net/'
.\scripts\run-with-kv.ps1
```

By default the wrapper runs `docker compose --profile ollama up -d`. Pass
`-Command` to run anything else with the same secrets loaded:

```powershell
.\scripts\run-with-kv.ps1 -Command 'sidekick'                  # run the bot directly (no Docker)
.\scripts\run-with-kv.ps1 -Command 'pwsh -NoExit'              # spawn a sub-shell pre-loaded
.\scripts\run-with-kv.ps1 -Command 'pytest tests/test_storage_tasks.py'
```

On Linux/macOS, use the bash twin:

```bash
AZURE_KEYVAULT_URL=https://<your-vault>.vault.azure.net/ ./scripts/run-with-kv.sh
./scripts/run-with-kv.sh https://<your-vault>.vault.azure.net/ -- sidekick
```

## Listing and rotating

```powershell
# Inspect what's currently in the vault
python -m scripts.sidekick_secrets --vault-url $env:AZURE_KEYVAULT_URL list

# Rotate a single secret without re-uploading the whole .env
az keyvault secret set --vault-name <your-vault> --name CHRONARY-API-KEY --value "<new value>"
docker compose restart sidekick  # picks up the new value on the next pull
```

## Threat model

| Threat | Protected by |
| --- | --- |
| Accidental `git commit` of `.env` | `.env` is gitignored and now empty of secrets |
| Casual filesystem snoop, laptop theft (powered off, BitLocker enabled) | Disk encryption + the vault never being on disk |
| Other user accounts on the same host | DPAPI scopes `az login` to your Windows user |
| Malware running as your Windows user | **Not protected** — it can call `az` too |
| Compromised cloud tenant / Azure breach | **Not protected** — out of scope for self-hosting |

For higher assurance, scope the role assignment to a **dedicated
identity** (e.g., a managed identity if you run Sidekick in Azure, or a
service principal with certificate auth on-prem) instead of your personal
login.

## Alternatives (still supported)

| Approach | Best for | Trade-offs |
| --- | --- | --- |
| Plain `.env` with `chmod 0600` | Solo dev, no cloud | Plaintext on disk; rotation is manual |
| Python `keyring` + Windows Credential Manager | Solo dev, no cloud, but want OS-encrypted | Same DPAPI scope as this, no audit log |
| 1Password CLI (`op run`) | Teams sharing secrets | Paid; introduces a vendor dep |
| SOPS + age | Committing encrypted secrets to git | Heaviest setup; great for multi-machine sync |

If you want one of these, open an issue — the `scripts/sidekick_secrets.py`
module is small enough that a `--backend keyring` or `--backend op` flag
is a one-evening port.

## Troubleshooting

- **`DefaultAzureCredential failed`** — re-run `az login` and confirm
  `az account show` returns the right tenant.
- **`(Forbidden) The user does not have secrets get permission`** — your
  role assignment is missing. Re-run the `az role assignment create`
  block in the Prerequisites.
- **`(SecretNotFound)`** — the secret hasn't been uploaded yet. Run
  `secrets-push.ps1` once, or `az keyvault secret set` it directly.
- **Docker can't see the secrets** — make sure you're invoking
  `docker compose` through the wrapper, not bare. The wrapper exports the
  env vars into the shell that runs compose; compose then inherits and
  passes them into the container.
