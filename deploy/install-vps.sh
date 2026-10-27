#!/usr/bin/env bash
# Run on Ubuntu 22.04/24.04 VPS as a user that can sudo (e.g. ubuntu).
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/kalshi-desk}"
REPO_URL="${REPO_URL:-}"

if [[ -z "$REPO_URL" ]]; then
  echo "Set REPO_URL to your git clone URL, e.g.:"
  echo '  REPO_URL=https://github.com/you/kalshi-desk.git bash deploy/install-vps.sh'
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only || true
fi

cd "$APP_DIR"
python3 -m venv .venv
./.venv/bin/pip install -U pip
./.venv/bin/pip install -r requirements.txt

if [[ ! -f .env ]] && [[ -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — add Kalshi keys if you have them."
fi

sudo cp deploy/kalshi-desk.service /etc/systemd/system/kalshi-desk.service
sudo sed -i "s|/home/ubuntu/kalshi-desk|$APP_DIR|g" /etc/systemd/system/kalshi-desk.service
sudo sed -i "s|User=ubuntu|User=$USER|g" /etc/systemd/system/kalshi-desk.service
sudo sed -i "s|Group=ubuntu|Group=$USER|g" /etc/systemd/system/kalshi-desk.service

sudo systemctl daemon-reload
sudo systemctl enable kalshi-desk
sudo systemctl restart kalshi-desk

echo ""
echo "Desk running on http://127.0.0.1:43123 (local to VPS only)."
echo "Check: sudo systemctl status kalshi-desk"
echo "Logs:  journalctl -u kalshi-desk -f"
echo ""
echo "Next: expose with Cloudflare Tunnel or nginx — see deploy/VPS.md"
