# Stop Apache Jena Fuseki started by start_triplestore.ps1.
#
# Usage:
#   .\scripts\stop_triplestore.ps1
#   . .\scripts\stop_triplestore.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
$ComposeFile = Join-Path $RepoRoot "docker-compose.fuseki.yml"

Write-Host "==> Stopping Fuseki..." -ForegroundColor Cyan
Push-Location $RepoRoot
try {
    docker compose -f $ComposeFile down
} finally {
    Pop-Location
}

Remove-Item Env:KG_SPARQL_QUERY_ENDPOINT -ErrorAction SilentlyContinue
Remove-Item Env:KG_SPARQL_UPDATE_ENDPOINT -ErrorAction SilentlyContinue
Remove-Item Env:KG_SPARQL_GSP_ENDPOINT -ErrorAction SilentlyContinue
Remove-Item Env:KG_SPARQL_USER -ErrorAction SilentlyContinue
Remove-Item Env:KG_SPARQL_PASSWORD -ErrorAction SilentlyContinue

Write-Host "==> Fuseki stopped. SPARQL env vars cleared from this process (if present)." -ForegroundColor Green
