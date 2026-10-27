# VPS deploy (Ubuntu, no laptop)

Run the desk 24/7 on a small Ubuntu VPS. The app listens on **127.0.0.1:43123**; use a tunnel or reverse proxy for HTTPS on your phone.

## 1. SSH into the VPS

From your computer (one time):

```bash
ssh ubuntu@YOUR_VPS_IP
```

Use the user/password or SSH key your provider gave you.

## 2. Clone and install

Replace `REPO_URL` with your repository (GitHub, Origin, etc.):

```bash
export REPO_URL='https://github.com/YOUR_USER/YOUR_REPO.git'
curl -fsSL "$REPO_URL/raw/main/deploy/install-vps.sh" -o /tmp/install-vps.sh
# If raw script URL fails, clone first then:
git clone "$REPO_URL" ~/kalshi-desk && cd ~/kalshi-desk && bash deploy/install-vps.sh
```

Or after clone:

```bash
cd ~/kalshi-desk
REPO_URL="$REPO_URL" bash deploy/install-vps.sh
```

## 3. Kalshi keys (optional)

Edit `~/kalshi-desk/.env`:

- `KALSHI_ACCESS_KEY`
- `KALSHI_PRIVATE_KEY_PATH` (path to PEM on the VPS)

Without keys, the desk still runs using Coinbase + Kraken composite; RTI index may be missing until keyed.

## 4. Verify on the server

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:43123/
sudo systemctl status kalshi-desk
journalctl -u kalshi-desk -f
```

## 5. Open from your phone (pick one)

### A. Cloudflare Tunnel (recommended, free HTTPS)

On the VPS:

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared tunnel login
cloudflared tunnel create kalshi-desk
```

Point a hostname (e.g. `desk.yourdomain.com`) at `http://127.0.0.1:43123` in the Cloudflare Zero Trust dashboard, or use a `config.yml` ingress. Run `cloudflared` as a systemd service (see Cloudflare docs).

### B. SSH tunnel (quick test, no domain)

From your phone/laptop while SSH works:

```bash
ssh -L 43123:127.0.0.1:43123 ubuntu@YOUR_VPS_IP
```

Then open http://127.0.0.1:43123 on that device.

## Updates

```bash
cd ~/kalshi-desk
git pull
./.venv/bin/pip install -r requirements.txt
sudo systemctl restart kalshi-desk
```

## Firewall

- Allow **22/tcp** (SSH).
- Do **not** need to open **43123** publicly if you use Cloudflare Tunnel or SSH port-forward.
