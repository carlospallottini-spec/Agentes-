# Turpial Finanzas 🦜📈

Plataforma tipo **oráculo** con agentes de Wall Street que generan **Risk Scores**
sobre empresas a partir de **filings primarios** (10-Q, 10-K, 8-K), fundamentales
XBRL, precio de mercado e insiders (Form 4). Cada análisis se entrega como un
**dashboard HTML autocontenido** (un archivo, gráficos en Canvas puro, mobile-first,
sin dependencias externas).

El oráculo corre los agentes en **cadencia diaria / semanal / mensual** y se
**adelanta a los earnings**: detecta cuándo una empresa va a reportar y dispara el
análisis unos días antes.

## El framework de Risk Score

Tres pilares, escala **0-100, mayor puntaje = menor riesgo**:

| Pilar | Peso | Qué mide |
|---|---|---|
| **Valuación** | 35% | P/E, P/S, P/B, FCF yield |
| **Salud Financiera** | 35% | Liquidez, deuda/patrimonio, cobertura de intereses, deuda neta/EBITDA, ROE, margen neto |
| **Crecimiento** | 30% | CAGR de ingresos y de EPS |

**Bandas:** 0-30 Alto · 30-55 Elevado · 55-75 Moderado · 75-90 Bajo-Mod · 90-100 Bajo Riesgo.

**Badges por métrica:**
- 🟢 **Ancla** — fundamental, alta convicción.
- 🟡 **Flex** — útil pero volátil.
- 🔴 **Alerta** — la métrica que el management preferiría que ignoraras.

El **score se calcula de forma determinística** desde los datos primarios; el agente
Claude (`claude-opus-4-7`) agrega la **narrativa**, ajusta los badges según el negocio,
enumera **trade-offs** y es **honesto sobre lo que no se puede saber** con información pública.

## Cómo se usa

```bash
pip install -r requirements.txt
cp .env.example .env   # poné tu ANTHROPIC_API_KEY y SEC_USER_AGENT

# Análisis de un ticker (genera el dashboard HTML)
python turpial.py AAPL                 # con narrativa de Claude
python turpial.py AAPL --no-narrative  # solo score determinístico (sin API key)

# Cadencias del oráculo (leen data/watchlist.json)
python turpial.py --cadence diario
python turpial.py --pre-earnings       # analiza lo que reporta pronto
```

El dashboard se escribe en `data/reports/<TICKER>_<fecha>.html`. Abrilo en el navegador
(o en el celular) — es un único archivo sin dependencias.

## El servicio web (oráculo)

```bash
python main.py        # uvicorn en :8000
```

| Endpoint | Qué hace |
|---|---|
| `GET /` | Índice de reportes generados |
| `GET /analyze/{ticker}` | Genera y devuelve el dashboard HTML en vivo |
| `GET /api/score/{ticker}` | Score + pilares en JSON |
| `GET /api/earnings/{ticker}` | Próxima fecha de earnings (estimada) |
| `GET /report/{ticker}` | Último dashboard guardado |
| `POST /cron/{cadencia}` | Dispara una cadencia (`diario`/`semanal`/`mensual`/`pre-earnings`) |

El endpoint `/cron` se protege con el header `X-Cron-Token` (variable `CRON_TOKEN`).
La cadencia la dispara un **cron externo** (Railway Cron, GitHub Actions o systemd-timer),
así el servicio web queda liviano.

## Fuentes de datos — honestidad sobre lo que existe

El brief pedía conectarse a varias plataformas. La realidad de las APIs:

| Fuente | API pública | Estado en Turpial |
|---|---|---|
| **SEC EDGAR** | ✅ gratis | **Real** — filings, fundamentales XBRL e insiders (Form 4) |
| **Yahoo / Stooq** | ✅ gratis | **Real** — precio actual de mercado |
| TIKR | ❌ | Adapter con hook `TIKR_API_KEY` (sin key → `no_data`) |
| Koyfin | ❌ | Adapter con hook `KOYFIN_API_KEY` |
| JustETF | ❌ (ToS) | Adapter — sin scraping; aporte manual |
| Microcap Club | ❌ (cerrado) | Comunidad paga — aporte manual |
| Value Invest Club | ❌ (cerrado) | Comunidad cerrada — aporte manual |
| Dataroma | ❌ oficial | 13F públicos pero frágil; para insiders usamos Form 4 (primario) |
| Wisdom | ❌ | Adapter — integración manual |

> **Importante:** TIKR, Koyfin, JustETF, Microcap Club, Value Invest Club, Dataroma y
> Wisdom **no exponen APIs públicas** (son plataformas pagas o comunidades cerradas).
> Turpial **no inventa** esos datos: deja conectores con interfaz lista y hooks de API
> key, y construye el motor real sobre fuentes **primarias y verificables** (SEC + precio).
> Esto respeta la propia directriz del brief: *"Sé honesto sobre lo que no se puede saber
> con información pública."*

## Arquitectura

```
turpial.py / app.py            ← CLI y servicio web (el oráculo)
   ↓
oracle/        scheduler · earnings · store     (cadencia, calendario, persistencia)
   ↓
agents/        risk_score · scoring · prompts   (agente de Wall Street + framework)
   ↓
connectors/    sec_edgar · prices · insiders · premium
   ↓
dashboard/     render            (HTML autocontenido, Canvas puro, mobile-first)
```

## Deploy en Railway

1. Deployá esta carpeta como un servicio. `railway.json` ya define el `startCommand`.
2. Variables de entorno: `ANTHROPIC_API_KEY`, `SEC_USER_AGENT`, `CRON_TOKEN`.
3. Agregá un **Railway Cron** que haga `POST /cron/diario`, `/cron/semanal`,
   `/cron/mensual` y `/cron/pre-earnings` con el header `X-Cron-Token`.

## Aviso

Turpial Finanzas es una herramienta de investigación. **No es recomendación de
inversión.** Verificá siempre los números contra los documentos originales de la SEC.
