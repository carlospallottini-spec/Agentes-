"""Servidor FastAPI con webhooks de WhatsApp e Instagram."""
import logging
import os
import threading

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

import conversations
import instagram
import whatsapp
from agent import build_client, responder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("selva-negra")

app = FastAPI(title="Selva Negra Pastelería - Asistente social")

_CLIENT = None
_PROCESSED_IDS: set[str] = set()
_PROCESSED_LOCK = threading.Lock()


def _client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = build_client()
    return _CLIENT


def _already_processed(message_id: str | None) -> bool:
    if not message_id:
        return False
    with _PROCESSED_LOCK:
        if message_id in _PROCESSED_IDS:
            return True
        _PROCESSED_IDS.add(message_id)
        if len(_PROCESSED_IDS) > 5000:
            _PROCESSED_IDS.clear()
        return False


def _handle_message(channel: str, sender: str, text: str, send_fn) -> None:
    user_key = f"{channel}:{sender}"
    history = conversations.get_history(user_key)
    try:
        reply = responder(_client(), history, text)
    except Exception:
        log.exception("Error generando respuesta para %s", user_key)
        reply = "Disculpá, tuvimos un problema técnico. Probá de nuevo en un ratito."
    conversations.save_history(user_key, history)

    if not reply:
        return
    try:
        send_fn(sender, reply)
    except Exception:
        log.exception("Error enviando respuesta a %s", user_key)


@app.get("/")
def health() -> dict:
    return {"status": "ok", "bakery": "selva-negra"}


# --- WhatsApp ----------------------------------------------------------------

@app.get("/webhook/whatsapp")
def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    expected = os.environ.get("META_VERIFY_TOKEN")
    if hub_mode == "subscribe" and hub_verify_token == expected:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verify token mismatch")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> dict:
    payload = await request.json()
    for msg in whatsapp.parse_incoming(payload):
        if _already_processed(msg["message_id"]):
            continue
        log.info("WA in from %s: %s", msg["from"], msg["text"][:80])
        _handle_message("wa", msg["from"], msg["text"], whatsapp.send_text)
    return {"status": "received"}


# --- Instagram ---------------------------------------------------------------

@app.get("/webhook/instagram")
def instagram_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    expected = os.environ.get("META_VERIFY_TOKEN")
    if hub_mode == "subscribe" and hub_verify_token == expected:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verify token mismatch")


@app.post("/webhook/instagram")
async def instagram_webhook(request: Request) -> dict:
    payload = await request.json()
    for msg in instagram.parse_incoming(payload):
        if _already_processed(msg["message_id"]):
            continue
        log.info("IG in from %s: %s", msg["from"], msg["text"][:80])
        _handle_message("ig", msg["from"], msg["text"], instagram.send_text)
    return {"status": "received"}
