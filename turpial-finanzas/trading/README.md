# EAs: la estrategia de Ornstein-Uhlenbeck en MT5 y NinjaTrader

Tres implementaciones de la misma matemática que vive en [`../quant/`](../quant), listas
para pasar por un tester:

| Archivo | Plataforma | Qué hace |
|---|---|---|
| [`mt5/OU_MeanReversion_EA.mq5`](./mt5/OU_MeanReversion_EA.mq5) | MetaTrader 5 | Reversión a la media sobre un símbolo (FX, índices, CFDs) |
| [`mt5/OU_PairsTrading_EA.mq5`](./mt5/OU_PairsTrading_EA.mq5) | MetaTrader 5 | Arbitraje estadístico de dos símbolos cointegrados |
| [`ninjatrader/OUMeanReversion.cs`](./ninjatrader/OUMeanReversion.cs) | NinjaTrader 8 | Lo mismo, para **futuros** (ES, NQ, MES, MNQ, CL, GC…) en cuenta demo |

La matemática común está en [`mt5/Include/OUMath.mqh`](./mt5/Include/OUMath.mqh) (MQL5) y
en la región `PORTABLE MATH` del archivo de NinjaTrader (C#).

---

## Qué está verificado y qué no

Esto importa antes que cualquier instrucción de instalación.

**Verificado, ejecutando código:**

```bash
python trading/tests/verify_ports.py
```

Extrae la matemática real de los dos archivos (no una copia), la compila —MQL5 como C++
con shims mínimos, C# con `mcs`— y exige que produzca **los mismos números que el motor de
Python** dentro de 1e-9, sobre 4 series de prueba y 301 ventanas móviles consecutivas.
Cubre: calibración del OU, half-life, z-score, estadístico de Dickey-Fuller, la cadena de
Markov con su test chi-cuadrado, las reglas de posición y —lo más importante— la
convención de ventana móvil, que es donde se escondería un off-by-one que en el tester
aparecería como rentabilidad venida del futuro.

Y el motor de Python, a su vez, está validado contra procesos simulados con parámetros
conocidos en `tests/test_quant.py`.

**NO verificado, y no puedo verificarlo desde acá:** la capa de ejecución. Envío de
órdenes, normalización de lotes, llenado, `stops level` del bróker, sesiones de futuros,
comportamiento en cuentas hedging vs netting. Nada de eso se compila ni se corre sin
MetaEditor y NinjaTrader. **Pasalos primero por el tester en demo y leé el diario de
operaciones**; si el bróker rechaza una orden, el motivo va a estar ahí.

Para cerrar el círculo sobre datos reales del tester:

```bash
# 1) poné InpDiagnosticoCSV = true y corré el tester
# 2) el CSV queda en la carpeta Files del agente
python trading/tests/compare_ea_csv.py OU_diag_EURUSD_PERIOD_H1.csv --ventana 250
```

Recalcula cada ventana con el motor de Python sobre los precios que usó el tester y
compara columna por columna.

---

## MetaTrader 5

### Instalación

1. En MT5: **Archivo > Abrir carpeta de datos**.
2. Copiar `OU_MeanReversion_EA.mq5` y `OU_PairsTrading_EA.mq5` a `MQL5\Experts\`.
3. Copiar `Include\OUMath.mqh` a `MQL5\Experts\Include\` (junto a los `.mq5`, respetando
   la subcarpeta `Include`: los EAs lo incluyen con ruta relativa).
4. Abrir cada `.mq5` en MetaEditor y compilar (**F7**). Debe compilar sin errores.

### Correr el tester

**Ctrl+R** para abrir el Probador de estrategias.

| Ajuste | Recomendado | Por qué |
|---|---|---|
| Símbolo | EURUSD, GBPUSD, USDJPY, índices | El FX intradiario revierte más que una acción suelta |
| Período | M15 o H1 | Con la ventana de 250 son ~2,5 meses (M15) o ~10 meses (H1) de calibración |
| Modelado | **Sólo precios de apertura** si `InpStopDuroATR = 0` | El EA decide únicamente al cierre de barra: ese modelado es *exacto* para él, y corre en segundos |
| Modelado | **1 minuto OHLC** o ticks reales si usás stop duro | Un ST intrabarra necesita que el tester recorra la barra |
| Spread | Real / variable | Con spread fijo optimista el edge de reversión aparece de la nada |
| Depósito | Realista para el lote | Con 0.10 lotes en FX, USD 10.000 es razonable |

Ojo con las **comisiones**: el tester sólo las cobra si el símbolo las tiene configuradas.
En cuentas ECN eso es la mitad del costo, y esta estrategia opera seguido. Si tu símbolo de
prueba no las modela, el resultado está inflado.

### Parámetros que importan de verdad

| Parámetro | Default | Qué hace |
|---|---|---|
| `InpVentana` | 250 | Barras de calibración. Más corto = se adapta más rápido y estima peor |
| `InpExigirDF` | **true** | Sólo opera si Dickey-Fuller rechaza la raíz unitaria al 5% |
| `InpEntradaZ` / `InpSalidaZ` / `InpStopZ` | 1.5 / 0.5 / 3.0 | Umbrales del z-score |
| `InpMaxHoldHL` | 3.0 | Cierra a los 3 half-lives sin reversión |
| `InpUsarRegimen` | true | Filtro de Markov: no comprar dentro de una tendencia bajista persistente |
| `InpStopDuroATR` | 0 | Red de seguridad en múltiplos de ATR (0 = sin stop de orden) |

### Si el EA no abre ni una operación

Es el caso más probable en muchos símbolos, y **suele ser el comportamiento correcto**. El
diario lo dice con todas las letras:

```
Sin reversión operable: Dickey-Fuller -1.42 no rechaza la raíz unitaria al 5%
(crítico -2.86): el half-life de 88.3 barras es un artefacto de la muestra
```

Toda serie finita produce un half-life. El gate estadístico existe justamente para no
operar el ruido. Antes de poner `InpExigirDF = false`, entendé que lo que estás apagando
es la pregunta "¿esto revierte de verdad?" — y que la respuesta que estabas ignorando era
"no". Si lo apagás igual, hacelo para *ver* qué pasa, no para creerle al resultado.

### El EA de pares

`OU_PairsTrading_EA.mq5` va sobre el gráfico del símbolo A, con el B en `InpSymbolB`.
Ambos tienen que estar en el Observador de Mercado y con historial descargado. Candidatos
razonables: `EURUSD`/`GBPUSD`, `AUDUSD`/`NZDUSD`, `XAUUSD`/`XAGUSD`, `USDCAD`/`CL`.

Cada barra recalcula el hedge ratio β por regresión de cointegración, testea el spread con
los valores críticos de **Engle-Granger** (más exigentes que Dickey-Fuller porque β se
estimó de los mismos datos) y opera el z-score del spread. Las patas se dimensionan por
valor nocional para que el par quede neutral al movimiento común, y si la segunda pata es
rechazada se revierte la primera: media posición deja de ser un par y pasa a ser una
apuesta direccional.

Dos advertencias del tester multi-símbolo: usá **1 minuto OHLC** o ticks reales (con
"sólo aperturas" el segundo símbolo se sincroniza mal), y tené en cuenta que el costo se
paga **dos veces por trade**, una por pata.

---

## NinjaTrader 8 (futuros)

### Instalación

1. Copiar `OUMeanReversion.cs` a `Documents\NinjaTrader 8\bin\Custom\Strategies\`.
2. En NinjaTrader: **New > NinjaScript Editor**, abrir el archivo y compilar con **F5**.
3. La estrategia aparece como `OUMeanReversion` en Strategies y en el Strategy Analyzer.

### Backtest y demo

- **Backtest**: Control Center > **New > Strategy Analyzer**, elegir el instrumento
  (ES, NQ, MES, MNQ, CL, GC), el período y la estrategia. `IncludeCommission` ya viene en
  `true`: en futuros la comisión por vuelta es una parte real del resultado.
- **Demo**: Control Center > **Strategies**, cuenta **Sim101**, instrumento y timeframe, y
  Enable. Sim101 es la cuenta simulada que trae NinjaTrader.
- **Datos**: para intradiario hace falta un feed en tiempo real (la conexión demo de tu
  bróker, o una prueba de Continuum). El feed gratuito de Kinetick es sólo fin de día, o
  sea sólo barras diarias.

Para probar sin arriesgar tamaño, usá los **micros** (MES, MNQ): un tick de MES vale USD
1,25 contra USD 12,50 del ES.

### Detalles propios de futuros

- `IsExitOnSessionCloseStrategy = true` y `ExitOnSessionCloseSeconds = 60`: no deja
  posición abierta al cierre de sesión. Para una estrategia de reversión con horizonte de
  varias barras esto **corta trades por reloj**, no por modelo — miralo en la lista de
  operaciones antes de sacar conclusiones.
- `UsarHorario` restringe las aperturas a una franja (por ejemplo 0930–1545 para el RTH del
  ES). Los cierres se ejecutan siempre, dentro o fuera de la franja.
- `StopTicks` es una red de seguridad en ticks, además del stop por z-score.
- Rollover: al pasar de contrato el precio salta. Usá series continuas ajustadas o
  reiniciá la calibración después del rollover; si no, el salto entra en la ventana y
  contamina μ.

---

## Qué esperar antes de abrir el tester

No quiero que descubras esto después de una tarde de optimización.

**EURUSD y GBPUSD en H1, 2 años, costo 1 bp** (la misma lógica del EA, corrida con
`quant/`):

| Símbolo | Gate DF | Trades | Exposición | Sharpe | t | Retorno | Max DD |
|---|---|---|---|---|---|---|---|
| EURUSD H1 | **ON** | 38 | 1,1 % | +1,38 | 1,38 | +1,57 % | 0,30 % |
| EURUSD H1 | off | 360 | 28,7 % | −0,06 | −0,08 | −0,46 % | 7,51 % |
| GBPUSD H1 | **ON** | 42 | 1,1 % | −0,08 | −0,11 | −0,10 % | 0,58 % |
| GBPUSD H1 | off | 424 | 29,6 % | −0,57 | −0,74 | −4,27 % | 5,32 % |

Ninguno llega a significancia: el mejor caso (EURUSD con gate) tiene **t = 1,38**, o sea
p = 0,17. Con 2 años de muestra el error estándar de un Sharpe es ≈ 0,7, así que un +1,38
no se distingue de cero.

Y eso es sólo la punta. El escaneo completo —12 instrumentos × 4 timeframes, 48 pruebas—
está en [`../docs/resultados.md`](../docs/resultados.md). El resumen:

- **Ninguna de las 48 pruebas alcanza p < 0,05**, ni siquiera nominal (el azar debería
  regalar 2,4). Cero sobreviven Bonferroni o Benjamini-Hochberg.
- El **Sharpe medio es −1,24 con t = −2,87**: lo único significativo del experimento es
  que la estrategia pierde plata.
- **A costo cero el Sharpe medio es −0,11 con t = −0,33**, 21 de 48 positivos. No es que
  los costos se coman el edge: no hay edge.
- Cuanto más bajo el timeframe, peor. En 5 minutos se opera 3× más y se pierde 8× más.

El gate hace lo que promete —baja la exposición de 28 % a 1,7 % y corta el sangrado—, pero
a costo cero **es peor** que sin gate: las ventanas donde Dickey-Fuller rechaza no son
mejores que el promedio. Ayuda operando menos, no operando mejor.

Si tu resultado en el tester sale mucho mejor que esto, la primera hipótesis a descartar es
que el spread esté modelado de forma optimista.

---

## Cómo leer un resultado

1. **¿Cuántas operaciones?** Con menos de 30, cualquier métrica es anécdota. Por eso
   `OnTester()` en MT5 devuelve 0 si hubo menos de `InpMinTradesFit`.
2. **¿Contra qué?** Comparalo con comprar y mantener en el mismo período. Un Sharpe de 0,5
   no vale nada si el buy & hold dio 0,9.
3. **¿Sobrevive a los costos?** Subí el spread y la comisión y volvé a correr. Si el
   resultado se da vuelta con costos realistas, el edge era el modelado, no el mercado.
4. **¿Sobrevive fuera de muestra?** Optimizar 6 parámetros sobre 2 años encuentra oro
   siempre. Usá walk-forward, o al menos reservá un tramo final que no mirás hasta el final.
5. **¿El gate estaba activado?** Un resultado con `InpExigirDF = false` describe qué pasa
   cuando se ignora la estadística. Es información, no una estrategia.

---

Esto es investigación cuantitativa, **no** asesoramiento de inversión. Ninguno de estos
programas fue probado con dinero real, y pasar un backtest no es evidencia de que vaya a
funcionar mañana.
