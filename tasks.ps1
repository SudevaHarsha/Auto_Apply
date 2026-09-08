param([string]$Target = "test")

$ErrorActionPreference = "Stop"

function Load-Env {
    $envFile = Join-Path (Get-Location) ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                $kv = $line.Split('=', 2)
                Set-Item -Path ("env:" + $kv[0]) -Value $kv[1]
            }
        }
    }
}

Load-Env

# Prefer the project venv when present (global `python` may be a bare shim).
$script:Py = "python"
if (Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\python.exe")) {
    $script:Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}

function Wait-Db {
    $compose = "infra/docker-compose.dev.yml"
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        & docker compose -f $compose exec -T db pg_isready -U autoapply 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { Write-Error "db did not become ready" }
}

switch ($Target) {
    "lint" { & $Py -m ruff check .; & $Py -m mypy backend }
    "test" { & $Py -m pytest tests/units }
    "dev-up" { & docker compose -f infra/docker-compose.dev.yml up -d }
    "dev-down" { & docker compose -f infra/docker-compose.dev.yml down }
    "db-reset" {
        & docker compose -f infra/docker-compose.dev.yml down -v
        & docker compose -f infra/docker-compose.dev.yml up -d db
        Wait-Db
    }
    "migrate" { & $Py db/run_migrations.py }
    "parity" {
        & docker compose -f infra/docker-compose.dev.yml down -v
        & docker compose -f infra/docker-compose.dev.yml up -d db
        Wait-Db
        & $Py db/run_migrations.py
        & $Py tests/parity/schema_parity.py
        & $Py -m pytest tests/parity
        & docker compose -f infra/docker-compose.dev.yml down
    }
    "test-integration" {
        & docker compose -f infra/docker-compose.dev.yml down -v
        & docker compose -f infra/docker-compose.dev.yml up -d db
        Wait-Db
        & $Py db/run_migrations.py
        & $Py -m pytest tests/integration
        & docker compose -f infra/docker-compose.dev.yml down
    }
    "test-e2e" { & $Py -m pytest tests/e2e }
    default { Write-Error "Unknown target: $Target" }
}