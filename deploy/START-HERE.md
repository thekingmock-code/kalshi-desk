# Confused? Do only this

I **cannot** log into your Zynoo VPS or Cloudflare for you. You do **two things**; the script does the rest.

Your dashboard URL when finished:

**https://desk.mockkingdesk.com**

VPS IP from Zynoo: **140.150.232.144**

---

## Thing 1 — Open the VPS terminal (2 minutes)

1. Zynoo billing panel → your VPS → **Console** (monitor icon).
2. Log in as **root** (password from Zynoo email).

---

## Thing 2 — Paste this block (one time)

Replace `YOUR_REPO_URL` with where your code lives (GitHub or Origin git URL after you **Create repo** in Cursor):

```bash
export REPO_URL="YOUR_REPO_URL"
apt update && apt install -y git
git clone "$REPO_URL" /root/kalshi-desk
cd /root/kalshi-desk
bash deploy/zynoo-bootstrap.sh
```

If the script stops and says **cloudflared tunnel login**:

1. Copy the **https://** link it prints (or run `cloudflared tunnel login`).
2. Open that link on your **phone**, log into Cloudflare, pick **mockkingdesk.com**, approve.
3. Back in the Console, run:

```bash
export REPO_URL="YOUR_REPO_URL"
bash /root/kalshi-desk/deploy/zynoo-bootstrap.sh
```

---

## Done

Open **https://desk.mockkingdesk.com** on your phone and bookmark it.

---

## If git clone fails

Your repo must be **public**, or use a GitHub personal access token in the URL (never paste tokens in chat).

Example public clone:

```bash
export REPO_URL="https://github.com/YOUR_USER/kalshi-desk.git"
```

---

## Help

| Problem | Fix |
|---------|-----|
| `curl` / desk not 200 | `journalctl -u kalshi-desk -f` |
| 502 on desk.mockkingdesk.com | `systemctl restart kalshi-desk cloudflared` |
| DNS | Cloudflare dashboard → mockkingdesk.com → DNS → CNAME `desk` |
