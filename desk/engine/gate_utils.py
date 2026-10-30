"""Gate display status, passing counts, and snapshots."""
from __future__ import annotations

import json
from typing import Any


def gate_check(
    label: str,
    *,
    ok: bool,
    detail: str = "",
    locked: bool = False,
    status: str | None = None,
    counts: bool = True,
    hardness: str | None = None,
    value: Any = None,
    threshold: Any = None,
    **extra: Any,
) -> dict:
    if status is None:
        if not counts and detail.lower().startswith("off"):
            status = "off"
        elif not counts and detail.lower().startswith("waiting"):
            status = "waiting"
        else:
            status = "pass" if ok else "fail"
    return {
        "label": label,
        "ok": ok if status in ("pass", "fail") else False,
        "detail": detail,
        "locked": locked,
        "status": status,
        "counts": counts,
        "hardness": hardness,
        "value": value,
        "threshold": threshold,
        **extra,
    }


def gate_passing_stats(checks: list[dict]) -> tuple[int, int]:
    counted = [c for c in checks if c.get("counts", True)]
    passing = sum(
        1
        for c in counted
        if c.get("status") == "pass" or (c.get("status") is None and c.get("ok"))
    )
    return passing, len(counted)


def all_active_pass(checks: list[dict]) -> bool:
    passing, total = gate_passing_stats(checks)
    return total > 0 and passing == total


def checks_excluding_labels(checks: list[dict], *labels: str) -> list[dict]:
    skip = set(labels)
    return [c for c in checks if c.get("label") not in skip]


def gate_snapshot_json(checks: list[dict]) -> str:
    rows = []
    for c in checks:
        rows.append(
            {
                "label": c.get("label"),
                "status": c.get("status"),
                "value": c.get("value"),
                "threshold": c.get("threshold"),
                "detail": c.get("detail"),
                "hardness": c.get("hardness"),
                "counts": c.get("counts", True),
            }
        )
    return json.dumps(rows)


def find_gate(checks: list[dict], label: str) -> dict | None:
    for c in checks:
        if c.get("label") == label:
            return c
    return None
