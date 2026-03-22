param(
    [string]$BaseUrl = "http://localhost:8082",
    [int]$TimeoutSec = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Pass([string]$Msg) {
    Write-Host ("PASS: {0}" -f $Msg)
}

function Write-Fail([string]$Msg) {
    Write-Host ("FAIL: {0}" -f $Msg)
}

function New-DefaultHeaders {
    return @{
        "X-Tenant-Id" = "11111111-1111-1111-1111-111111111111"
        "X-User-Id"   = "22222222-2222-2222-2222-222222222222"
        "X-Role"      = "admin"
    }
}

function Invoke-Json {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][hashtable]$Headers,
        [Parameter(Mandatory = $false)][object]$Body
    )

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Url -Headers $Headers -TimeoutSec 10
    }
    $json = $Body | ConvertTo-Json -Depth 10
    return Invoke-RestMethod -Method $Method -Uri $Url -Headers $Headers -ContentType "application/json" -Body $json -TimeoutSec 10
}

function Normalize-BaseUrl([string]$Url) {
    $u = $Url.Trim()
    if ($u.EndsWith("/")) { $u = $u.Substring(0, $u.Length - 1) }
    return $u
}

try {
    $BaseUrl = Normalize-BaseUrl $BaseUrl
    if ($TimeoutSec -lt 5) { throw "TimeoutSec must be >= 5" }

    $headers = New-DefaultHeaders
    $nonce = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $title = "Smoke Doc $nonce"
    $content = "smoke test ${nonce}: This document should be chunked and indexed into pgvector. keyword=$nonce"

    Write-Host ("BaseUrl={0} TimeoutSec={1}" -f $BaseUrl, $TimeoutSec)
    Write-Host ("Create document title='{0}'" -f $title)

    $create = Invoke-Json -Method "POST" -Url ("{0}/v1/documents" -f $BaseUrl) -Headers $headers -Body @{
        title = $title
        source_type = "upload"
        content = $content
    }

    $docId = $create.document_id
    if (-not $docId) { throw "Create document response missing document_id" }
    Write-Pass ("create queued document_id={0}" -f $docId)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $status = ""
    while ($true) {
        if ((Get-Date) -gt $deadline) {
            Write-Fail ("document not ready within timeout (last_status='{0}')" -f $status)
            exit 1
        }

        $doc = Invoke-Json -Method "GET" -Url ("{0}/v1/documents/{1}" -f $BaseUrl, $docId) -Headers $headers
        $status = [string]$doc.status
        if ($status -eq "ready") {
            Write-Pass "document status=ready"
            break
        }
        if ($status -eq "failed") {
            Write-Fail "document status=failed (worker ingest failed)"
            exit 1
        }

        Write-Host ("WAIT: status={0}" -f $status)
        Start-Sleep -Seconds 1
    }

    Write-Host "Run RAG search..."
    $search = Invoke-Json -Method "POST" -Url ("{0}/v1/rag/search" -f $BaseUrl) -Headers $headers -Body @{
        query = $nonce
        top_k = 5
    }

    $hits = @()
    if ($search -and $search.hits) { $hits = @($search.hits) }
    if ($hits.Count -lt 1) {
        Write-Fail "rag search returned 0 hits"
        exit 1
    }

    Write-Pass ("rag search hits={0}" -f $hits.Count)
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}
