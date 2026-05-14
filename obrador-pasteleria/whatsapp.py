"""Cliente mínimo de WhatsApp Cloud API para enviar mensajes y parsear webhooks."""
import os
from typing import Iterator

import httpx

GRAPH_VERSION = "v21.0"


def send_text(to: str, body: str) -> dict:
    """Envía un mensaje de texto por WhatsApp."""
    phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    token = os.environ["WHATSAPP_ACCESS_TOKEN"]
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body[:4096]},
    }
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=20.0,
    )
    r.raise_for_status()
    return r.json()


def parse_incoming(payload: dict) -> Iterator[dict]:
    """Itera mensajes de texto entrantes en un webhook payload de WhatsApp.

    Yields dicts con {"from": "<phone>", "text": "<body>", "message_id": "..."}.
    Ignora estados de entrega/lectura y mensajes no-texto.
    """
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for msg in value.get("messages", []) or []:
                if msg.get("type") != "text":
                    continue
                yield {
                    "from": msg.get("from"),
                    "text": (msg.get("text") or {}).get("body", ""),
                    "message_id": msg.get("id"),
                }
