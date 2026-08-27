# Estrategias algorítmicas con matemática: Ornstein-Uhlenbeck y Markov

Este documento explica la matemática que implementa el paquete `quant/`, de la ecuación
diferencial estocástica hasta la regla de trading, y —tan importante como lo anterior—
**cuándo el modelo no aplica**.

---

## 1. La fuerza restauradora: la EDE de Ornstein-Uhlenbeck

Un movimiento browniano geométrico (el modelo estándar de un precio) no tiene memoria de
ningún nivel: se va a donde lo lleve el ruido. El proceso de Ornstein-Uhlenbeck agrega un
término de arrastre proporcional a la distancia a un equilibrio:

```
dX_t = θ·(μ − X_t)·dt + σ·dW_t
```

| Símbolo | Qué es | Analogía física |
|---|---|---|
| `θ > 0` | velocidad de reversión | constante del resorte (rigidez) |
| `μ` | nivel de equilibrio | posición de reposo |
| `σ` | volatilidad instantánea | intensidad de los golpes térmicos |
| `dW_t` | incremento de Wiener | ruido browniano |

El término `θ·(μ − X_t)·dt` es una **fuerza restauradora tipo Hooke**: proporcional al
desplazamiento y de signo opuesto. Por encima de μ empuja hacia abajo, por debajo empuja
hacia arriba. Esta es la única diferencia con un random walk, y lo cambia todo: el proceso
tiene distribución límite en vez de dispersarse sin cota.

## 2. La curva de decaimiento y el half-life

Tomando esperanza en la EDE, el ruido se cancela (`E[dW] = 0`) y queda una EDO lineal:

```
dE[X_t]/dt = θ·(μ − E[X_t])
```

cuya solución es un **decaimiento exponencial** de la desviación inicial:

```
E[X_t | X_0] = μ + (X_0 − μ)·e^(−θ·t)
```

El **half-life** es el tiempo en que la desviación se reduce a la mitad:

```
(X_0 − μ)·e^(−θ·t½) = ½·(X_0 − μ)   ⟹   t½ = ln(2) / θ
```

Es el número que hace operable al modelo: dice **cuántos días** hay que esperar, no solo
que "en algún momento vuelve". La curva es autosemejante — cada half-life corta la mitad
de lo que quedaba:

| Tiempo | Desviación restante |
|---|---|
| 1 × t½ | 50 % |
| 2 × t½ | 25 % |
| 3 × t½ | 12,5 % |
| τ = 1/θ | 36,8 % (1/e) |

La varianza condicional crece pero **satura**:

```
Var[X_t | X_0] = σ²·(1 − e^(−2θt)) / (2θ)   ──→   σ²_eq = σ²/(2θ)
```

Por eso el z-score `z = (X − μ)/σ_eq` es una medida estacionaria de "cuánto está estirado
el resorte", comparable entre activos y entre épocas. En un random walk, en cambio, la
varianza crece sin límite (`σ²·t`) y ningún z-score de ese tipo tiene sentido.

Implementado en `quant/ou.py`: `expected_path()` devuelve la curva, la banda de ±1σ y los
hitos de 1, 2 y 3 half-lives.

## 3. Calibración: del SDE a una regresión lineal

El OU tiene **solución exacta en tiempo discreto** (no hace falta Euler-Maruyama).
Muestreando cada Δt:

```
X_(i+1) = X_i·e^(−θΔt) + μ·(1 − e^(−θΔt)) + ε_i,    ε_i ~ N(0, σ²(1−e^(−2θΔt))/(2θ))
```

Esto es exactamente un AR(1): `X_(i+1) = a + b·X_i + ε`. Se estima por mínimos cuadrados y
se deshace el cambio de variable:

```
θ = −ln(b)/Δt        μ = a/(1−b)        σ = σ_ε·√(2θ/(1−b²))        σ_eq = σ_ε/√(1−b²)
```

Si `b ≥ 1` no hay reversión (raíz unitaria o proceso explosivo) y la calibración se declara
inválida en vez de devolver un θ negativo disfrazado.

## 4. El test que evita el autoengaño: Dickey-Fuller

**Toda** serie finita produce un `b < 1` y por lo tanto un half-life. Eso no significa que
haya reversión: es la pregunta, no la respuesta. La regresión de Dickey-Fuller

```
ΔX_i = a + (b−1)·X_i + ε
```

testea `H0: b = 1` (raíz unitaria, sin reversión). Bajo H0 el estadístico **no** sigue una
t de Student —está sesgado hacia valores negativos— así que se compara contra la tabla de
Dickey-Fuller (con constante, sin tendencia):

| Nivel | Crítico |
|---|---|
| 1 % | −3,43 |
| 5 % | −2,86 |
| 10 % | −2,57 |

Si el estadístico no baja del crítico, el half-life calculado es un **artefacto de la
muestra**. La plataforma lo dice explícitamente en vez de dibujar la curva y callarse.

En la práctica, con acciones e índices sueltos el test casi nunca rechaza: el log-precio se
comporta como random walk. Ese es el resultado esperado y honesto, y la razón de la sección 6.

## 5. Regímenes de mercado: cadenas de Markov

Un proceso de Markov de primer orden cumple:

```
P(S_(t+1) = j | S_t = i, S_(t−1), …) = P(S_(t+1) = j | S_t = i) = P_ij
```

Los retornos diarios se discretizan en tres regímenes con umbrales ±k·σ (k = 0,5 por
defecto): **bajista**, **lateral**, **alcista**. La matriz `P` se estima por frecuencias
con suavizado de Laplace (α = 1) para que un par no observado no dé probabilidad 0 exacta.

De `P` salen tres cantidades que sí se usan:

- **Persistencia** `P_ii`: probabilidad de seguir en el mismo régimen mañana.
- **Duración media de la racha**: `1/(1 − P_ii)` — esperanza de una geométrica.
- **Distribución estacionaria** `π`, con `π·P = π`, calculada por iteración de potencias:
  la fracción de tiempo de largo plazo en cada régimen. `P^n` (Chapman-Kolmogorov) da la
  probabilidad de régimen a n pasos y converge a `π`.

Y un test de control, análogo al de Dickey-Fuller: un **χ² de independencia** sobre la
tabla de contingencia de transiciones, con `(k−1)² = 4` grados de libertad. `H0` = el
próximo estado es independiente del actual (no hay memoria). Si el p-valor es alto, **el
régimen no informa nada** y el filtro de régimen se desactiva solo. En datos diarios de
acciones, lo normal es no encontrar memoria: los retornos diarios son casi ruido blanco.

Implementado en `quant/markov.py`.

## 6. Dónde el OU sí aplica: pares cointegrados

Si el precio suelto no revierte, la salida no es forzarlo sino cambiar el objeto de estudio.
Dos activos pueden ser individualmente no estacionarios y aun así tener una **combinación
lineal estacionaria**: eso es cointegración. Engle-Granger en dos etapas:

1. `log A_t = α + β·log B_t + s_t` — `β` es el **hedge ratio** y `s_t` el spread (una
   cartera de valor neto ≈ 0: larga en A, corta en β unidades de B).
2. Test de raíz unitaria sobre `s_t`. Como β se estimó de los mismos datos, los valores
   críticos son más exigentes (tabla de Engle-Granger para 2 series: −3,34 al 5 %).

Si el spread pasa el test, se lo modela como OU y el half-life dice cuántos días tarda en
cerrarse la mitad de la divergencia. Este es el uso correcto del proceso, y el origen
histórico del *statistical arbitrage*.

La cointegración **no es permanente**: se rompe con fusiones, cambios de negocio o de
régimen de tasas. Por eso el backtest de pares re-estima β en cada ventana.

Implementado en `quant/pairs.py`.

## 7. De los parámetros a las órdenes

```
z_t = (X_t − μ̂) / σ̂_eq        (μ̂ y σ̂_eq estimados SOLO con datos hasta t)

z ≤ −entrada  → largo (+1)      el resorte está estirado hacia abajo
z ≥ +entrada  → corto (−1)      estirado hacia arriba
|z| ≤ salida  → cerrar          volvió al equilibrio
|z| ≥ stop    → cerrar          la tesis falló: el equilibrio se movió
t > k·t½      → cerrar          la fuerza restauradora debería haber actuado ya
```

La última regla es la que convierte el half-life en gestión de riesgo real: si pasaron
3 half-lives sin reversión, la evidencia dice que el modelo dejó de describir a la serie —
no que "falta poco".

Encima va el **filtro de régimen**: no se abren posiciones contra un régimen persistente
(nada de comprar la caída dentro de una tendencia bajista con `P_ii` alto). El filtro solo
se activa si el χ² rechazó la independencia; sin evidencia de memoria, no filtra.

Implementado en `quant/strategies.py`.

## 8. Backtest: por qué es walk-forward

Calibrar el OU sobre toda la muestra y después "operar" ese z-score es **look-ahead bias**:
μ y σ_eq contienen información de precios futuros, y el resultado es una curva de equity
espectacular e irreproducible. `quant/backtest.py` recalibra sobre una ventana móvil que
termina en `t`, decide la señal con esa información y cobra el P&L con el retorno de
`t → t+1`. Los costos (`cost_bps`) se cobran sobre `|Δposición|`, así que dar vuelta una
posición paga dos veces.

Hay un test automático que verifica esta propiedad estructuralmente
(`test_backtest_sin_look_ahead`): corre el backtest sobre una serie y sobre la misma serie
extendida, y exige que el tramo común sea **idéntico bit a bit**. Si alguna vez se filtrara
información del futuro, ese test falla.

Métricas reportadas: retorno total, CAGR, volatilidad anualizada, Sharpe, Sortino, máximo
drawdown, Calmar, hit rate, cantidad de trades y exposición — siempre contra el buy & hold
del mismo período, que es el benchmark que importa.

## 9. Validación

`tests/test_quant.py` no compara contra números "que parecen bien": simula procesos con
parámetros **conocidos** y exige recuperarlos.

- OU con θ = 0,05, μ = 4,0, σ = 0,2 → el calibrador recupera los tres con < 10 % de error, y
  el half-life converge a ln(2)/0,05 = 13,86.
- Un random walk **no** debe declararse estacionario.
- Una cadena de Markov con matriz conocida → se recupera con error < 0,02 por celda; `P^50`
  converge a π; el χ² detecta memoria en la cadena persistente y **no** la detecta en una
  serie iid.
- La estrategia gana sobre una serie que *es* un OU (Sharpe > 0,8) y **no** genera alfa
  sobre un random walk.
- El backtest no mira el futuro (test bit a bit descrito arriba).

```bash
python tests/test_quant.py     # 22/22 tests, sin red, deterministas
```

## 10. Limitaciones honestas

- **Datos de cierre diario, gratuitos** (Yahoo). Sin ajuste por dividendos ni por splits más
  allá de lo que ya trae el feed; sin datos intradiarios ni libro de órdenes.
- **Costos aproximados**: `cost_bps` cubre comisión + spread de forma lineal. No modela
  impacto de mercado, slippage en momentos de estrés ni costo de borrow para vender en corto
  (que en un par cointegrado no es despreciable).
- **Sin ejecución**: la plataforma calcula y explica; no manda órdenes a ningún bróker.
- **Backtest ≠ futuro**: los parámetros son estimaciones con error muestral, y la
  cointegración puede romperse el día después del último dato.
- Un buen resultado en backtest sobre una serie que no pasa los tests de estacionariedad es
  **ruido**, no una señal. La plataforma marca esos casos en vez de esconderlos.

Esto es análisis cuantitativo, **no** asesoramiento de inversión.
