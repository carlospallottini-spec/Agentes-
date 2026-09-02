# Análisis del EA DualNasdaq (motores S y G)

Réplica en Python de las dos estrategias del EA, pasadas por los mismos filtros que el
resto del repo: Sharpe con error estándar de Lo, **nulo por permutación**, sensibilidad al
costo, ventanas de tiempo y régimen de VIX.

```bash
python research/dual_nasdaq.py --symbol ^NDX --guardar
```

Datos: 5.026 sesiones diarias del Nasdaq 100 (2006-09 a 2026-09, 19,9 años), costo base
1 bp por lado sobre el nocional. Con 20 años, el listón para t = 2 es **Sharpe ≥ 0,47**.

---

## Lo primero: el test que casi nadie hace

El Nasdaq tiene deriva intradía. Comprar en la apertura y vender en el cierre **en días
elegidos al azar** ya es una estrategia. Así que la pregunta no es si el backtest da
positivo, sino si la señal le gana a tirar una moneda.

El nulo por permutación reparte los **mismos** trades sobre días al azar, con el mismo
dimensionamiento y las mismas reglas de salida. Sólo cambia *cuándo* se opera.

## Motor S — SessionMarkov: **la señal aporta**

| Métrica | Valor |
|---|---|
| Operaciones | 991 en 19,9 años (50/año) |
| Sharpe | **+0,55** (t = +2,29, p = 0,022) |
| CAGR | +4,05 % · maxDD 14,1 % |
| Profit factor | 1,236 · aciertos 54,5 % |
| Media por operación | 8,51 bps |
| **p empírico contra el nulo** | **0,0080** |

El nulo queda centrado en cero (media −0,00, p95 +0,32) y operar **todos** los días da
Sharpe −0,00. O sea: la deriva intradía sola no explica nada, y la señal sí.

**Es lo primero en todo este proyecto que pasa las dos barras a la vez**: significancia
paramétrica y nulo empírico.

Y aguanta el cambio de ventana, que es donde mueren casi todas las estrategias:

| Ventana | Años | Sharpe | CAGR | maxDD | PF |
|---|---|---|---|---|---|
| 2006-2026 (todo) | 19,9 | +0,55 | +4,05 % | 14,1 % | 1,24 |
| 2018-2026 (la que declara el EA) | 8,6 | +0,41 | +3,08 % | 9,3 % | 1,17 |
| **2006-2017 (fuera de esa muestra)** | 11,3 | **+0,61** | +4,44 % | 14,1 % | 1,27 |

Funciona *mejor* fuera de la ventana en la que se declaró validado. Eso es lo contrario
del sobreajuste.

### Dónde se rompe

**En los costos.** El resultado es lineal en el costo y muere antes de los 5 bps:

| Costo | Sharpe | CAGR | PF | Media/trade |
|---|---|---|---|---|
| 0 bps | +0,68 | +5,07 % | 1,30 | 10,49 bps |
| 1 bp | +0,55 | +4,05 % | 1,24 | 8,51 bps |
| 2 bps | +0,41 | +3,03 % | 1,18 | 6,53 bps |
| **5 bps** | **+0,01** | +0,04 % | 1,01 | 0,60 bps |

Con 8,5 bps de ganancia media por operación, cada punto básico de costo se lleva el 12 %
del edge. **El spread del bróker decide si esto existe.** Antes de asignar capital, medí
el spread real de tu US100 en los primeros 20 minutos de la sesión de NY — que es
justamente cuando es más ancho.

Sobre QQQ en vez del índice, el Sharpe baja a **+0,34**: la señal es real pero no
sobra.

## Motor G — Gap-Fade: **mi réplica no puede zanjarlo**

| Supuesto | Sharpe | PF | CAGR | Aciertos |
|---|---|---|---|---|
| Conservador (se asume el stop) | **−0,67** | 0,81 | −3,93 % | 48,1 % |
| Optimista (se asume el objetivo) | **+1,03** | 1,41 | +6,20 % | 59,7 % |

El motor G pone un objetivo y un stop simétricos alrededor del precio de entrada. En
**100 de 859 días de señal (11,6 %)** el precio tocó los dos dentro de la misma jornada, y
con velas diarias **es imposible saber cuál se tocó primero**.

Ese 11,6 % decide el signo del resultado completo. No es un matiz: es la diferencia entre
perder 3,93 % anual y ganar 6,20 %.

**Acá el backtest del EA es mejor herramienta que mi réplica.** Un test "cada tick basado
en ticks reales" resuelve exactamente ese caso. Yo con velas diarias no. Así que **no
afirmo que Gap-Fade no funcione** — afirmo que no se puede decidir con datos diarios, y
que la estrategia es inusualmente sensible a la microestructura.

Dos cosas que sí se pueden decir:

1. **El filtro de tendencia aporta.** Contra el nulo correcto —los mismos trades
   repartidos entre días que *también* tienen un hueco de 0,30-2 %, sin filtrar por
   SMA200— el p empírico es 0,020. Operar todos los huecos que califican da Sharpe −1,04;
   con el filtro, −0,67. Mejora, aunque desde un número malo.
2. **La ventana que el EA declara validada es la peor.** En 2018-2026 mi réplica
   conservadora da PF 0,74, contra 0,89 en 2006-2017. El EA reporta PF 1,11 en esa misma
   ventana. La brecha se explica casi entera por el supuesto ambiguo, y refuerza el punto:
   este resultado vive o muere en la resolución intradía.

## Cartera: los dos juntos

Con mi supuesto conservador, la suma da Sharpe −0,01. La diversificación que promete el
encabezado sí existe —**sólo el 8 % de los días operan los dos motores a la vez**, contra
el 14 % declarado— pero no salva a una pata que resta.

## Régimen de VIX

Motor S rompe el patrón que se repitió en todo el resto del repo: le va **mejor con VIX
bajo** (Sharpe 1,37 con VIX < 17) y peor en la banda 17-21 (−0,29). La diferencia contra el
resto es de −3,08 bps/día con t = −1,93 (p = 0,054), al borde de la significancia.

Tiene lógica: es una estrategia de reversión de un día. Con volatilidad baja, comprar la
caída de ayer funciona; con volatilidad alta, la caída de ayer suele ser el principio de
algo. **Si operás el motor S, la banda 17-21 no es su amiga.**

---

## Revisión del código

Lo que encontré leyendo los dos `.mq5`, ordenado por lo que más importa.

### Problemas

1. **`DualNasdaq2.0` no compila como está.** Hace `#include <RegimeFilter.mqh>` y ese
   archivo no vino. Sin él, `RegimeStressProb()` no existe. No pude evaluar el filtro de
   régimen de la v2.0 en absoluto.

2. **Los Sharpe del encabezado no son comparables entre sí.** Dice "Sharpe 3,17" para el
   motor S y "Sharpe 0,81" combinado. Dos estrategias con Sharpe 3,17 y 2,14 y correlación
   0,068 no pueden dar 0,81 juntas — darían más de 3. La explicación es que **el Sharpe que
   reporta el tester de MT5 se calcula sobre los resultados por operación, no sobre
   retornos diarios anualizados**: no es el mismo número que se usa en la literatura ni el
   que calculo yo. El 0,81 sí es un Sharpe anualizado plausible, y mi réplica del motor S
   da 0,55, del mismo orden. Los 3,17 y 2,14 conviene sacarlos del encabezado: invitan a
   comparar peras con manzanas.

3. **El riesgo real del motor S es el doble del que sugiere el parámetro.**
   `InpS_RiskPct = 1.5` es exposición por ATR ("1 ATR = 1,5 % del capital"), y el stop está
   a **2 ATR**. O sea, 3 % del capital por operación, no 1,5 %. El encabezado habla de
   "riesgo ~1 % cada uno", que no es lo que hace el default.

4. **El motor G entra hasta 20 minutos después de la apertura, con `SYMBOL_ASK`, no con la
   apertura.** El hueco se mide contra el precio del momento, así que si el hueco ya se
   cerró parcialmente el EA entra con menos recorrido al objetivo y el mismo stop. Es
   plausible que ahí se vaya una parte del edge en real. En mi réplica entro en la
   apertura exacta, lo que me favorece.

5. **`Sleep(100)` dentro de `OnTick`, hasta 20 veces.** Bloquea el hilo hasta 2 segundos
   buscando la posición recién abierta. En vivo, en los primeros minutos de la sesión, eso
   es mucho tiempo. `OnTradeTransaction` resuelve lo mismo sin bloquear.

6. **`BuildSessions` pide `(wanted+3)*288` velas M5.** Para el motor S son 5.760 velas ≈ 20
   días de mercado 24 h. Alcanza, pero sin margen: si el bróker tiene huecos de historial
   M5, `got` cae por debajo de `ATRPeriod+2` y el motor deja de operar en silencio (sólo
   avisa cada 10 minutos). Vale pedir el doble.

### Lo que está bien hecho

- **No hay look-ahead.** El motor S sólo usa sesiones con `r[i].time < todayStart`; el G
  usa `Buf(hSMA,1)` y `D1Close(1)`, o sea la barra diaria ya cerrada. Lo verifiqué línea
  por línea y es correcto.
- **El cierre por magic hace varias pasadas** porque los índices se corren al cerrar. Es un
  bug clásico y está resuelto.
- **`PosByMagic` suma con signo**, que es lo correcto en cuentas de cobertura.
- **Abrir primero y poner SL/TP después** evita los rechazos por "Invalid stops". Buena
  decisión práctica.
- **El horario de NY con DST calculado a mano**, en vez de asumir el offset del servidor.

---

## Qué haría yo

**Motor S: seguir.** Es lo único en todo este repo que pasó el nulo por permutación y
además aguantó el cambio de ventana. Antes de ponerle plata:

1. Medí el spread real de tu símbolo entre 9:30 y 9:50 ET. Si supera 3-4 bps de ida y
   vuelta, no queda edge.
2. Bajá `InpS_RiskPct` a 0,75 si querés el 1,5 % de riesgo por operación que dice el
   encabezado.
3. Corré el tester con comisión explícita, no sólo spread.

**Motor G: no decidible con lo que tengo.** El resultado vive en el 11,6 % de días
ambiguos. Antes de operarlo, correlo en el tester con ticks reales y mirá **cuántas
operaciones tocaron ambas barreras** — si son ~12 %, el backtest está decidiendo por vos
en una octava parte de los trades y conviene saber con qué supuesto de fill.

**Y separá los dos motores.** Con mi supuesto conservador, G le resta a S. Que estén poco
correlacionados no ayuda si uno tiene esperanza negativa: diversificar pérdidas no es
diversificar.

---

Esto es investigación cuantitativa, **no** asesoramiento de inversión. Mi réplica no es el
EA: entra en la apertura exacta, usa el índice y no el CFD de tu bróker, y no modela
slippage ni comisión.
