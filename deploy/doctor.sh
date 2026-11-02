#!/usr/bin/env bash
# Quick health check on the VPS (run as root).
set -uo pipefail

DESK_FQDN="${DESK_FQDN:-desk.mockkingdesk.com}"
APP_DIR="${APP_DIR:-/root/kalshi-desk}"

echo "=== Kalshi desk doctor ==="
echo "Time (UTC): $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Public URL: https://${DESK_FQDN}"
echo ""

desk_code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:43123/ 2>/dev/null || echo "000")
api_code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:43123/api/state 2>/dev/null || echo "000")
health_json=$(curl -s http://127.0.0.1:43123/api/health 2>/dev/null || echo "{}")
echo "Local desk /        → HTTP ${desk_code} (want 200)"
echo "Local desk /api/state → HTTP ${api_code} (want 200)"
ui_build=$(echo "$health_json" | grep -o '"ui_build"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 || true)
if [[ -n "$ui_build" ]]; then
  echo "UI build marker    → ${ui_build} (want desk-main-arb-chart-v3)"
  if [[ -f "${APP_DIR}/desk/static/lightweight-charts.standalone.js" ]]; then
    echo "Chart library file → present ($(wc -c < "${APP_DIR}/desk/static/lightweight-charts.standalone.js") bytes)"
  else
    echo "Chart library file → MISSING (git pull)"
  fi
else
  echo "UI build marker    → missing (git pull + restart kalshi-desk)"
fi
if [[ -f "${APP_DIR}/desk/static/index.html" ]]; then
  panels=$(grep -c 'id="deskPanels"' "${APP_DIR}/desk/static/index.html" 2>/dev/null || echo 0)
  echo "Features tab fix   → deskPanels count ${panels} (want 1)"
fi
echo ""

for u in kalshi-desk cloudflared; do
  if systemctl is-active --quiet "$u" 2>/dev/null; then
    echo "systemd ${u}: active"
  else
    echo "systemd ${u}: NOT active ($(systemctl is-active "$u" 2>/dev/null || echo missing))"
  fi
done
echo ""

if command -v cloudflared >/dev/null 2>&1; then
  cloudflared --version 2>/dev/null | head -1 || true
  if [[ -f /etc/cloudflared/config.yml ]]; then
    echo "Tunnel config: /etc/cloudflared/config.yml"
    grep -E '^(tunnel:|credentials-file:|hostname:)' /etc/cloudflared/config.yml 2>/dev/null || true
  else
    echo "Missing /etc/cloudflared/config.yml"
  fi
else
  echo "cloudflared: not installed"
fi
echo ""

pub=$(curl -s -o /dev/null -w "%{http_code}" --max-time 12 "https://${DESK_FQDN}/" 2>/dev/null || echo "000")
echo "Public https://${DESK_FQDN}/ → HTTP ${pub} (want 200 from VPS too)"
if [[ "$pub" != "200" ]]; then
  echo "If local is 200 but public is not: check cloudflared + Cloudflare DNS CNAME for desk → tunnel."
fi
echo ""
echo "Recent errors (if any):"
journalctl -u kalshi-desk -u cloudflared -p err -n 8 --no-pager 2>/dev/null || true
