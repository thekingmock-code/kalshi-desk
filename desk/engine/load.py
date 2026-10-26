from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    raw = (path or CONFIG_PATH).read_text()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("config.yaml must be a mapping")
    return data
