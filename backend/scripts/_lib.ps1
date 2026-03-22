Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Read-DotEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    $vars = @{}
    if (!(Test-Path -LiteralPath $Path)) {
        return $vars
    }

    $lines = Get-Content -LiteralPath $Path -ErrorAction Stop
    foreach ($line in $lines) {
        $trim = $line.Trim()
        if ($trim.Length -eq 0) { continue }
        if ($trim.StartsWith("#")) { continue }
        $idx = $trim.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $trim.Substring(0, $idx).Trim()
        $val = $trim.Substring($idx + 1)
        $vars[$key] = $val
    }

    return $vars
}

function Write-DotEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Vars
    )

    $dir = Split-Path -Parent $Path
    if ($dir -and !(Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }

    # Keep a stable, readable ordering. Avoid BOM (PowerShell 5.1 default encodings are surprising).
    $keys = @($Vars.Keys | Sort-Object)
    $content = ($keys | ForEach-Object { "$_=$($Vars[$_])" }) -join "`n"
    $content = $content + "`n"

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $Path), $content, $utf8NoBom)
}

function Upsert-DotEnvLine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $dir = Split-Path -Parent $Path
    if ($dir -and !(Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }

    $content = ""
    if (Test-Path -LiteralPath $Path) {
        try {
            $content = Get-Content -LiteralPath $Path -Raw -Encoding utf8
        } catch {
            $content = Get-Content -LiteralPath $Path -Raw
        }
    }

    $newline = "`n"
    if ($content -match "`r`n") { $newline = "`r`n" }

    $escapedKey = [regex]::Escape($Key)
    $pattern = "(?m)^(?:$escapedKey)=.*$"
    $replacement = ("{0}={1}" -f $Key, $Value)
    if ($content -match $pattern) {
        $content = [regex]::Replace($content, $pattern, $replacement)
    } else {
        if ($content.Length -gt 0 -and -not ($content.EndsWith("`n") -or $content.EndsWith("`r`n"))) {
            $content = $content + $newline
        }
        $content = $content + $replacement + $newline
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    if (Test-Path -LiteralPath $Path) {
        [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $Path), $content, $utf8NoBom)
    } else {
        [System.IO.File]::WriteAllText($Path, $content, $utf8NoBom)
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [switch]$ContinueOnError
    )

    if (-not (Get-Variable -Name "__step" -Scope Script -ErrorAction SilentlyContinue)) {
        $script:__step = 0
    }
    $script:__step = [int]$script:__step + 1

    Write-Host ""
    Write-Host ("[{0}] {1}" -f $script:__step, $Label)
    try {
        # Ensure this variable exists under StrictMode even if the step doesn't run any native command.
        $global:LASTEXITCODE = 0
        & $Command
        if ($global:LASTEXITCODE -ne 0) {
            throw ("Command failed with exit code {0}" -f $global:LASTEXITCODE)
        }
        Write-Host "  OK"
        return $true
    } catch {
        Write-Host ("  FAIL: {0}" -f $_.Exception.Message)
        if ($ContinueOnError) { return $false }
        throw
    }
}

function Test-CommandExists {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}
