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

## Experimento 3 — Control positivo: ¿el motor vería un edge si existiera?

Los dos experimentos anteriores dicen "no encontré nada". Eso sólo vale si la maquinaria
sería capaz de encontrar algo. Se puso a prueba con los momentums mejor documentados de la
literatura, 20 años de datos diarios y un **nulo por permutación**: la misma mecánica con
la señal barajada, 200 veces, preservando fechas, costos y covarianzas.

```bash
python research/control_positivo.py --guardar
```

### Meta-control: el motor sí detecta

Primero, sobre datos sintéticos donde el momentum existe **por construcción**:

| Universo | Sharpe | p95 del nulo | p empírico |
|---|---|---|---|
| 9 activos | +2,17 | +0,37 | **0,010** |
| 20 activos | +3,03 | +0,42 | **0,010** |
| 40 activos | +4,93 | +0,43 | **0,010** |

El motor lo encuentra con el p mínimo que permiten 100 permutaciones, y el nulo queda
correctamente centrado en cero. **La maquinaria no es ciega.**

(Un detalle que costó descubrir: con una señal cuya persistencia es *menor* que el
lookback de 252 días, el mismo motor no detecta nada aunque el efecto exista. No es una
falla — es un desajuste entre el horizonte de la señal y el del efecto. Vale como
advertencia para cualquier búsqueda futura.)

### Momentum real: no se distingue del ruido

| Test | Sharpe | t (Lo) | p empírico | Veredicto |
|---|---|---|---|---|
| XSMOM 12-1 · 40 acciones | +0,06 | +0,26 | 0,144 | no detectado |
| XSMOM 12-1 · 9 sectores | +0,10 | +0,43 | 0,129 | no detectado |
| TSMOM 12m · 9 clases de activo | +0,03 | +0,13 | 0,269 | no detectado |

Las 40 acciones tienen **sesgo de supervivencia declarado** —son empresas que existían
hace 20 años y siguen cotizando— y ese sesgo empuja los resultados hacia arriba. Aun así
no alcanza.

**Pero el motor sí está capturando la dinámica real.** El desglose anual del XSMOM:

| Año | Retorno | Sharpe |
|---|---|---|
| 2007 | +11,3 % | 5,13 |
| 2008 | +4,9 % | 0,34 |
| **2009** | **−21,7 %** | **−1,48** |
| 2015 | +8,7 % | 1,72 |
| 2016 | −11,6 % | −2,07 |

Ese −21,7 % de 2009 es el **momentum crash** documentado por Daniel y Moskowitz: cuando el
mercado se dio vuelta en marzo de 2009, la pata corta (los perdedores de 2008) se disparó.
El motor lo reprodujo sin que nadie se lo pidiera. Excluyendo 2009 el Sharpe sube a +0,28
(t = 1,16) — sigue sin ser significativo, pero deja de ser cero.

## Experimento 4 — Régimen de volatilidad: la banda VIX 17-21

Todo lo anterior condicionado por el VIX del cierre del día anterior (el régimen se conoce
antes de ganar el retorno, así que no hay look-ahead). La banda 17-21 ocupa el **21,2 %**
de los últimos 20 años.

| Estrategia | VIX < 17 | **VIX 17-21** | VIX > 21 |
|---|---|---|---|
| XSMOM · 40 acciones | 0,05 | **0,61** | −0,14 |
| XSMOM · 9 sectores | 0,06 | **0,36** | 0,03 |
| TSMOM · 9 clases | 0,29 | 0,15 | −0,12 |
| OU (reversión), sin gate | −0,18 | **−0,04** | −0,39 |

*(Sharpe anualizado dentro de cada régimen.)*

El patrón es coherente con la teoría y aparece en casi todas las filas: **el régimen medio
es el mejor para el momentum cross-sectional, y el peor para todos es el de estrés.** El
XSMOM de 40 acciones pasa de Sharpe 0,05 a **0,61** dentro de la banda — un factor 12. La
reversión a la media, que pierde en todos lados, es "menos mala" justo en 17-21.

Tiene sentido: por debajo de 17 hay poca dispersión para explotar; por encima de 21 las
correlaciones se van a 1 y las estrategias direccionales se rompen. El medio es donde hay
movimiento sin pánico.

**Y aun así no es significativo.** Este es el punto que no quiero que se pierda:

| Estrategia en la banda | Sharpe | Años en banda | SE | t | p |
|---|---|---|---|---|---|
| XSMOM · 40 acciones | +0,61 | 4,2 | 0,53 | **+1,14** | 0,252 |
| XSMOM · 9 sectores | +0,36 | 4,2 | 0,50 | +0,71 | 0,476 |
| TSMOM · 9 clases | +0,15 | 4,2 | 0,49 | +0,30 | 0,760 |

La diferencia de medias entre estar dentro y fuera de la banda (test t de Welch) da
+1,92 bps/día con **t = 1,18, p = 0,240** para el mejor caso.

Y el número que resume todo el proyecto: **para que ese Sharpe de 0,61 llegue a t = 2
harían falta ~13 años dentro de la banda, o sea ~60 años de calendario.**

Además, partir la muestra en tres regímenes triplica las hipótesis. Encontrar que uno de
tres tramos se ve mejor no es un hallazgo, es lo que pasa cuando partís cualquier serie.

Esto es la hipótesis más prometedora de todo el proyecto, y sigue siendo **una hipótesis**,
no un resultado. Si alguien la operara con estos datos, estaría apostando a un patrón que
en cuatro años de muestra no se separa del azar.

---

## Conclusión

Sobre acciones, ETFs, FX, crypto y futuros, en velas de 5 minutos a diarias, con costos
realistas: **no encontré reversión a la media operable.** Los tests de Dickey-Fuller y
Engle-Granger rechazan casi siempre, y donde no rechazan el backtest tampoco paga.

El control positivo cierra la pregunta que faltaba. El motor **sí detecta** un efecto
inyectado (p = 0,010 en las tres pruebas sintéticas) y **sí reproduce** el crash de
momentum de 2009 sin que nadie se lo pida. No es ciego. Lo que pasa es otra cosa, y es más
interesante:

> **Ni siquiera el momentum —documentado desde 1993, replicado durante treinta años— llega
> a significancia con 20 años de datos.** Sharpe +0,06, p empírico 0,144.

Ese es el resultado que más enseña de todo el proyecto. El problema no es que las
estrategias no funcionen: es que los efectos reales en estos mercados tienen un tamaño tan
chico que la cantidad de datos necesaria para demostrarlos supera la vida útil de la
mayoría de las series. La banda VIX 17-21 —el hallazgo más prometedor— necesitaría **60
años de calendario** para alcanzar t = 2.

Nada de esto invalida el motor. La calibración recupera θ, μ y σ de procesos simulados con
menos de 10 % de error, los tres ports coinciden en 1e-9, y sobre una serie que *es* un
Ornstein-Uhlenbeck la estrategia da Sharpe 1,65. El modelo funciona; lo que no se cumple es
su supuesto.

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
- **La banda VIX 17-21, con más historia.** Es la única pista con dirección consistente en
  todas las estrategias probadas. Con datos desde 1990 (el VIX existe desde entonces) la
  muestra dentro de la banda pasaría de 4 a ~7 años. Sigue sin alcanzar para t = 2, pero
  es la dirección correcta.
- **Aceptar de entrada que el listón es la potencia estadística, no la idea.** Antes de
  probar una hipótesis nueva conviene calcular cuántos años harían falta para confirmarla.
  Si la respuesta es 60, el problema no se arregla programando mejor.

Y lo que **no** haría: apagar el gate y optimizar los seis parámetros hasta que la curva
quede linda. Eso siempre encuentra algo, y ese algo nunca sobrevive fuera de muestra.

---

Esto es investigación cuantitativa, **no** asesoramiento de inversión.
