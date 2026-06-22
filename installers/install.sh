#!/usr/bin/env bash
# Namma Agent - installer for macOS & Linux.
# Run it:  bash installers/install.sh   (or double-click "Install Namma Agent.command" on macOS)
#
# Bootstraps everything on THIS machine - and AUTO-INSTALLS Python, Git and Node.js
# if they're missing (Homebrew on macOS; apt/dnf/pacman/zypper on Linux) - so a
# beginner can just run it. Then: venv, dependencies, the web UI, the first AI
# provider + onboarding, a desktop launcher, and launch.
#
#   --no-setup     skip the interactive first-provider / onboarding prompts
#   --no-launch    set up only, don't launch (used by the native .dmg/.AppImage)
#   --no-shortcut  don't create a launcher (the native installer manages it)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

NO_LAUNCH=0; NO_SETUP=0; NO_SHORTCUT=0
for a in "$@"; do
  case "$a" in
    --no-launch)   NO_LAUNCH=1 ;;
    --no-setup)    NO_SETUP=1 ;;
    --no-shortcut) NO_SHORTCUT=1 ;;
  esac
done

echo "=============================================="
echo "  Namma Agent - installer"
echo "  Intelligence for Everyone."
echo "=============================================="

have() { command -v "$1" >/dev/null 2>&1; }

# 1. Ensure Python, Git, Node (auto-install if missing) ----------------------
echo "[1/8] Ensuring Python 3.10+, Git and Node.js ..."
ensure_deps_macos() {
  have git || xcode-select --install 2>/dev/null || true
  if ! have brew; then
    echo "      Installing Homebrew (non-interactive)…"
    NONINTERACTIVE=1 /bin/bash -c \
      "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || true
    [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [ -x /usr/local/bin/brew ]    && eval "$(/usr/local/bin/brew shellenv)"
  fi
  if have brew; then
    have python3 || brew install python || true
    have npm     || brew install node   || true
    have git     || brew install git    || true
    # Optional tools (richer search/media; app degrades gracefully without them).
    have rg      || brew install ripgrep || true
    have ffmpeg  || brew install ffmpeg  || true
  fi
}
ensure_deps_linux() {
  local need=""
  have python3 || need="$need python"
  have npm     || need="$need node"
  have git     || need="$need git"
  # ripgrep + ffmpeg are optional (richer search/media); pull them in too if missing.
  have rg      || need="$need ripgrep"
  have ffmpeg  || need="$need ffmpeg"
  [ -z "$need" ] && return 0
  echo "      Missing:$need — installing with your package manager (may ask for sudo)…"
  if   have apt-get; then sudo apt-get update -y || true
       sudo apt-get install -y python3 python3-venv python3-pip nodejs npm git ripgrep ffmpeg || true
  elif have dnf;     then sudo dnf install -y python3 python3-pip nodejs npm git ripgrep ffmpeg || true
  elif have pacman;  then sudo pacman -Sy --noconfirm python nodejs npm git ripgrep ffmpeg || true
  elif have zypper;  then sudo zypper install -y python3 python3-venv nodejs npm git ripgrep ffmpeg || true
  else echo "      No known package manager — please install python3, node and git manually."
  fi
}
case "$(uname -s)" in
  Darwin) ensure_deps_macos ;;
  Linux)  ensure_deps_linux ;;
esac

# 2. Pick a Python 3.10+ -----------------------------------------------------
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if have "$c" && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: Python 3.10+ not found and could not be installed automatically."
  echo "  Install it, then re-run this script."
  exit 1
fi
echo "[2/8] Using $($PY --version)"

# 3. virtual environment -----------------------------------------------------
if [ ! -d .venv ]; then echo "[3/8] Creating .venv …"; "$PY" -m venv .venv
else echo "[3/8] Reusing existing .venv"; fi
VPY="$ROOT/.venv/bin/python"

# 4. dependencies ------------------------------------------------------------
echo "[4/8] Installing dependencies (a few minutes on first run) …"
"$VPY" -m pip install --upgrade pip --no-cache-dir >/dev/null
"$VPY" -m pip install --no-cache-dir -r namma_agent/requirements.txt

# 5. web UI ------------------------------------------------------------------
if [ -f namma_agent/webui/dist/index.html ]; then
  echo "[5/8] Web UI already built — skipping"
elif have npm; then
  echo "[5/8] Building the web UI …"
  ( cd namma_agent/webui && npm install && npm run build )
else
  echo "[5/8] WARNING: web UI not built and Node/npm not found."
fi

# 6. first provider + onboarding ---------------------------------------------
if [ "$NO_SETUP" = "1" ]; then
  echo "[6/8] Skipping provider/onboarding — configure it in the app."
else
  echo "[6/8] Configuring the first AI provider + a few questions …"
  "$VPY" -m namma_agent --setup || echo "      (setup skipped — finish it in the app)"
fi

# 7. desktop launcher --------------------------------------------------------
if [ "$NO_SHORTCUT" = "1" ]; then
  echo "[7/8] Skipping launcher (managed by the installer)."
elif [ "$(uname -s)" = "Darwin" ]; then
  echo "[7/8] Creating a desktop launcher …"
  LAUNCHER="$ROOT/Namma Agent.command"
  printf '#!/usr/bin/env bash\ncd "%s"\nexec "%s" -m namma_agent\n' "$ROOT" "$VPY" > "$LAUNCHER"
  chmod +x "$LAUNCHER"
  echo "      Double-click to start: $LAUNCHER"
else
  echo "[7/8] Creating a desktop launcher …"
  APPS="$HOME/.local/share/applications"; mkdir -p "$APPS"
  cat > "$APPS/namma-agent.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Namma Agent
Comment=Intelligence for Everyone
Exec=$VPY -m namma_agent
Icon=$ROOT/namma_agent/assets/sparkle.png
Terminal=false
Categories=Utility;Development;
EOF
  chmod +x "$APPS/namma-agent.desktop" 2>/dev/null || true
  echo "      Added to your applications menu: Namma Agent"
fi

# 7b. `namma` command on PATH (so you can run `namma`, `namma --chat`, `namma --server`).
BINDIR="$HOME/.local/bin"; mkdir -p "$BINDIR"
printf '#!/usr/bin/env bash\nexec "%s" -m namma_agent "$@"\n' "$VPY" > "$BINDIR/namma"
chmod +x "$BINDIR/namma"
case ":$PATH:" in
  *":$BINDIR:"*) echo "      Installed the 'namma' command ($BINDIR/namma)." ;;
  *) echo "      Installed the 'namma' command at $BINDIR/namma — add $BINDIR to your PATH to use it." ;;
esac

# 8. launch ------------------------------------------------------------------
echo "=============================================="
if [ "$NO_LAUNCH" = "1" ]; then
  echo "[8/8] Setup complete. Launch 'Namma Agent' from your applications menu."
else
  echo "[8/8] Launching Namma Agent …"
  exec "$VPY" -m namma_agent
fi
