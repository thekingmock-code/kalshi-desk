#!/usr/bin/env bash
# One-shot setup for mockkingdesk.com on Ubuntu VPS (Zynoo, etc.)
# Run as root on the VPS (Zynoo Console or: ssh root@YOUR_IP)
#
# You still must complete ONE browser step when prompted:
#   cloudflared tunnel login  → open the URL and approve mockkingdesk.com
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOU/REPO/main/deploy/zynoo-bootstrap.sh | bash
# Or after git clone:
#   REPO_URL=https://... bash deploy/zynoo-bootstrap.sh

set -euo pipefail

DOMAIN="${DOMAIN:-mockkingdesk.com}"
HOSTNAME="${HOSTNAME:-desk.${DOMAIN}}"
APP_DIR="${APP_DIR:-/root/kalshi-desk}"
TUNNEL_NAME="${TUNNEL_NAME:-kalshi-desk}"
REPO_URL="${REPO_URL:-}"

echo "=== Kalshi desk bootstrap ==="
echo "Domain: https://${HOSTNAME}"
echo ""

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (Zynoo default). Try: sudo bash $0"
  exit 1
fi

if [[ -z "$REPO_URL" ]]; then
  echo "Set REPO_URL to your git clone URL, e.g.:"
  echo '  REPO_URL="https://github.com/mock-the-king/kalshi-desk.git" bash deploy/zynoo-bootstrap.sh'
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip curl

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only || true
fi

cd "$APP_DIR"
python3 -m venv .venv
./.venv/bin/pip install -U pip -q
./.venv/bin/pip install -r requirements.txt -q

if [[ ! -f .env ]] && [[ -f .env.example ]]; then
  cp .env.example .env
fi

# systemd — desk on localhost only
sed "s|/home/ubuntu/kalshi-desk|$APP_DIR|g; s|User=ubuntu|User=root|g; s|Group=ubuntu|Group=root|g" \
  deploy/kalshi-desk.service > /etc/systemd/system/kalshi-desk.service
systemctl daemon-reload
systemctl enable kalshi-desk
systemctl restart kalshi-desk

sleep 2
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:43123/ || echo "000")
echo "Desk HTTP check: $code (want 200)"
if [[ "$code" != "200" ]]; then
  echo "Desk failed — logs:"
  journalctl -u kalshi-desk -n 30 --no-pager
  exit 1
fi

# cloudflared
if ! command -v cloudflared >/dev/null 2>&1; then
  curl -fsSL -o /tmp/cloudflared.deb \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  dpkg -i /tmp/cloudflared.deb
fi

CFDIR=/root/.cloudflared
mkdir -p "$CFDIR"

if [[ ! -f "$CFDIR/cert.pem" ]]; then
  echo ""
  echo "=============================================="
  echo "ACTION REQUIRED (only step you must do by hand)"
  echo "=============================================="
  echo "Run this command and open the URL in your browser:"
  echo "  cloudflared tunnel login"
  echo "Choose domain: ${DOMAIN}"
  echo "Then run again:"
  echo "  REPO_URL=\"$REPO_URL\" bash $APP_DIR/deploy/zynoo-bootstrap.sh"
  echo "=============================================="
  exit 0
fi

# Tunnel create (idempotent-ish)
if ! cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
  cloudflared tunnel create "$TUNNEL_NAME"
fi

TUNNEL_ID=$(cloudflared tunnel list | awk -v n="$TUNNEL_NAME" '$0 ~ n {print $1; exit}')
if [[ -z "$TUNNEL_ID" ]]; then
  echo "Could not find tunnel id for $TUNNEL_NAME"
  exit 1
fi

cloudflared tunnel route dns "$TUNNEL_NAME" "$HOSTNAME" 2>/dev/null || true

CRED="$CFDIR/${TUNNEL_ID}.json"
if [[ ! -f "$CRED" ]]; then
  # newer cloudflared may store creds by uuid only
  CRED=$(ls "$CFDIR"/*.json 2>/dev/null | head -1 || true)
fi

cat > "$CFDIR/config.yml" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CRED}

ingress:
  - hostname: ${HOSTNAME}
    service: http://127.0.0.1:43123
  - service: http_status:404
EOF

mkdir -p /etc/cloudflared
cp "$CFDIR/config.yml" /etc/cloudflared/config.yml
cp "$CRED" /etc/cloudflared/
sed -i "s|${CFDIR}|/etc/cloudflared|g" /etc/cloudflared/config.yml

cloudflared service install 2>/dev/null || true
systemctl enable cloudflared 2>/dev/null || true
systemctl restart cloudflared

echo ""
echo "=== Done ==="
echo "Bookmark: https://${HOSTNAME}"
echo "Desk:  systemctl status kalshi-desk"
echo "Tunnel: systemctl status cloudflared"
