[CmdletBinding()]
param(
    [switch]$KeepRunning,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "docker-compose.yml"
$BackendPort = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "8501" }

function Wait-HttpEndpoint {
    param(
        [Parameter(Mandatory)] [string]$Uri,
        [Parameter(Mandatory)] [string]$Name
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Uri -TimeoutSec 3 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                Write-Host "$Name is ready: $Uri"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "$Name did not become ready within $TimeoutSeconds seconds: $Uri"
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
    throw "Missing .env. Copy .env.example to .env and configure provider credentials first."
}

Push-Location $ProjectRoot
try {
    docker compose --file $ComposeFile config --quiet
    docker compose --file $ComposeFile build
    docker compose --file $ComposeFile up --detach --wait --wait-timeout $TimeoutSeconds

    Wait-HttpEndpoint -Uri "http://127.0.0.1:$BackendPort/api/live" -Name "Backend"
    Wait-HttpEndpoint -Uri "http://127.0.0.1:$FrontendPort/_stcore/health" -Name "Frontend"

    $healthJson = curl.exe --silent --show-error "http://127.0.0.1:$BackendPort/api/health"
    if ($LASTEXITCODE -ne 0) {
        throw "Backend readiness endpoint could not be read."
    }
    $health = $healthJson | ConvertFrom-Json
    if (-not $health.status -or -not $health.chroma -or -not $health.llm -or -not $health.embedding) {
        throw "Backend readiness response is missing required capability status."
    }

    docker compose --file $ComposeFile restart backend
    Wait-HttpEndpoint -Uri "http://127.0.0.1:$BackendPort/api/live" -Name "Restarted backend"

    Write-Host "Docker smoke test passed."
}
finally {
    if (-not $KeepRunning) {
        docker compose --file $ComposeFile down --remove-orphans
    }
    Pop-Location
}
