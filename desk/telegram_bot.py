"""Optional Telegram bot: /status and /composite (token from env only)."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request


def _api(token: str, method: str, **params) -> dict:
    q = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{token}/{method}?{q}" if q else f"https://api.telegram.org/bot{token}/{method}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _post(token: str, method: str, body: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


async def run_telegram_bot(desk, stop: asyncio.Event) -> None:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return
    allowed = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    offset = 0
    print("Telegram bot polling (set TELEGRAM_CHAT_ID to restrict replies)")
    while not stop.is_set():
        try:
            data = await asyncio.to_thread(_api, token, "getUpdates", offset=offset, timeout=25)
            for upd in data.get("result") or []:
                offset = max(offset, int(upd["update_id"]) + 1)
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                text = (msg.get("text") or "").strip()
                if allowed and chat_id != allowed:
                    continue
                if text.startswith("/start"):
                    reply = (
                        f"Desk linked. Your chat id is {chat_id}. "
                        "Set TELEGRAM_CHAT_ID on the server to this value. Commands: /status /composite"
                    )
                    await asyncio.to_thread(_post, token, "sendMessage", {"chat_id": chat_id, "text": reply})
                elif text.startswith("/status") or text.startswith("/composite"):
                    body = await asyncio.to_thread(_format_composite, desk)
                    await asyncio.to_thread(_post, token, "sendMessage", {"chat_id": chat_id, "text": body[:4000]})
        except Exception as exc:
            if stop.is_set():
                return
            print(f"Telegram bot: {exc.__class__.__name__}")
            await asyncio.sleep(3.0)


def _format_composite(desk) -> str:
    now = __import__("time").time()
    lines = ["XVANTAGE composite"]
    for asset, st in desk.assets.items():
        price, names, age = desk._composite(st, now)
        diag = desk._last_composite_diag.get(asset) or {}
        lines.append(f"\n{asset}: composite={price} venues={','.join(names) if names else '—'}")
        for vname, row in sorted((diag.get("venues") or {}).items()):
            lines.append(
                f"  {vname}: {row.get('mid')} dev {row.get('deviation_usd')} ({row.get('deviation_bps')} bps) age {row.get('age_ms')}ms"
            )
        if diag.get("median") is not None:
            lines.append(f"  median cross-check: {diag['median']}")
    return "\n".join(lines)
