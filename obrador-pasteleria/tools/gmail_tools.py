import base64
import json
import os
from email.mime.text import MIMEText
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _service():
    """Construye un cliente de Gmail con credenciales OAuth almacenadas localmente."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds_file = os.environ.get("GMAIL_CREDENTIALS_FILE", "./credentials/credentials.json")
    token_file = os.environ.get("GMAIL_TOKEN_FILE", "./credentials/token.json")

    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(creds_file).exists():
                raise FileNotFoundError(
                    f"No se encontró {creds_file}. Descargá credentials.json desde "
                    "Google Cloud Console (OAuth Client ID tipo Desktop) y colocalo allí."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token_file).parent.mkdir(parents=True, exist_ok=True)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def listar_correos(query: str = "", max_resultados: int = 10) -> str:
    try:
        svc = _service()
        max_resultados = max(1, min(int(max_resultados), 50))
        resp = svc.users().messages().list(userId="me", q=query, maxResults=max_resultados).execute()
        msgs = resp.get("messages", [])
        resumen = []
        for m in msgs:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
            resumen.append({
                "id": m["id"],
                "de": headers.get("From"),
                "asunto": headers.get("Subject"),
                "fecha": headers.get("Date"),
                "snippet": full.get("snippet"),
            })
        return json.dumps(resumen, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def leer_correo(mensaje_id: str) -> str:
    try:
        svc = _service()
        full = svc.users().messages().get(userId="me", id=mensaje_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}

        def _extract(payload):
            if payload.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            for part in payload.get("parts", []) or []:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            for part in payload.get("parts", []) or []:
                text = _extract(part)
                if text:
                    return text
            return ""

        cuerpo = _extract(full.get("payload", {}))
        return json.dumps({
            "id": mensaje_id,
            "de": headers.get("From"),
            "para": headers.get("To"),
            "asunto": headers.get("Subject"),
            "fecha": headers.get("Date"),
            "cuerpo": cuerpo,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> str:
    try:
        svc = _service()
        msg = MIMEText(cuerpo, _charset="utf-8")
        msg["to"] = destinatario
        msg["subject"] = asunto
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return json.dumps({"ok": True, "id": sent.get("id")}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


SCHEMAS = [
    {
        "name": "listar_correos",
        "description": "Lista correos del buzón del obrador, opcionalmente filtrando con sintaxis Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Filtro estilo Gmail. Ej.: 'from:cliente@dominio.com', 'is:unread', 'subject:pedido'. Vacío para últimos mensajes.",
                },
                "max_resultados": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Cantidad máxima de mensajes a devolver.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "leer_correo",
        "description": "Lee el contenido completo de un correo a partir de su ID (obtenido con listar_correos).",
        "input_schema": {
            "type": "object",
            "properties": {
                "mensaje_id": {"type": "string", "description": "ID del mensaje de Gmail."}
            },
            "required": ["mensaje_id"],
        },
    },
    {
        "name": "enviar_correo",
        "description": "Envía un correo desde la cuenta del obrador. Confirmá el contenido con el usuario antes de llamar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "destinatario": {"type": "string", "description": "Dirección de email del destinatario."},
                "asunto": {"type": "string"},
                "cuerpo": {"type": "string", "description": "Contenido en texto plano."},
            },
            "required": ["destinatario", "asunto", "cuerpo"],
        },
    },
]

HANDLERS = {
    "listar_correos": listar_correos,
    "leer_correo": leer_correo,
    "enviar_correo": enviar_correo,
}
