param(
    [string]$EnvFile = "backend/.env",
    [string[]]$Candidates = @("docker.1panel.live", "docker.m.daocloud.io", "docker.io"),
    [switch]$SkipPull
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot/_lib.ps1"

function Get-ProbeImage {
    param([Parameter(Mandatory = $true)][string]$Registry)
    if ($Registry -eq "" -or $Registry -eq "docker.io") {
        return "library/python:3.11-slim"
    }
    return ("{0}/library/python:3.11-slim" -f $Registry)
}

function Get-ProbeImages {
    param(
        [Parameter(Mandatory = $true)][string]$Registry,
        [switch]$Minimal
    )
    $imgs = @(
        "library/python:3.11-slim",
        "library/redis:7.4-alpine",
        "pgvector/pgvector:pg16",
        "minio/minio:RELEASE.2025-02-28T09-55-16Z"
    )
    if ($Minimal) { $imgs = @("library/python:3.11-slim") }
    if ($Registry -eq "" -or $Registry -eq "docker.io") { return $imgs }
    return ($imgs | ForEach-Object { ("{0}/{1}" -f $Registry, $_) })
}

function Test-Registry {
    param(
        [Parameter(Mandatory = $true)][string]$Registry,
        [switch]$Minimal
    )

    $imgs = Get-ProbeImages -Registry $Registry -Minimal:$Minimal

    $first = $true
    foreach ($img in $imgs) {
        # Fast path: manifest inspect (no layer download).
        & docker manifest inspect $img 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) {
            $first = $false
            continue
        }

        # Only use a pull fallback for the first probe (keep this fast).
        if ($SkipPull -or -not $first) { return $false }
        & docker pull $img 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        $first = $false
    }

    return $true
}

if (!(Test-Path -LiteralPath $EnvFile)) {
    throw ("Env file not found: {0}" -f $EnvFile)
}

if (!(Test-CommandExists -Name "docker")) {
    throw "docker not found in PATH"
}

$vars = Read-DotEnv -Path $EnvFile
$current = ""
if ($vars.ContainsKey("DOCKER_REGISTRY")) {
    $current = $vars["DOCKER_REGISTRY"].Trim()
}

$try = @()
if ($current) { $try += $current }
$try += $Candidates

$selected = $null
foreach ($reg in $try | Select-Object -Unique) {
    Write-Host ("Probe registry: {0}" -f $reg)
    $ok = $false
    $minimal = $false
    if ($current -and ($reg -eq $current)) { $minimal = $true }
    try { $ok = Test-Registry -Registry $reg -Minimal:$minimal } catch { $ok = $false }
    if (-not $ok -and $minimal) {
        # Current registry: if the minimal probe fails, confirm with a full probe before switching.
        Write-Host ("  Minimal probe failed, retry full probe: {0}" -f $reg)
        try { $ok = Test-Registry -Registry $reg } catch { $ok = $false }
    }
    if ($ok) {
        $selected = $reg
        break
    }
    Write-Host ("  Not usable: {0}" -f $reg)
}

if (-not $selected) {
    throw ("No usable registry found. Tried: {0}" -f (($try | Select-Object -Unique) -join ", "))
}

Upsert-DotEnvLine -Path $EnvFile -Key "DOCKER_REGISTRY" -Value $selected
Write-Host ("Selected DOCKER_REGISTRY={0} (written to {1})" -f $selected, $EnvFile)
