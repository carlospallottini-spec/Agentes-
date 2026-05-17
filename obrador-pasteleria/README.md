# Obrador de Pastelería — Asistente social

Servicio web que responde mensajes de WhatsApp e Instagram para el **Obrador de Pastelería**, usando Claude (`claude-opus-4-7`) para entender al cliente y herramientas internas para mostrar menú, tomar pedidos y agendar entregas.

## Qué hace

- Atiende DMs de Instagram y mensajes de WhatsApp Business.
- Recuerda la conversación de cada cliente por separado (persistida en `data/conversations.json`).
- Muestra el menú (`data/menu.json`), consulta horarios, registra pedidos inmediatos y agenda pedidos futuros.
- Confirma datos antes de cerrar un pedido y recuerda las 24 hs mínimas para tortas.

## Estructura

```
obrador-pasteleria/
├── webhooks.py          # FastAPI: rutas /webhook/whatsapp y /webhook/instagram
├── agent.py             # Loop de Claude con tool use
├── conversations.py     # Persistencia de historial por usuario
├── whatsapp.py          # Cliente WhatsApp Cloud API
├── instagram.py         # Cliente Instagram Messaging API
├── tools/
│   ├── menu_tools.py    # mostrar_menu, consultar_horarios
│   └── order_tools.py   # tomar_pedido, agendar_pedido, listar_pedidos
├── data/
│   └── menu.json        # Catálogo
├── main.py              # Entry para correr local con uvicorn
├── Procfile             # Para Render/Heroku-style hosts
├── railway.json         # Config Railway
├── requirements.txt
└── .env.example
```

## Variables de entorno

Copiá `.env.example` a `.env` (local) o configuralas en tu hosting:

| Variable | De dónde sacarla |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |
| `META_VERIFY_TOKEN` | Inventalo: cadena aleatoria larga (ej. `obrador-2026-X9K2`) |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta for Developers → App → WhatsApp → API Setup |
| `WHATSAPP_ACCESS_TOKEN` | Meta Business Settings → System Users → genera token con permiso `whatsapp_business_messaging` |
| `INSTAGRAM_ACCOUNT_ID` | Graph API Explorer: `GET /me/accounts` → tu página → `instagram_business_account.id` |
| `INSTAGRAM_ACCESS_TOKEN` | Page Access Token de la página de Facebook vinculada |
| `PORT` | Lo inyecta el hosting; en local default 8000 |

## Deploy en Railway

1. Andá a https://railway.com/new y elegí **Deploy from GitHub repo** → seleccioná `carlospallottini-spec/agentes-`.
2. En **Settings → Service → Root Directory** poné `obrador-pasteleria`.
3. En **Variables** pegá las 7 variables de la tabla anterior.
4. Railway detecta `railway.json` y deploya. Esperá a que termine y copiá la URL pública (algo como `https://obrador-pasteleria.up.railway.app`).
5. Verificá que `https://<tu-url>/` devuelva `{"status": "ok", "bakery": "obrador-pasteleria"}`.

## Configurar webhook de WhatsApp en Meta

1. https://developers.facebook.com/apps → tu app → **WhatsApp → Configuration**.
2. **Callback URL**: `https://<tu-url-railway>/webhook/whatsapp`
3. **Verify token**: el mismo valor que pusiste en `META_VERIFY_TOKEN`.
4. Click **Verify and save**.
5. En **Webhook fields**, suscribite a `messages`.

## Configurar webhook de Instagram en Meta

1. https://developers.facebook.com/apps → tu app → **Webhooks → Instagram** (o **Messenger** según el setup).
2. **Callback URL**: `https://<tu-url-railway>/webhook/instagram`
3. **Verify token**: el mismo `META_VERIFY_TOKEN`.
4. Suscribite al field `messages`.
5. En **Instagram → API Setup**, conectá la cuenta Business y autorizá la app.

## Probar local con ngrok

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # editá y pegá tus credenciales
python main.py                       # arranca en localhost:8000
```

En otra terminal:
```bash
ngrok http 8000
```

Usá la URL HTTPS de ngrok como Callback URL en Meta (mismos pasos de webhook anteriores).

## Editar el menú

Modificá `data/menu.json` y redeployá. La estructura es:

```json
{
  "categorias": {
    "tortas": [
      {"id": "T01", "nombre": "...", "descripcion": "...", "porciones": 10, "precio": 18000}
    ]
  },
  "horarios": { ... },
  "tiempo_minimo_pedido_torta_horas": 24,
  "notas": "..."
}
```

## Ver pedidos

Los pedidos se persisten en `data/orders.json` dentro del contenedor. En Railway podés ver el archivo con el shell del servicio, o exportarlos con un endpoint si lo necesitás.
