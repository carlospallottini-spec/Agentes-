"""Lista de seguimiento del inversor (multi-activo, persistida en disco).

Distinta de data/watchlist.json (que define las cadencias del oráculo): esta es la
watchlist personal que el usuario edita desde la plataforma, con cualquier clase de activo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from config import DATA_DIR

_PATH = DATA_DIR / "user_watchlist.json"


def _load() -> list[dict]:
    if _PATH.exists():
        return json.loads(_PATH.read_text(encoding="utf-8"))
    return []


def _save(items: list[dict]) -> None:
    _PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def list_items() -> list[dict]:
    return _load()


def add(symbol: str, name: str | None = None, asset_class: str | None = None) -> list[dict]:
    symbol = symbol.upper().strip()
    items = _load()
    if any(i["symbol"] == symbol for i in items):
        return items
    items.append({
        "symbol": symbol,
        "name": name or symbol,
        "asset_class": asset_class or "Otro",
        "added_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
    })
    _save(items)
    return items


def remove(symbol: str) -> list[dict]:
    symbol = symbol.upper().strip()
    items = [i for i in _load() if i["symbol"] != symbol]
    _save(items)
    return items
