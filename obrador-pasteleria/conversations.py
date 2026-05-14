"""Persistencia simple de historial de conversación por usuario.

Cada usuario (WhatsApp phone, IG user id) tiene su propio hilo, identificado
por una clave estable tipo "wa:54911..." o "ig:1789...".
"""
import json
import threading
from pathlib import Path

STORE_PATH = Path(__file__).parent / "data" / "conversations.json"
_LOCK = threading.Lock()

# Cantidad máxima de turnos por usuario que mantenemos en memoria/disco.
# Cada "turno" es un mensaje en el historial (user + assistant + tool_results cuentan).
MAX_TURNS_PER_USER = 60


def _load_all() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def _save_all(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(STORE_PATH)


def get_history(user_key: str) -> list[dict]:
    with _LOCK:
        return list(_load_all().get(user_key, []))


def save_history(user_key: str, history: list[dict]) -> None:
    with _LOCK:
        data = _load_all()
        # Trim si crece demasiado, conservando los últimos N turnos completos.
        if len(history) > MAX_TURNS_PER_USER:
            history = history[-MAX_TURNS_PER_USER:]
            # Si el primero quedó siendo un tool_result, lo descartamos para mantener
            # la alternancia válida.
            while history and history[0].get("role") == "user" and isinstance(history[0].get("content"), list) \
                    and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in history[0]["content"]):
                history = history[1:]
        data[user_key] = history
        _save_all(data)
