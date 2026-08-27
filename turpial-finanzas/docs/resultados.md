# Resultados: ¿hay reversión a la media operable?

Este documento existe porque un repo de trading sin resultados medidos es una demo. Acá
está todo lo que el motor encontró, **incluido lo que no funcionó** — que es casi todo.

Reproducible:

```bash
python research/escaneo.py --modo pares --guardar
python research/escaneo.py --modo intradiario --sensibilidad --guardar
python research/escaneo.py --modo intradiario --gate --sensibilidad --guardar
```

Los JSON crudos quedan en [`research/resultados/`](../research/resultados).

---

## Cómo se evita el autoengaño

Tres reglas, aplicadas antes de mirar ningún número:

**1. Los parámetros están fijos.** Ventana 250, entrada z=1,5, salida 0,5, stop 3,0, cierre
a 3 half-lives, filtro de régimen activo. Los mismos para los 68 casos. No se optimizó
nada: buscar el mejor de una tabla grande siempre encuentra algo.

**2. Cada Sharpe viene con su error estándar.** Un Sharpe estimado sobre T años tiene
SE ≈ √((1 + S²/2)/T) — Lo (2002). Esto es brutal con muestras cortas: **un Sharpe de 2,0
medido sobre 2 meses tiene t = 0,46 y p = 0,64.** Muestrear más seguido no ayuda; lo que
manda es el tiempo calendario.

**3. Se corrige por múltiples pruebas.** Con 48 tests al 5 %, el azar regala 2,4
ganadores. Se reportan Bonferroni (p < α/N) y Benjamini-Hochberg (FDR).

---

## Experimento 1 — Pares cointegrados, velas diarias, 5 años

20 pares candidatos (EWA/EWC, KO/PEP, MA/V, XOM/CVX, GS/MS, …).

| Métrica | Valor |
|---|---|
| Sharpe medio | **+0,072** (desvío 0,502) |
| t de la media | **+0,65** — se necesita \|t\| > 2 |
| Positivos | 11 / 20 |
| p < 0,05 nominal | **0** (esperados por azar: 1,0) |
| Sobreviven Bonferroni / BH | **0 / 0** |
| Cointegrados al 5 % | 2 de 20 (esperados por azar: **1,0**) |

Sólo 2 de 20 pasan Engle-Granger, y el azar regala 1. De esos dos, uno da Sharpe −0,46
(EWA/EWC) y el otro +0,52 (MA/V): una moneda.

**El detalle que más enseña:** los mejores backtests del escaneo — PG/CL (Sharpe 0,98,
+29,8 %) y USO/XLE (+34,8 %) — **fallaron el test de cointegración**. Si ordenás la tabla
por retorno y elegís el de arriba, estás eligiendo pares que la estadística dice que no
tienen relación. Ese es el mecanismo del sobreajuste, en una tabla de 20 filas.

## Experimento 2 — Timeframes bajos

12 instrumentos (FX, crypto, futuros, ETFs) × 4 timeframes. 5m/15m/30m sobre 59 días
—el máximo que sirve Yahoo—, 1h sobre 2 años. Costo base 1 bp por cambio de posición.

| | Sin gate | Con gate Dickey-Fuller |
|---|---|---|
| Sharpe medio | −1,47 | −1,24 |
| t de la media | **−3,16** | **−2,87** |
| Positivos | 11 / 48 | 18 / 48 |
| p < 0,05 nominal | 0 (esperados 2,4) | 0 (esperados 2,4) |
| Sobreviven Bonferroni / BH | 0 / 0 | 0 / 0 |
| Trades totales | 11.590 | 1.842 |
| Exposición media | 28 % | 1,7 % |

Ningún caso llega siquiera a significancia **nominal**. Y el promedio es negativo **con
t = −3,16**: eso sí es significativo. La estrategia no es neutra a estos timeframes, es
destructiva.

Por timeframe (sin gate, 1 bp):

| TF | Sharpe medio | Positivos | Trades | Ventanas que pasan el gate |
|---|---|---|---|---|
| 5m | −3,58 | 1/12 | 4.846 | 10,6 % |
| 15m | −0,43 | 4/12 | 1.568 | 7,6 % |
| 30m | −1,46 | 5/12 | 624 | 5,9 % |
| 1h | −0,42 | 1/12 | 4.552 | 5,6 % |

Cuanto más bajo el timeframe, peor. En 5 minutos se opera 3× más y se pierde 8× más.

### La pregunta decisiva: ¿es la señal o son los costos?

Repitiendo el mismo universo a distintos costos:

| Costo | Sharpe medio (sin gate) | t | Positivos |
|---|---|---|---|
| **0 bps** | **−0,11** | −0,33 | 21 / 48 |
| 1 bp | −1,47 | −3,16 | 11 / 48 |
| 2 bps | −2,79 | −4,06 | 8 / 48 |
| 5 bps | −6,23 | −4,88 | 5 / 48 |

**A costo cero el Sharpe medio es −0,11 con t = −0,33, y 21 de 48 son positivos.** O sea:
una moneda centrada en cero. No es que los costos se coman un edge — **no hay edge que
comer**. Los costos después convierten el cero en pérdida.

Esta distinción importa. Si a costo cero hubiera salido +1,5 y a 1 bp −1,5, la conclusión
sería "hay señal, pero está por debajo del piso de costos: buscá ejecución más barata".
No es el caso.

### Qué hace el gate en realidad

Con el gate activo se opera el 1,7 % del tiempo en vez del 28 %, y el Sharpe medio mejora
de −1,47 a −1,24. Pero **a costo cero el gate es peor** (−0,32 contra −0,11). O sea: las
ventanas donde Dickey-Fuller rechaza no son mejores que el promedio. El gate ayuda
**operando menos**, no operando mejor.

Es un resultado menos halagador que el que conté antes de medirlo así, y es el correcto.

### El límite duro de este experimento

Con 59 días de datos, T = 0,16 años y el error estándar de cualquier Sharpe es ≈ 2,5.
**Nada por debajo de un Sharpe de 5 es detectable con esta muestra.** Yahoo no da más
profundidad en velas de 5 minutos, así que esto no se arregla escaneando más
instrumentos: hace falta otra fuente de datos.

Lo que sí queda establecido con la muestra que hay: no hay ningún efecto **grande**. Un
edge chico sigue siendo indetectable acá — y también sería indetectable en tu tester.

---

## Conclusión

Sobre acciones, ETFs, FX, crypto y futuros, en velas de 5 minutos a diarias, con costos
realistas: **no encontré reversión a la media operable.** Los tests de Dickey-Fuller y
Engle-Granger rechazan casi siempre, y donde no rechazan el backtest tampoco paga.

Eso no invalida el motor. La calibración recupera θ, μ y σ de procesos simulados con menos
de 10 % de error, los tres ports coinciden en 1e-9, y sobre una serie que *es* un
Ornstein-Uhlenbeck la estrategia da Sharpe 1,65. El modelo funciona; lo que no se cumple es
su supuesto. Los precios de estos mercados, a estas frecuencias, no son procesos de
Ornstein-Uhlenbeck.

Lo que sí quedó demostrado, y tiene valor: **la infraestructura detecta correctamente la
ausencia de señal.** El gate apagado opera el 96 % del tiempo y pierde de forma
consistente; encendido se queda afuera. Eso es lo que separa una herramienta de
investigación de un generador de backtests lindos.

### Dónde seguiría buscando

Con honestidad sobre las probabilidades:

- **Datos, antes que ideas.** El cuello de botella no es el modelo, son los 59 días. Con
  años de datos intradiarios (Databento, Polygon, IQFeed) el mismo escaneo pasa de
  anecdótico a concluyente.
- **Arbitraje mecánico, no correlación estadística.** ETF contra su canasta, calendar
  spreads del mismo subyacente, triangulación de FX. Ahí la reversión tiene una causa
  económica, no una regresión que salió bien.
- **Escaneo amplio con FDR desde el principio**, no 20 candidatos elegidos a mano.

Y lo que **no** haría: apagar el gate y optimizar los seis parámetros hasta que la curva
quede linda. Eso siempre encuentra algo, y ese algo nunca sobrevive fuera de muestra.

---

Esto es investigación cuantitativa, **no** asesoramiento de inversión.
