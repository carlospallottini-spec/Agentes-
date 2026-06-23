# Turpial Finanzas 🦜📈

Plataforma de inversión **todo-en-uno**: buscador universal multi-activo, watchlist
editable, gráficos en vivo y un **agente IA** embebido que responde cualquier pregunta
del inversor usando datos reales. Por debajo, un **oráculo** de agentes de Wall Street
genera **Risk Scores** de acciones a partir de filings primarios y corre en cadencia
diaria / semanal / mensual, adelantándose a los earnings.

Todo se sirve desde una sola app (FastAPI + una SPA sin dependencias externas).

## Qué hace la plataforma

- 🔎 **Buscador universal**: escribís "Bitcoin", "oro", "EUR/USD", "S&P 500" o un ticker
  y encontrás el activo, sea cual sea su clase.
- 🧭 **Multi-activo**: acciones, ETFs, bonos (yields), **crypto**, **Forex**,
  **commodities/futuros** e índices — todo con cotización y gráfico en vivo.
- ⭐ **Watchlist**: agregá/quitá activos y monitoreá precios y variación desde un solo lugar.
- 📊 **Gráficos**: precio histórico en Canvas puro, con rangos 1d → max.
- 🤖 **Agente IA del oráculo**: un analista conversacional, **didáctico**, que busca
  símbolos, cotiza, trae historiales, calcula Risk Scores y maneja tu watchlist en vivo.
  Explica cada término técnico y es honesto sobre lo que no se puede saber.
- 🧮 **Risk Score** de acciones (framework de 3 pilares, abajo).

## El framework de Risk Score

Tres pilares, escala **0-100, mayor puntaje = menor riesgo**:

| Pilar | Peso | Qué mide |
|---|---|---|
| **Valuación** | 35% | P/E, P/S, P/B, FCF yield |
| **Salud Financiera** | 35% | Liquidez, deuda/patrimonio, cobertura de intereses, deuda neta/EBITDA, ROE, margen neto |
| **Crecimiento** | 30% | CAGR de ingresos y de EPS |

**Bandas:** 0-30 Alto · 30-55 Elevado · 55-75 Moderado · 75-90 Bajo-Mod · 90-100 Bajo Riesgo.
**Badges:** 🟢 Ancla (alta convicción) · 🟡 Flex (útil pero volátil) · 🔴 Alerta (mirá con lupa).

El score se calcula de forma **determinística** desde los datos primarios; el agente Claude
(`claude-opus-4-7`) agrega narrativa, ajusta badges, expone trade-offs y los límites del análisis.

## Cómo se usa

```bash
pip install -r requirements.txt
cp .env.example .env   # poné ANTHROPIC_API_KEY (para el agente IA) y SEC_USER_AGENT
python main.py         # levanta la plataforma en http://localhost:8000
```

Abrí `http://localhost:8000` y tenés la plataforma completa. El **agente IA** necesita
`ANTHROPIC_API_KEY`; el resto (búsqueda, cotizaciones, gráficos, watchlist, Risk Score)
funciona sin clave de Claude.

También hay CLI para análisis y cadencias:

```bash
python turpial.py AAPL                 # dashboard de Risk Score (HTML autocontenido)
python turpial.py --cadence diario     # corre una cadencia de la watchlist del oráculo
python turpial.py --pre-earnings       # analiza lo que reporta pronto
```

## API

| Endpoint | Qué hace |
|---|---|
| `GET /` | La plataforma (SPA) |
| `GET /api/search?q=` | Búsqueda universal multi-activo |
| `GET /api/quote/{symbol}` | Cotización en vivo (cualquier clase de activo) |
| `GET /api/history/{symbol}?range=` | Serie histórica para graficar |
| `GET/POST/DELETE /api/watchlist` | Lista de seguimiento del inversor |
| `POST /api/chat` | El agente IA (body: `{"messages":[...]}`) |
| `GET /api/score/{ticker}` | Risk Score en JSON |
| `GET /api/earnings/{ticker}` | Próxima fecha de earnings (estimada) |
| `GET /analyze/{ticker}` | Dashboard de Risk Score (HTML autocontenido) |
| `POST /cron/{cadencia}` | Dispara una cadencia del oráculo |

## Fuentes de datos — honestidad sobre lo que existe

| Fuente | API pública | Estado en Turpial |
|---|---|---|
| **Yahoo Finance** | ✅ gratis | **Real** — precio, búsqueda e historial de TODA clase de activo |
| **SEC EDGAR** | ✅ gratis | **Real** — filings, fundamentales XBRL e insiders (Form 4) |
| TIKR / Koyfin | ❌ | Adapter con hook de API key (sin key → `no_data`) |
| JustETF / Microcap Club / Value Invest Club / Dataroma / Wisdom | ❌ | Sin API pública (pagas/cerradas); integración manual |

> TIKR, Koyfin, JustETF, Microcap Club, Value Invest Club, Dataroma y Wisdom **no exponen
> APIs públicas**. Turpial **no inventa** esos datos: deja conectores con interfaz lista y
> construye el motor real sobre fuentes **primarias y verificables**. Para "insiders" usa
> **Form 4 de la SEC**, que es la fuente primaria y legal.
>
> Nota: el endpoint de **opciones** de Yahoo hoy requiere un *crumb* de sesión y suele
> devolver 401, así que esa clase queda como mejora futura (cadenas de opciones).

## Arquitectura

```
web/index.html                 ← la plataforma (SPA, Canvas puro, sin dependencias)
app.py                         ← FastAPI: sirve la SPA + APIs (búsqueda, cotización, chat, score)
   ↓
agents/   oracle_chat (agente IA conversacional) · risk_score · scoring · prompts
oracle/   scheduler · earnings · store · watchlist
connectors/  market (Yahoo multi-activo) · sec_edgar · prices · insiders · premium
dashboard/  render            ← dashboard de Risk Score (HTML autocontenido)
```

## Deploy en Railway

1. Deployá esta carpeta como un servicio. `railway.json` ya define el `startCommand`.
2. Variables: `ANTHROPIC_API_KEY`, `SEC_USER_AGENT`, `CRON_TOKEN`.
3. Agregá un Railway Cron que haga `POST /cron/{diario|semanal|mensual|pre-earnings}`
   con el header `X-Cron-Token`.

## Aviso

Turpial Finanzas es una herramienta de investigación. **No es asesoramiento de inversión.**
Verificá siempre los números contra los documentos originales.
