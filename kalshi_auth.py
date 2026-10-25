"""Kalshi Trade API request signing (RSA-PSS / Ed25519)."""
from __future__ import annotations

import base64
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def load_private_key_from_env() -> tuple[str | None, Any | None]:
    """Return (api_key_id, private_key) from env, or (None, None) if unset."""
    api_key_id = os.environ.get("KALSHI_ACCESS_KEY") or os.environ.get(
        "KALSHI_API_KEY_ID"
    )
    pem = os.environ.get("KALSHI_PRIVATE_KEY")
    path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if not api_key_id:
        return None, None
    if pem:
        pem_bytes = pem.replace("\\n", "\n").encode("utf-8")
    elif path:
        with open(path, "rb") as f:
            pem_bytes = f.read()
    else:
        return api_key_id, None
    key = serialization.load_pem_private_key(
        pem_bytes, password=None, backend=default_backend()
    )
    return api_key_id, key


def sign_request(private_key, timestamp_ms: str, method: str, sign_path: str) -> str:
    path_without_query = sign_path.split("?")[0]
    message = f"{timestamp_ms}{method.upper()}{path_without_query}".encode("utf-8")
    if isinstance(private_key, Ed25519PrivateKey):
        signature = private_key.sign(message)
    else:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
    return base64.b64encode(signature).decode("utf-8")


def kalshi_get(
    base_url: str,
    api_key_id: str,
    private_key,
    path: str,
    *,
    query: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict:
    """
    Authenticated GET. `path` is relative to base (e.g. `/cfbenchmarks/values`).
    Signs `/trade-api/v2` + path without query string.
    """
    base = base_url.rstrip("/")
    sign_path = urllib.parse.urlparse(base + path).path
    q = urllib.parse.urlencode(query) if query else ""
    url = f"{base}{path}" + (f"?{q}" if q else "")
    timestamp = str(int(time.time() * 1000))
    signature = sign_request(private_key, timestamp, "GET", sign_path)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "KALSHI-ACCESS-KEY": api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        },
        method="GET",
    )
    import json

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Kalshi HTTP {e.code}: {body}") from e
