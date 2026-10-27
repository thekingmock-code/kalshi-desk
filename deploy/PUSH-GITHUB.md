# Push this project to GitHub

The agent **cannot** push to GitHub until **you** authorize GitHub once (no password stored here).

## Easiest — Cursor “Create repo”

1. Open this chat in Cursor.
2. Click **Create repo** → choose **GitHub** → name e.g. `kalshi-desk`.
3. Done — code is on `https://github.com/YOUR_USERNAME/kalshi-desk`.

Use on VPS:

```bash
export REPO_URL="https://github.com/YOUR_USERNAME/kalshi-desk.git"
```

---

## Option B — GitHub website + phone

1. On your phone: [https://github.com/new](https://github.com/new)
2. Repository name: **`kalshi-desk`**
3. **Public** → **Create repository** (no README/license).
4. On your laptop (or Cursor terminal with GitHub logged in):

```bash
cd /path/to/kalshi-desk
git remote add github https://github.com/YOUR_USERNAME/kalshi-desk.git
git push -u github main
```

If it asks for a password, use a **Personal Access Token** (GitHub → Settings → Developer settings → Tokens).

---

## Option C — Authorize this agent, then ask to push again

1. Open [https://github.com/login/device](https://github.com/login/device)
2. In Cursor agent terminal, run: `gh auth login --web --git-protocol https`
3. Enter the **one-time code** shown in the terminal.
4. Ask the agent: “push to github now”

---

## Already on Cursor git

Your code is already on Origin:

`https://origin.cursor.com/git/mock-the-king/tmp-0d8739d7766488b2.git`

GitHub is separate until you complete one of the steps above.
