# Permanent dashboard: domain + Cloudflare Tunnel (free HTTPS)

Use this after the desk is running on your Ubuntu VPS (`deploy/install-vps.sh`).

You will:

1. Buy a domain on Cloudflare (~$10/year).
2. Run **cloudflared** on the VPS (free).
3. Open **`https://desk.YOURDOMAIN.com`** on your phone — same URL forever.

The desk stays on **127.0.0.1:43123** on the VPS. Only Cloudflare talks to it; you do **not** open port 43123 on the public internet.

---

## Part A — Buy the domain (Cloudflare Registrar)

1. Log in at [https://dash.cloudflare.com](https://dash.cloudflare.com) (create a free account if needed).
2. Go to **Domain Registration** → **Register domains** (or **Registrar** in the sidebar).
3. Search for a name (e.g. `mockkingdesk.com`, `xvdesk.com`).
4. Add to cart and pay (often ~$10–15/year for `.com`; Cloudflare sells at cost).
5. The domain is automatically on your Cloudflare account — no extra DNS host to configure.

Pick a hostname for the desk, e.g. **`desk`** → full URL **`https://desk.YOURDOMAIN.com`**.

---

## Part B — Desk already on the VPS

SSH in:

```bash
ssh ubuntu@YOUR_VPS_IP
```

If you have not installed the app yet:

```bash
git clone YOUR_REPO_URL ~/kalshi-desk
cd ~/kalshi-desk
REPO_URL=YOUR_REPO_URL bash deploy/install-vps.sh
```

Confirm:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:43123/
# expect 200
sudo systemctl status kalshi-desk
```

---

## Part C — Install cloudflared on the VPS

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared --version
```

(For ARM VPS, use `cloudflared-linux-arm64.deb` instead.)

---

## Part D — Log in and create a tunnel

```bash
cloudflared tunnel login
```

- A URL prints in the terminal. Open it on your ** laptop/phone browser**, log into Cloudflare, and **authorize** the domain you bought.

Create a named tunnel:

```bash
cloudflared tunnel create kalshi-desk
```

Note the **Tunnel UUID** printed (and the credentials JSON path, usually `~/.cloudflared/<UUID>.json`).

Route DNS (replace `YOURDOMAIN.com`):

```bash
cloudflared tunnel route dns kalshi-desk desk.YOURDOMAIN.com
```

This creates a CNAME `desk` → your tunnel in Cloudflare DNS.

---

## Part E — Tunnel config

Edit config (create the directory if needed):

```bash
mkdir -p ~/.cloudflared
nano ~/.cloudflared/config.yml
```

Paste and replace **TUNNEL-UUID** and **YOURDOMAIN.com**:

```yaml
tunnel: TUNNEL-UUID
credentials-file: /home/ubuntu/.cloudflared/TUNNEL-UUID.json

ingress:
  - hostname: desk.YOURDOMAIN.com
    service: http://127.0.0.1:43123
  - service: http_status:404
```

If your Linux user is not `ubuntu`, fix the `credentials-file` path (`/home/YOUR_USER/.cloudflared/...`).

Test run (foreground):

```bash
cloudflared tunnel run kalshi-desk
```

On your phone, open **`https://desk.YOURDOMAIN.com`**. You should see the XVANTAGE desk.

Stop the test with `Ctrl+C`.

---

## Part F — Run cloudflared on boot (systemd)

```bash
sudo cloudflared service install
```

If your config is in `~/.cloudflared/config.yml` as **ubuntu**, the install may expect root config. Safer approach — install as root with system config:

```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/config.yml /etc/cloudflared/config.yml
sudo cp ~/.cloudflared/*.json /etc/cloudflared/
sudo sed -i 's|/home/ubuntu/.cloudflared|/etc/cloudflared|g' /etc/cloudflared/config.yml
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

---

## Part G — Firewall (recommended)

Only **SSH (22)** needs to be open to the world. The desk and tunnel egress out; inbound 43123 is not required.

```bash
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

---

## Checklist

| Step | Command / URL |
|------|----------------|
| Desk local | `curl http://127.0.0.1:43123/` → 200 |
| Kalshi desk service | `sudo systemctl status kalshi-desk` |
| Tunnel service | `sudo systemctl status cloudflared` |
| Phone bookmark | `https://desk.YOURDOMAIN.com` |

---

## Updates (desk code)

```bash
cd ~/kalshi-desk
git pull
./.venv/bin/pip install -r requirements.txt
sudo systemctl restart kalshi-desk
```

Tunnel keeps running; no DNS changes needed.

---

## Troubleshooting

**502 / error page from Cloudflare**

- Desk down: `sudo systemctl restart kalshi-desk` and check `journalctl -u kalshi-desk -f`.
- Wrong port in `config.yml` → must be `http://127.0.0.1:43123`.

**Tunnel not connecting**

- `journalctl -u cloudflared -f`
- Re-run `cloudflared tunnel login` if credentials expired.

**WebSocket flaky but page loads**

- The UI falls back to HTTP polling; hard refresh the page.

**Kalshi RTI / index missing on VPS**

- Add keys in `~/kalshi-desk/.env` and `sudo systemctl restart kalshi-desk`.
