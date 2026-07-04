#!/usr/bin/env bash
# Namma Agent — Cognee memory setup (Linux / macOS / Git-Bash).
# One command to make Cognee — Namma's memory — work on a fresh machine.
# Cognee runs FULLY CONTAINERIZED — it adds NO Python dependencies to Namma.
# The only prerequisite is Docker. See README.md + docs/COGNEE.md.
#
#   Run from the project root:  bash scripts/setup_cognee.sh
#   SKIP_LOCAL_LLM=1 bash scripts/setup_cognee.sh   # skip the 4.7 GB local model
#                                                   # (if you'll use a cloud LLM)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Namma Agent · Cognee setup =="

if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running. Start Docker and re-run this script." >&2
  exit 1
fi

# The compose file pins the network name to agi_default so the cognee container
# can always join it, regardless of this folder's name.
echo "-> Starting Ollama container..."
docker compose -f docker-compose.cognee.yml up -d

echo "-> Pulling embedding model (nomic-embed-text, ~275 MB)..."
docker exec namma-cognee-ollama ollama pull nomic-embed-text
if [ "${SKIP_LOCAL_LLM:-0}" != "1" ]; then
  echo "-> Pulling local extraction model (qwen2.5:7b, ~4.7 GB)..."
  echo "   (skip with SKIP_LOCAL_LLM=1 if you use a cloud LLM instead)"
  docker exec namma-cognee-ollama ollama pull qwen2.5:7b
fi

echo "-> Pulling Cognee MCP image (cognee/cognee-mcp:main, large)..."
docker pull cognee/cognee-mcp:main

if [ ! -f .env.cognee ]; then
  cp .env.cognee.example .env.cognee
  echo "-> Created .env.cognee from the example (fully local, key-free)."
fi

# PERSISTENCE: create the cognee-data volume + pre-create its dirs with write perms.
# The volume is root-owned by default but Cognee runs non-root, so without this it
# can't write its DBs there and memory would reset on every restart.
echo "-> Preparing the cognee-data volume (persistent memory)..."
docker volume create cognee-data >/dev/null
docker run --rm -v cognee-data:/cognee-data busybox sh -c \
  "mkdir -p /cognee-data/system /cognee-data/data /cognee-data/cache && chmod -R 777 /cognee-data"

cat <<'EOF'

Done. Now start Namma Agent and click ONE button:

  Settings -> MCP -> Cognee -> "Register Cognee server"

It connects in ~30s. To use a cloud LLM for faster graph building, pick a
preset under "Models & embeddings" in the same tab. See docs/COGNEE.md.
EOF
