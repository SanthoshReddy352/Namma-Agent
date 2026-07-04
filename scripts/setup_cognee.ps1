# Namma Agent — Cognee memory setup (Windows / PowerShell).
# One command to make Cognee — Namma's memory — work on a fresh machine.
# Cognee runs FULLY CONTAINERIZED — it adds NO Python dependencies to Namma.
# All this script needs is Docker Desktop. See README.md + docs/COGNEE.md.
#
#   Run from the project root:  powershell -ExecutionPolicy Bypass -File scripts/setup_cognee.ps1
#
#   -SkipLocalLLM  skip pulling the local extraction model (qwen2.5:7b, ~4.7 GB)
#                  — use this if you'll point Cognee at Groq/OpenAI/another cloud
#                  LLM in Settings → MCP → Cognee instead.

param([switch]$SkipLocalLLM)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Namma Agent · Cognee setup ==" -ForegroundColor Cyan

# 1. Docker must be running.
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Docker isn't running. Start Docker Desktop and re-run this script." -ForegroundColor Yellow
  exit 1
}

# 2. Start Ollama (free, local LLM + embedding server). Only container we run persistently.
#    The compose file pins the network name to agi_default so the cognee container
#    can always join it, regardless of this folder's name.
Write-Host "-> Starting Ollama container..." -ForegroundColor Green
docker compose -f docker-compose.cognee.yml up -d

# 3. Pull the models (idempotent — skips if already present).
Write-Host "-> Pulling embedding model (nomic-embed-text, ~275 MB)..." -ForegroundColor Green
docker exec namma-cognee-ollama ollama pull nomic-embed-text
if (-not $SkipLocalLLM) {
  Write-Host "-> Pulling local extraction model (qwen2.5:7b, ~4.7 GB)..." -ForegroundColor Green
  Write-Host "   (skip next time with -SkipLocalLLM if you use a cloud LLM instead)" -ForegroundColor DarkGray
  docker exec namma-cognee-ollama ollama pull qwen2.5:7b
}

# 4. Pull the Cognee MCP server image (first time only — it is large).
Write-Host "-> Pulling Cognee MCP image (cognee/cognee-mcp:main, large)..." -ForegroundColor Green
docker pull cognee/cognee-mcp:main

# 5. Ensure a local env file exists (defaults to the fully-local Ollama config).
if (-not (Test-Path ".env.cognee")) {
  Copy-Item ".env.cognee.example" ".env.cognee"
  Write-Host "-> Created .env.cognee from the example (fully local, key-free)." -ForegroundColor Green
}

# 6. PERSISTENCE: create the cognee-data volume and pre-create its dirs with write
# perms. The volume is root-owned by default but Cognee runs non-root, so without
# this it can't write its DBs there and memory would reset every restart.
Write-Host "-> Preparing the cognee-data volume (persistent memory)..." -ForegroundColor Green
docker volume create cognee-data | Out-Null
docker run --rm -v cognee-data:/cognee-data busybox sh -c "mkdir -p /cognee-data/system /cognee-data/data /cognee-data/cache && chmod -R 777 /cognee-data"

Write-Host ""
Write-Host "Done. Now start Namma Agent and click ONE button:" -ForegroundColor Cyan
Write-Host "  Settings -> MCP -> Cognee -> 'Register Cognee server'" -ForegroundColor Cyan
Write-Host "It connects in ~30s. To use a cloud LLM for faster graph building, pick a" -ForegroundColor DarkGray
Write-Host "preset under 'Models & embeddings' in the same tab. See docs/COGNEE.md." -ForegroundColor DarkGray
