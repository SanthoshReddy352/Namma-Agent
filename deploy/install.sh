#!/usr/bin/env bash
# Namma Agent — one-line VPS installer (Ubuntu/Debian, Phase 6b).
#
#   curl -fsSL https://raw.githubusercontent.com/SanthoshReddy352/Namma-Agent/main/deploy/install.sh | sudo bash
#
# Sized for the 1 GB Oracle Always-Free E2.1.Micro but works on any apt box.
# What it does (idempotent — safe to re-run; it upgrades in place):
#   1. installs system packages (python3-venv, git, node for the UI build)
#   2. creates a 2 GB swap file if the box has < 2 GB RAM and no swap
#      (the 1 GB box's survival step — the UI build and busy days need it)
#   3. creates a 'namma' system user and clones/updates /opt/namma-agent
#   4. venv + python deps (core + telegram-ready; no GUI/desktop extras)
#   5. installs Ollama + the all-minilm embedding model (semantic memory recall)
#   6. builds the web UI (skipped when a prebuilt dist/ ships in the tree)
#   7. applies the server-lite config profile (only on first install)
#   8. generates an access token into .env (only if missing)
#   9. installs + starts the systemd service
#  10. prints the token and what to do next
#
# Flags:  --dry-run        print every step, change nothing
#         --no-swap        skip the swap step
#         --no-embeddings  skip Ollama + all-minilm (~350 MB on disk, ~150 MB
#                          resident); memory recall stays keyword-only
set -euo pipefail

REPO_URL="${NAMMA_REPO:-https://github.com/SanthoshReddy352/Namma-Agent.git}"
INSTALL_DIR="${NAMMA_INSTALL_DIR:-/opt/namma-agent}"
RUN_USER=namma
DRY=0
NOSWAP=0
NOEMBED=0
for a in "$@"; do
  case "$a" in
    --dry-run)       DRY=1 ;;
    --no-swap)       NOSWAP=1 ;;
    --no-embeddings) NOEMBED=1 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then echo "DRY: $*"; else "$@"; fi }

if [ "$DRY" = 0 ] && [ "$(id -u)" != 0 ]; then
  echo "Run me with sudo (or as root): sudo bash install.sh" >&2
  exit 1
fi

say "1/10 System packages"
run apt-get update -y
run apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip git ca-certificates curl

say "2/10 Swap (the 1 GB box's survival step)"
mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if [ "$NOSWAP" = 1 ]; then
  echo "skipped (--no-swap)"
elif swapon --show | grep -q .; then
  echo "swap already active — nothing to do"
elif [ "$mem_kb" -ge 2097152 ]; then
  echo "box has >= 2 GB RAM — no swap needed"
else
  run fallocate -l 2G /swapfile
  run chmod 600 /swapfile
  run mkswap /swapfile
  run swapon /swapfile
  if ! grep -q '^/swapfile' /etc/fstab; then
    run sh -c "echo '/swapfile none swap sw 0 0' >> /etc/fstab"
  fi
  echo "2 GB swap file created and persisted"
fi

say "3/10 User + code"
if ! id -u "$RUN_USER" >/dev/null 2>&1; then
  run useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"
fi
if [ -d "$INSTALL_DIR/.git" ]; then
  run git -C "$INSTALL_DIR" fetch --depth 1 origin main
  run git -C "$INSTALL_DIR" reset --hard origin/main
else
  run git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

say "4/10 Python environment"
if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
  run python3 -m venv "$INSTALL_DIR/.venv"
fi
# Core + comms only — no pywebview/pystray/playwright on a headless box.
run "$INSTALL_DIR/.venv/bin/pip" install --no-cache-dir -q --upgrade pip
run "$INSTALL_DIR/.venv/bin/pip" install --no-cache-dir -q \
  fastapi "uvicorn[standard]" websockets pydantic PyYAML \
  anthropic openai google-genai \
  ddgs requests python-multipart

say "5/10 Memory embeddings (Ollama + all-minilm)"
# Semantic memory recall. Without it, memory search is keyword-only and misses
# paraphrases ("what is my mother tongue?" never reaches the fact that says
# Telugu). all-minilm is 46 MB / 384-dim and ~150 MB resident — it fits the
# 1 GB reference box next to the agent, and Ollama's installer registers a
# systemd unit so it survives reboots. Wholly optional: on failure recall falls
# back to BM25 and the embedder circuit-breaks, costing nothing per turn.
embed_fail() {
  cat >&2 <<EOF

ERROR: $1
  Namma Agent's memory needs a local embedding model for semantic recall.
  Install Ollama manually, then re-run this installer:
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull all-minilm

  To install without it anyway (memory recall becomes keyword-only), re-run with:
    ... | sudo bash -s -- --no-embeddings
EOF
  exit 1
}

if [ "$NOEMBED" = "1" ]; then
  echo "skipped (--no-embeddings) — recall will be keyword-only"
elif command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | grep -q "^all-minilm"; then
  echo "all-minilm already installed"
else
  if ! command -v ollama >/dev/null 2>&1; then
    echo "installing Ollama…"
    run sh -c "curl -fsSL https://ollama.com/install.sh | sh" || true
  fi
  command -v ollama >/dev/null 2>&1 || \
    embed_fail "Ollama could not be installed automatically."
  # The official installer enables ollama.service; make sure it's up before pulling.
  run systemctl enable --now ollama 2>/dev/null || true
  for _ in 1 2 3 4 5; do ollama list >/dev/null 2>&1 && break; sleep 2; done
  ollama list >/dev/null 2>&1 || \
    embed_fail "Ollama is installed but its service is not responding."
  echo "pulling all-minilm (46 MB)…"
  run ollama pull all-minilm >/dev/null 2>&1 || \
    embed_fail "Downloading the all-minilm model failed."
  echo "semantic memory recall enabled"
fi

say "6/10 Web UI"
if [ -f "$INSTALL_DIR/namma_agent/webui/dist/index.html" ]; then
  echo "prebuilt dist/ present — skipping the Node build"
else
  if ! command -v node >/dev/null 2>&1; then
    run apt-get install -y --no-install-recommends nodejs npm
  fi
  echo "building the UI (few minutes on a small box — the swap file carries it)…"
  run sh -c "cd '$INSTALL_DIR/namma_agent/webui' && npm install --no-audit --no-fund && npm run build"
fi

say "7/10 Server-lite config profile"
if [ ! -f "$INSTALL_DIR/namma_agent/config.local.yaml" ]; then
  run cp "$INSTALL_DIR/deploy/config.server-lite.yaml" \
        "$INSTALL_DIR/namma_agent/config.local.yaml"
  echo "applied deploy/config.server-lite.yaml (1 GB-friendly defaults)"
else
  echo "config.local.yaml exists — keeping your settings"
fi

say "8/10 Access token"
touch "$INSTALL_DIR/.env"
if grep -q '^NAMMA_AUTH_TOKEN=' "$INSTALL_DIR/.env"; then
  TOKEN=$(grep '^NAMMA_AUTH_TOKEN=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2-)
  echo "token already set — keeping it"
else
  TOKEN=$("$INSTALL_DIR/.venv/bin/python" -c "import secrets;print(secrets.token_urlsafe(32))")
  run sh -c "echo 'NAMMA_AUTH_TOKEN=$TOKEN' >> '$INSTALL_DIR/.env'"
fi
run chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR"
run chmod 600 "$INSTALL_DIR/.env"

say "9/10 systemd service"
if [ "$DRY" = 1 ]; then
  echo "DRY: install /etc/systemd/system/namma-agent.service"
else
  sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$INSTALL_DIR/deploy/namma-agent.service" \
    > /etc/systemd/system/namma-agent.service
  systemctl daemon-reload
  systemctl enable --now namma-agent
fi

say "10/10 Done"
cat <<EOF

  Namma Agent is installed and running as a service.

  Access token (also in $INSTALL_DIR/.env — you need it if you expose the web UI):
      $TOKEN

  Next steps:
    * Add your AI provider key:   sudo -u $RUN_USER nano $INSTALL_DIR/.env
        e.g.  ANTHROPIC_API_KEY=sk-ant-...
      then:  sudo systemctl restart namma-agent
    * Connect Telegram (recommended — no open ports needed): docs/GATEWAYS.md
    * Check it:   sudo systemctl status namma-agent
                  curl -s http://127.0.0.1:8000/api/health
    * Full guides: docs/DEPLOY.md (incl. the Oracle free-tier walkthrough)

EOF
