param(
    [string]$EnvFile = "backend/.env",
    [string]$ComposeFile = "backend/docker-compose.yml",
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot/_lib.ps1"

function Ensure-EnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-Path -LiteralPath $Path) { return }
    $example = Join-Path (Split-Path -Parent $Path) ".env.example"
    if (!(Test-Path -LiteralPath $example)) {
        throw ("Missing {0} and example {1}" -f $Path, $example)
    }
    Copy-Item -LiteralPath $example -Destination $Path -Force
}

function Compose-Command {
    param([Parameter(Mandatory = $true)][string]$Args)
    return ("docker-compose -f ""{0}"" --env-file ""{1}"" {2}" -f $ComposeFile, $EnvFile, $Args)
}

$script:failed = $false
$script:softFail = $false
$expectedServices = @(
    "postgres",
    "redis",
    "minio",
    "gateway-service",
    "identity-service",
    "knowledge-service",
    "ai-service",
    "worker-service",
    "ops-service"
)

try {
    Invoke-Checked -Label "Ensure env file exists" -Command {
        Ensure-EnvFile -Path $EnvFile
        if (!(Test-Path -LiteralPath $ComposeFile)) {
            throw ("Compose file not found: {0}" -f $ComposeFile)
        }
    } | Out-Null

    Invoke-Checked -Label "Check docker (engine reachable)" -Command {
        if (!(Test-CommandExists -Name "docker")) { throw "docker not found in PATH" }
        & docker version | Out-Null
    } | Out-Null

    Invoke-Checked -Label "Select usable DOCKER_REGISTRY (mainland-friendly)" -Command {
        & powershell -NoLogo -ExecutionPolicy Bypass -File "$PSScriptRoot/select_docker_registry.ps1" -EnvFile $EnvFile
        if ($LASTEXITCODE -ne 0) { throw "select_docker_registry failed" }
    } | Out-Null

    Invoke-Checked -Label "Check docker-compose" -Command {
        if (!(Test-CommandExists -Name "docker-compose")) { throw "docker-compose not found in PATH" }
        & docker-compose version | Out-Null
    } | Out-Null

    Invoke-Checked -Label "Validate compose config" -Command {
        & docker-compose -f $ComposeFile --env-file $EnvFile config 1>$null
    } | Out-Null

    if ($PreflightOnly) {
        Write-Host ""
        Write-Host "Preflight-only checks completed."
        exit 0
    }

    if (-not (Invoke-Checked -Label "Show stack status (docker-compose ps)" -Command {
        & docker-compose -f $ComposeFile --env-file $EnvFile ps

        $missing = @()
        foreach ($svc in $expectedServices) {
            $cid = (& docker-compose -f $ComposeFile --env-file $EnvFile ps -q $svc) | Select-Object -First 1
            if (-not $cid) { $missing += $svc; continue }
            $state = (& docker inspect -f "{{.State.Status}}" $cid 2>$null)
            if ($state -ne "running") { $missing += $svc }
        }
        if ($missing.Count -gt 0) {
            throw ("Services not running: {0}" -f ($missing -join ", "))
        }
    } -ContinueOnError)) { $script:softFail = $true }

    if (-not (Invoke-Checked -Label "Health checks (HTTP)" -Command {
        $endpoints = @(
            "http://localhost:8080/healthz",
            "http://localhost:8081/healthz",
            "http://localhost:8082/healthz",
            "http://localhost:8083/healthz",
            "http://localhost:8084/healthz"
        )
        foreach ($u in $endpoints) {
            Write-Host ("  GET {0}" -f $u)
            try {
                Invoke-RestMethod -Method Get -Uri $u -TimeoutSec 3 | Out-Null
            } catch {
                throw ("Health check failed: {0}" -f $u)
            }
        }
    } -ContinueOnError)) { $script:softFail = $true }

    if (-not (Invoke-Checked -Label "Knowledge UI + ingest summary (admin)" -Command {
        Invoke-RestMethod -Method Get -Uri "http://localhost:8082/ui/knowledge" -TimeoutSec 3 | Out-Null

        $headers = @{
            "X-Tenant-Id" = "11111111-1111-1111-1111-111111111111"
            "X-User-Id"   = "22222222-2222-2222-2222-222222222222"
            "X-Role"      = "admin"
        }
        Invoke-RestMethod -Method Get -Uri "http://localhost:8082/v1/admin/ingest/summary" -Headers $headers -TimeoutSec 3 | Out-Null
    } -ContinueOnError)) { $script:softFail = $true }

    Write-Host ""
    if ($script:softFail) {
        Write-Host "Doctor completed with failures. See FAIL steps above."
        Write-Host "Suggested fix: run `just up` to start the full stack, then re-run `just doctor`."
        exit 2
    }
    Write-Host "Doctor checks completed."
    exit 0
} catch {
    Write-Host ""
    Write-Host ("Doctor failed: {0}" -f $_.Exception.Message)
    exit 1
}
