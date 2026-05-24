<#
.SYNOPSIS
    One-time bulk upload of Sidekick secrets from a .env file to Azure Key Vault.

.DESCRIPTION
    Wraps `python -m scripts.sidekick_secrets push`. Uses DefaultAzureCredential,
    which picks up your `az login` session automatically. Run this once per
    machine (or whenever you rotate a secret).

.PARAMETER VaultUrl
    The vault URL, e.g. https://my-kv.vault.azure.net/. Falls back to the
    AZURE_KEYVAULT_URL env var.

.PARAMETER EnvFile
    Path to the source .env file. Defaults to .env in the repo root.

.EXAMPLE
    .\scripts\secrets-push.ps1 -VaultUrl https://my-kv.vault.azure.net/

.EXAMPLE
    $env:AZURE_KEYVAULT_URL = 'https://my-kv.vault.azure.net/'
    .\scripts\secrets-push.ps1
#>

[CmdletBinding()]
param(
    [string]$VaultUrl = $env:AZURE_KEYVAULT_URL,
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = 'Stop'

if (-not $VaultUrl) {
    throw "VaultUrl is required. Pass -VaultUrl or set `$env:AZURE_KEYVAULT_URL."
}

# Resolve repo root from this script's location so it works no matter where you cd from.
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot $EnvFile))) {
    throw "Env file not found: $(Join-Path $RepoRoot $EnvFile)"
}

Push-Location $RepoRoot
try {
    Write-Host "Uploading secrets from $EnvFile to $VaultUrl ..." -ForegroundColor Cyan
    & python -m scripts.sidekick_secrets --vault-url $VaultUrl push --env-file $EnvFile
    if ($LASTEXITCODE -ne 0) {
        throw "secrets-push failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
