<#
.SYNOPSIS
    Pull Sidekick secrets from Azure Key Vault into the current PowerShell
    session as env vars, then execute a command (default: docker compose up).

.DESCRIPTION
    Secrets exist only in process memory and the spawned child process —
    nothing is written to disk. Combine with a stripped-down `.env` that
    holds only non-secret config (TIMEZONE, OLLAMA_MODEL, etc.) and
    docker-compose will see the union of both.

.PARAMETER VaultUrl
    The vault URL, e.g. https://my-kv.vault.azure.net/. Falls back to the
    AZURE_KEYVAULT_URL env var.

.PARAMETER Command
    Command to exec after the env vars are set. Defaults to
    `docker compose --profile ollama up -d`.

.EXAMPLE
    .\scripts\run-with-kv.ps1 -VaultUrl https://my-kv.vault.azure.net/

.EXAMPLE
    # Just open a sub-shell with the secrets loaded for interactive use:
    .\scripts\run-with-kv.ps1 -Command 'pwsh -NoExit'

.EXAMPLE
    # Run the bot directly (no Docker):
    .\scripts\run-with-kv.ps1 -Command 'sidekick'
#>

[CmdletBinding()]
param(
    [string]$VaultUrl = $env:AZURE_KEYVAULT_URL,
    [string]$Command = 'docker compose --profile ollama up -d'
)

$ErrorActionPreference = 'Stop'

if (-not $VaultUrl) {
    throw "VaultUrl is required. Pass -VaultUrl or set `$env:AZURE_KEYVAULT_URL."
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    Write-Host "Pulling Sidekick secrets from $VaultUrl ..." -ForegroundColor Cyan

    # Capture the PowerShell-formatted assignments and dot-source them
    # into the current scope. The python module emits one `$env:KEY = '...'`
    # per line so this stays auditable.
    $assignments = & python -m scripts.sidekick_secrets --vault-url $VaultUrl pull --format ps1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to pull secrets (exit code $LASTEXITCODE)."
    }

    foreach ($line in $assignments) {
        if ($line.Trim()) {
            Invoke-Expression $line
        }
    }
    Write-Host "Loaded $($assignments.Count) secret(s) into the current session." -ForegroundColor Green
    Write-Host "Running: $Command" -ForegroundColor Cyan
    Write-Host ""

    # Use cmd /c so multi-word $Command strings (with their own args/flags)
    # parse exactly the same way the user typed them.
    & cmd /c $Command
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
