param([string]$Target = "test")

$ErrorActionPreference = "Stop"

function Load-Env {
    param([string]$File = ".env")
    $envFile = Join-Path (Get-Location) $File
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

function Load-TestEnv {
    if (Test-Path (Join-Path (Get-Location) ".env.test")) {
        Load-Env -File ".env.test"
    } else {
        Load-Env -File ".env.test.example"
    }
}

# Dev env by default; test targets call Load-TestEnv (overrides URLs to :5435).
Load-Env

# Prefer the project venv when present (global `python` may be a bare shim).
$script:Py = "python"
if (Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\python.exe")) {
    $script:Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}

function Wait-Db {
    param(
        [string]$ComposeFile = "infra/docker-compose.dev.yml",
        [string]$Service = "db"
    )
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        & docker compose -f $ComposeFile exec -T $Service pg_isready -U autoapply 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { Write-Error "$Service did not become ready" }
}

function Run-Parity {
    param(
        [string]$ComposeFile,
        [string]$DbService
    )
    Set-Item -Path env:PARITY_COMPOSE -Value $ComposeFile
    Set-Item -Path env:PARITY_DB_SERVICE -Value $DbService
    & $Py tests/parity/schema_parity.py
    & $Py -m pytest tests/parity
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
        Load-TestEnv
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.test.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db_test"
        & docker compose -f infra/docker-compose.test.yml down -v
        & docker compose -f infra/docker-compose.test.yml up -d db_test
        Wait-Db -ComposeFile "infra/docker-compose.test.yml" -Service "db_test"
        & $Py db/run_migrations.py
        Run-Parity -ComposeFile "infra/docker-compose.test.yml" -DbService "db_test"
        & docker compose -f infra/docker-compose.test.yml down -v
    }
    "parity-dev" {
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.dev.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db"
        & docker compose -f infra/docker-compose.dev.yml up -d db
        Wait-Db
        Run-Parity -ComposeFile "infra/docker-compose.dev.yml" -DbService "db"
    }
    "test-integration" {
        Load-TestEnv
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.test.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db_test"
        & docker compose -f infra/docker-compose.test.yml down -v
        & docker compose -f infra/docker-compose.test.yml up -d db_test
        Wait-Db -ComposeFile "infra/docker-compose.test.yml" -Service "db_test"
        & $Py db/run_migrations.py
        & $Py -m pytest tests/integration
        & docker compose -f infra/docker-compose.test.yml down -v
    }
    "test-e2e" { & $Py -m pytest tests/e2e }
    "test-env-up" {
        Load-TestEnv
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.test.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db_test"
        & docker compose -f infra/docker-compose.test.yml up -d db_test
        Wait-Db -ComposeFile "infra/docker-compose.test.yml" -Service "db_test"
        & $Py db/run_migrations.py
    }
    "test-env-down" { Load-TestEnv; & docker compose -f infra/docker-compose.test.yml down }
    default { Write-Error "Unknown target: $Target" }
}