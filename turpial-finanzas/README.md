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
- 📐 **Motor cuantitativo**: calibra un proceso de **Ornstein-Uhlenbeck** sobre el precio
  (fuerza restauradora, **half-life** y curva de decaimiento), estima **regímenes de
  mercado con cadenas de Markov**, testea **cointegración de pares** y corre backtests
  walk-forward de la estrategia de reversión a la media.

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

## El motor cuantitativo (Ornstein-Uhlenbeck + Markov)

El precio se modela con la ecuación diferencial estocástica

```
dX = θ·(μ − X)·dt + σ·dW
```

donde `θ·(μ − X)·dt` es una **fuerza restauradora** tipo resorte: cuanto más lejos está el
precio de su nivel de equilibrio μ, más fuerte tira de vuelta. Tomando esperanza queda un
decaimiento exponencial de la desviación,

```
E[X_t | X_0] = μ + (X_0 − μ)·e^(−θt)        half-life = ln(2)/θ
```

y el **half-life** es lo que hace operable al modelo: dice en cuántos días se cierra la
**mitad** de la desviación. La plataforma dibuja esa curva de decaimiento con su banda de
±1σ y las marcas de 1, 2 y 3 half-lives (50 % → 25 % → 12,5 %).

| Pieza | Qué hace |
|---|---|
| `quant/ou.py` | Calibra θ, μ, σ por la discretización exacta AR(1); half-life, z-score, curva de decaimiento y test de Dickey-Fuller |
| `quant/markov.py` | Regímenes bajista/lateral/alcista, matriz de transición, distribución estacionaria π, duración de rachas y χ² de memoria |
| `quant/strategies.py` | Reglas de entrada/salida por z-score, corte temporal en múltiplos del half-life y filtro de régimen |
| `quant/backtest.py` | Backtest **walk-forward** (sin look-ahead) con costos, y métricas contra buy & hold |
| `quant/pairs.py` | Cointegración de Engle-Granger, hedge ratio β y OU sobre el spread |
| `quant/scan.py` | Significancia del Sharpe, Bonferroni y Benjamini-Hochberg |
| `quant/engine.py` | Orquesta todo con datos reales de mercado |

### Resultados medidos

El repo no se queda en la demo: [`docs/resultados.md`](./docs/resultados.md) tiene el
escaneo completo —20 pares en velas diarias y 12 instrumentos × 4 timeframes
intradiarios, 68 pruebas— con error estándar del Sharpe (Lo, 2002) y corrección por
múltiples tests (Bonferroni y Benjamini-Hochberg).

El resultado, en una línea: **no se encontró reversión a la media operable en ningún
lado.** Ninguna de las 48 pruebas intradiarias llega a p < 0,05, y a costo cero el Sharpe
medio es −0,11 con t = −0,33. No es que los costos se coman el edge: no hay edge.

```bash
python research/escaneo.py --modo pares --guardar
python research/escaneo.py --modo intradiario --gate --sensibilidad --guardar
```

**Lo importante es lo que el motor se niega a afirmar.** Toda serie finita produce un
half-life; eso no prueba que haya reversión. Cada resultado viene con su test —
Dickey-Fuller para un activo suelto, Engle-Granger para un par— y si no rechaza la hipótesis
de raíz unitaria, el reporte dice que ese half-life es un artefacto de la muestra. Lo mismo
con el régimen: si el χ² no encuentra memoria markoviana, el filtro se desactiva solo.

La matemática completa, con derivaciones y limitaciones, está en
[`docs/quant.md`](./docs/quant.md).

```bash
python turpial.py --quant KO      # OU + Markov + backtest de un activo
python turpial.py --par EWA EWC   # cointegración y OU sobre el spread
python tests/test_quant.py        # 29 tests contra procesos simulados, sin red
```

### Llevarlo a un tester real

La misma matemática está portada a **MetaTrader 5** (dos EAs: un símbolo y pares
cointegrados) y a **NinjaTrader 8** (futuros, cuenta demo), en
[`trading/`](./trading). Los ports no son una reescritura a ojo: `verify_ports.py`
extrae la matemática de los archivos de MQL5 y C#, la compila y exige que dé los mismos
números que `quant/` dentro de 1e-9, incluidas 301 ventanas móviles consecutivas.

```bash
python trading/tests/verify_ports.py     # MQL5 y C# vs. el motor de Python
python trading/tests/compare_ea_csv.py OU_diag_EURUSD_PERIOD_H1.csv --ventana 250
```

En la SPA, el botón **🧮 Quant** de cualquier activo abre el panel con los parámetros
calibrados, la curva de decaimiento, la matriz de transición y el backtest.

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
python turpial.py --quant KO           # análisis estocástico (OU, half-life, Markov)
python turpial.py --par EWA EWC        # cointegración de un par
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
| `GET /api/quant/{symbol}` | OU (θ, μ, half-life, curva de decaimiento) + Markov + backtest |
| `GET /api/quant/par/{a}/{b}` | Cointegración de Engle-Granger + OU sobre el spread |
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
