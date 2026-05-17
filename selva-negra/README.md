# Selva Negra Pastelería — Asistente social

Servicio web que responde mensajes de WhatsApp e Instagram para **Selva Negra Pastelería** (clásicos alemanes: Selva Negra, Sachertorte, Apfelstrudel, Stollen, Brezel, etc.), usando Claude (`claude-opus-4-7`).

## Qué hace

- Atiende DMs de Instagram y mensajes de WhatsApp Business.
- Recuerda la conversación de cada cliente por separado (persistida en `data/conversations.json`).
- Muestra el menú (`data/menu.json`), consulta horarios, registra pedidos inmediatos y agenda pedidos futuros.
- Confirma datos antes de cerrar un pedido y recuerda las **48 hs mínimas** para tortas Selva Negra y Sachertorte.

## Estructura

```
selva-negra/
├── webhooks.py          # FastAPI: rutas /webhook/whatsapp y /webhook/instagram
├── agent.py             # Loop de Claude con tool use
├── conversations.py     # Persistencia de historial por usuario
├── whatsapp.py          # Cliente WhatsApp Cloud API
├── instagram.py         # Cliente Instagram Messaging API
├── tools/
│   ├── menu_tools.py
│   └── order_tools.py
├── data/
│   └── menu.json
├── main.py
├── Procfile
├── railway.json
├── requirements.txt
└── .env.example
```

## Variables de entorno

| Variable | De dónde sacarla |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |
| `META_VERIFY_TOKEN` | Inventalo: cadena aleatoria larga |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta for Developers → App → WhatsApp → API Setup |
| `WHATSAPP_ACCESS_TOKEN` | System User token con permiso `whatsapp_business_messaging` |
| `INSTAGRAM_ACCOUNT_ID` | Graph API Explorer: `GET /me/accounts` → página → `instagram_business_account.id` |
| `INSTAGRAM_ACCESS_TOKEN` | Page Access Token de la página vinculada |
| `PORT` | Lo inyecta el hosting; en local default 8000 |

> ⚠️ Usá una **app de Meta Developers distinta** a la del Obrador (o al menos números de WhatsApp e IG Business separados) para que los dos negocios respondan desde sus propias cuentas.

## Deploy en Railway

1. https://railway.com/new → **Deploy from GitHub repo** → seleccioná `carlospallottini-spec/agentes-`.
2. **Settings → Service → Root Directory** = `selva-negra`.
3. **Variables** → pegá las 7 de la tabla.
4. Railway lee `railway.json` y deploya. Copiá la URL pública.
5. `GET https://<tu-url>/` debe devolver `{"status": "ok", "bakery": "selva-negra"}`.

## Webhook WhatsApp en Meta

1. https://developers.facebook.com/apps → tu app → **WhatsApp → Configuration**.
2. Callback URL: `https://<tu-url-railway>/webhook/whatsapp`
3. Verify token: el mismo `META_VERIFY_TOKEN`.
4. Suscribite a `messages`.

## Webhook Instagram en Meta

1. App → **Webhooks → Instagram**.
2. Callback URL: `https://<tu-url-railway>/webhook/instagram`
3. Verify token: el mismo `META_VERIFY_TOKEN`.
4. Suscribite a `messages`.
5. **Instagram → API Setup**: conectá la cuenta Business.

## Probar local con ngrok

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python main.py                       # localhost:8000
ngrok http 8000                      # otra terminal
```

## Editar el menú

`data/menu.json`. Categorías actuales: `tortas_clasicas`, `tortas_modernas`, `panaderia`, `individuales`.
