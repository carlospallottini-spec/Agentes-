"""Cliente mínimo de Instagram Messaging API para enviar DMs y parsear webhooks."""
import os
from typing import Iterator

import httpx

GRAPH_VERSION = "v21.0"


def send_text(recipient_id: str, body: str) -> dict:
    """Envía un DM por Instagram (Messenger Platform sobre Graph API)."""
    ig_id = os.environ["INSTAGRAM_ACCOUNT_ID"]
    token = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{ig_id}/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": body[:1000]},
    }
    r = httpx.post(
        url,
        params={"access_token": token},
        json=payload,
        timeout=20.0,
    )
    r.raise_for_status()
    return r.json()


def parse_incoming(payload: dict) -> Iterator[dict]:
    """Itera mensajes de texto entrantes en un webhook payload de Instagram.

    Yields dicts con {"from": "<igsid>", "text": "<body>", "message_id": "..."}.
    Ignora echos (mensajes que enviamos nosotros), reacciones y adjuntos.
    """
    for entry in payload.get("entry", []) or []:
        for event in entry.get("messaging", []) or []:
            msg = event.get("message") or {}
            if msg.get("is_echo"):
                continue
            text = msg.get("text")
            if not text:
                continue
            sender = (event.get("sender") or {}).get("id")
            if not sender:
                continue
            yield {
                "from": sender,
                "text": text,
                "message_id": msg.get("mid"),
            }
