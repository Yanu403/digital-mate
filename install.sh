#!/usr/bin/env bash
# Digital Mate - One-line installer
# Usage: curl -sSL https://raw.githubusercontent.com/Yanu403/digital-mate/master/install.sh | bash
# Options: --launch (auto-start after install), INSTALL_DIR=/path (custom location)

set -euo pipefail

# --- Colors & helpers ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC} $*"; }
ok()    { echo -e "${GREEN}[ok]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
err()   { echo -e "${RED}[error]${NC} $*" >&2; }
die()   { err "$*"; exit 1; }

REPO_URL="https://github.com/Yanu403/digital-mate.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.digital-mate}"
LAUNCH=false

# Parse arguments
for arg in "$@"; do
  case "$arg" in
    --launch) LAUNCH=true ;;
  esac
done

# Handle Ctrl+C
trap 'echo ""; warn "Installation cancelled by user."; exit 130' INT

echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Digital Mate Installer         ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

# --- 1. Check prerequisites ---
info "Checking prerequisites..."

if ! command -v git &>/dev/null; then
  die "git is not installed.\n  Install it with:\n    Ubuntu/Debian: sudo apt install git\n    macOS: xcode-select --install"
fi
ok "git found: $(git --version)"

# Check Python 3.11+
PYTHON=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" &>/dev/null; then
    version=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)
    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ] 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  die "Python 3.11+ is required but not found.\n  Install it with:\n    Ubuntu/Debian: sudo apt install python3.11 python3.11-venv\n    macOS: brew install python@3.11"
fi
ok "Python found: $($PYTHON --version)"

# --- 2. Clone or update repo ---
if [ -d "$INSTALL_DIR/.git" ]; then
  info "Digital Mate already installed at $INSTALL_DIR — updating..."
  cd "$INSTALL_DIR"
  git pull --ff-only 2>/dev/null || warn "Could not fast-forward; using existing version."
  ok "Repository updated."
else
  if [ -d "$INSTALL_DIR" ]; then
    warn "$INSTALL_DIR exists but is not a git repo."
    read -r -p "  Remove it and re-install? [y/N] " answer < /dev/tty || answer="y"
    case "$answer" in
      [yY]*) rm -rf "$INSTALL_DIR" ;;
      *) die "Aborted. Remove $INSTALL_DIR manually and retry." ;;
    esac
  fi
  info "Cloning Digital Mate into $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
  ok "Repository cloned."
fi

cd "$INSTALL_DIR"

# --- 3. Setup Python venv ---
info "Creating Python virtual environment..."
if [ ! -d ".venv" ]; then
  $PYTHON -m venv .venv
fi
ok "Virtual environment ready."

info "Upgrading pip..."
.venv/bin/pip install --upgrade pip --quiet

info "Installing dependencies (this may take a minute)..."
.venv/bin/pip install -r requirements.txt --quiet
ok "Dependencies installed."

# --- 4. Create .env ---
if [ -f .env.example ] && [ ! -f .env ]; then
  cp .env.example .env
  ok "Created .env from .env.example — edit it with your settings."
elif [ ! -f .env ]; then
  touch .env
  ok "Created empty .env file."
else
  ok ".env already exists — not overwriting."
fi

# --- 5. Create convenience wrapper ---
mkdir -p bin
cat > bin/digital-mate << 'WRAPPER'
#!/usr/bin/env bash
# Digital Mate CLI wrapper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
exec "$PROJECT_DIR/.venv/bin/python" -m digital_mate "$@"
WRAPPER
chmod +x bin/digital-mate
ok "Created bin/digital-mate wrapper."

# --- 6. Done ---
echo ""
echo -e "${GREEN}${BOLD}✅ Digital Mate installed successfully!${NC}"
echo ""
echo -e "  To start the dashboard:"
echo -e "    ${CYAN}cd $INSTALL_DIR && .venv/bin/python -m digital_mate serve${NC}"
echo ""
echo -e "  Or use the shortcut:"
echo -e "    ${CYAN}$INSTALL_DIR/bin/digital-mate serve${NC}"
echo ""
echo -e "  Add to your PATH for easy access:"
echo -e "    ${CYAN}echo 'export PATH=\"$INSTALL_DIR/bin:\$PATH\"' >> ~/.bashrc${NC}"
echo ""

# --- 7. Auto-launch ---
if [ "$LAUNCH" = true ]; then
  info "Launching Digital Mate..."
  exec .venv/bin/python -m digital_mate serve
fi
