# Niveles de sesión para futuros de índices (ES, MES, NQ, MNQ)

Dos piezas que resuelven lo mismo desde distintos lados:

| Pieza | Qué hace |
|---|---|
| **App web** — `web/futuros.html`, servida en `/futuros` | Calcula todo: niveles de precio **y** de opciones |
| **Indicador de TradingView** — `trading/tradingview/NivelesSesion.pine` | Dibuja los niveles sobre el gráfico donde operás, en tiempo real |

```bash
python main.py          # http://localhost:8000/futuros
```

---

## Lo primero: qué NO es esto

**No es option flow.** Barridos, bloques y clasificación por lado agresor necesitan el feed
de ticks de CME o de OPRA, que es pago. Acá no hay nada de eso, y conviene saberlo antes de
mirar un número.

Lo que sí se consiguió, y no es poco: **Yahoo no publica cadena de opciones para `ES=F` ni
`NQ=F`, pero sí para `^SPX` y `^NDX`** — que son el mismo subyacente. Las opciones de
índice son además un mercado más grande que las de futuros, así que el posicionamiento que
mueve al índice está ahí. Los strikes se traducen a puntos del futuro con la base
(futuro/índice ≈ 1,008 en ES), que incorpora tasa y dividendos; sin esa corrección todos
los niveles quedan desplazados unos 60 puntos.

Y una distinción que importa al leer la pantalla:

- **Volumen por strike** = actividad de **hoy**. Es lo más cercano a "flujo" que hay gratis.
- **Interés abierto** = posiciones que quedaron de **ayer**. Es lo estructural.

En los vencimientos del mismo día el interés abierto figura en cero, porque se reporta del
cierre anterior. No es un error del tablero: es cómo se publica el dato.

## Los niveles

**De precio** (velas de 5 minutos del futuro, 59 días de historial):

| Nivel | Por qué está |
|---|---|
| Cierre, máximo y mínimo del **RTH previo** (9:30-16:00 NY) | El cierre de ayer es la referencia del hueco |
| Máximo y mínimo de **Globex** (18:00-9:30) | Romper el extremo nocturno es la continuación más limpia |
| **Rango de apertura** (primeros 30 min) | El initial balance del perfil de mercado |
| **VWAP** anclado a la apertura del RTH | El precio medio que mira la mesa |
| **Pivotes de piso** PP, R1-R3, S1-S3 | Aritmética sobre la sesión previa. Valen porque mucha gente los mira, no porque el mercado los respete |
| **Apertura ± ATR de sesión** | Cota de lo "normal" para el día |

**De opciones** (cadena de `^SPX` / `^NDX`, strikes dentro de ±5% del precio):

| Nivel | Qué dice |
|---|---|
| **Muro de calls** | Mayor interés abierto en calls por encima: la cobertura de los vendedores frena la suba |
| **Muro de puts** | Mayor interés abierto en puts por debajo |
| **Max pain** | Dónde vencería sin valor la mayor cantidad de contratos. No es una predicción |
| **Gamma cero** | Dónde cambia de signo la gamma total. Por encima, cubrir amortigua el movimiento; por debajo lo amplifica |

El filtro de ±5% no es cosmético. Sin él, el "muro de puts" se iba a un strike **1.568
puntos por debajo** del precio: una cobertura de cartera de largo plazo, dato real y
completamente inútil para operar la sesión.

La gamma no viene en el feed: se calcula con Black-Scholes a partir de la volatilidad
implícita que sí viene. En los vencimientos del día el tiempo a vencimiento se acota por
abajo, porque con T→0 la gamma se va al infinito.

## La app web

Un tablero por contrato con mosaicos de cifra, una **escalera de niveles** y tablas.

Sobre la escalera: en una sesión normal hay nueve niveles dentro de 60 puntos y las
etiquetas se pisan — la primera versión era ilegible, con 12 de 16 solapadas y 0,1 px de
separación mínima. La línea y el punto van en el precio **real**; la etiqueta se corre lo
mínimo para no solaparse, con un conector que la ata a su nivel. Quedaron 19 px de
separación garantizada y cero solapamientos.

Los colores de dato codifican el **origen** del nivel (precio contra opciones), no si está
arriba o abajo: eso ya lo dice la posición en el gráfico. El par `#4a86de` / `#b8862b` pasa
los seis controles de paleta sobre el fondo oscuro: banda de luminosidad, piso de croma,
separación ΔE 25,5 en protanopía y 26,9 en visión normal, y contraste ≥ 3:1. El precio
actual va en tinta de texto, porque es una referencia y no una serie.

Cada fila de la tabla trae la distancia en puntos **y en dólares por contrato**, usando el
multiplicador real: 1 punto son US$ 50 en ES y US$ 2 en MNQ. Esa diferencia de 25× es lo
que decide si un nivel a 30 puntos importa o no.

El servidor cachea: 2 minutos los niveles de precio, 15 minutos la cadena de opciones. El
interés abierto cambia una vez por día — pedirlo cada minuto no agrega nada y castiga a un
feed gratuito.

## El indicador de TradingView

Pine Script **no puede leer una cadena de opciones**: `request.security` sólo trae otros
símbolos de TradingView, no interés abierto por strike. Así que el indicador se reparte:

**En tiempo real, calculado solo** — RTH previo, Globex, rango de apertura, VWAP anclado,
pivotes, ATR de sesión. Todo tick a tick, y **sin repintado**: cada nivel queda fijo cuando
su sesión termina y no se vuelve a tocar.

**Carga manual** — los cuatro niveles de opciones. El tablero web los muestra en un bloque
aparte con un botón de copiar. Son cuatro números por la mañana, y como el interés abierto
se actualiza una vez por día, no hace falta más.

Incluye tabla de distancias en una esquina y **alertas con mensaje dinámico** al cruzar
cada nivel ("ES cruzó el muro de puts en 7558.42"), que se disparan una vez por barra
cerrada para no inundar el teléfono con cada oscilación sobre el nivel.

### Instalación

1. TradingView → **Pine Editor** → pegar el contenido de `NivelesSesion.pine`.
2. **Save** y **Add to chart**.
3. Abrir los ajustes y cargar los cuatro valores de opciones desde `/futuros`.

Probalo en `ES1!`, `NQ1!` o `MNQ1!` en temporalidad intradía (1 a 15 minutos). En diario no
tiene sentido: los niveles son de sesión.

### La estadística de toques, y por qué el control al azar no es opcional

El indicador cuenta, nivel por nivel, cuántas veces el precio **aguantó** y cuántas
**rompió**. La primera versión decía algo así: *"los niveles aguantan el 71% de los
toques"*. Esa cifra es verdadera y no significa nada.

El problema es el procedimiento. Una vela que toca una resistencia desde abajo casi siempre
cierra por debajo del nivel: ya arranca más cerca de la condición de "aguantó" que de la de
"rompió". Cualquier precio medido así da una tasa alta, incluso uno inventado.

Para medirlo se corre todo de nuevo con **niveles puestos al azar** dentro del rango de la
sesión previa ampliado por un ATR, en la misma cantidad y con las mismas reglas:

| | ES=F | NQ=F |
|---|---|---|
| Niveles reales | 71,1 % | 72,4 % |
| Niveles **al azar** | 73,5 % | 73,0 % |
| p empírico | 0,76 | 0,59 |
| Niveles informativos (de 12) | 0 | 0 |

Los niveles de verdad **pierden** contra líneas tiradas al azar. El 71% medía la mecánica
de la medición, no el mercado. Ningún nivel individual sobrevive a corregir por las doce
pruebas: el mejor fue el Pivote R2 del NQ con z = 2,11 sobre n = 12, que da p = 0,035
suelto pero necesita p < 0,0042 para pasar Bonferroni con doce candidatos. Mirar doce
niveles y quedarse con el mejor es exactamente la receta conocida para encontrar nada.

**Conclusión operativa:** los niveles sirven como mapa de dónde mirar y dónde poner un
stop, no como probabilidad de rebote. El indicador y la app muestran el control al azar
**al lado** del dato, en la misma tabla y en el mismo gráfico, para que la cifra no se
pueda leer sola.

Detalles del procedimiento:

- Tolerancia de toque: 0,10 ATR de sesión. Margen de resolución: 0,25 ATR. En fracciones
  de ATR y no en puntos, para que el criterio signifique lo mismo en ES (ATR ~60) que en
  NQ (ATR ~350).
- Tras resolver un toque hay **enfriamiento**: el precio tiene que alejarse del nivel antes
  de que cuente un toque nuevo. Sin eso, una consolidación pegada al nivel registraba un
  toque por vela y multiplicaba el conteo.
- Límite de 24 barras para resolver; lo que no resuelve queda como `sin_resolver` y no
  suma a ningún lado.
- Intervalos por Wilson, no por la aproximación normal: con n=7 la normal da intervalos
  que se salen de [0,1].
- La muestra es chica y no por descuido: Yahoo entrega unas 8 semanas de velas de 5
  minutos, o sea ~26 sesiones. Por eso los intervalos son anchos. Con un feed de más
  historial la conclusión podría cambiar, pero el control al azar seguiría siendo
  obligatorio.

Está en `quant/toques.py` (Python, con tests), en `/api/futuros/toques/{symbol}` y
replicado en el Pine, donde la tabla lleva una fila ámbar **"CONTROL al azar"** con un
nivel sorteado en cada apertura de sesión por un generador congruencial propio — Pine no
trae números aleatorios.

### Lo que no pude verificar

**El Pine no está compilado.** No hay compilador de Pine fuera de TradingView, así que
revisé el código a mano y corregí cuatro errores de sintaxis reales que había escrito:
declaraciones `var` múltiples en una línea (Pine exige una por línea), una función declarada
dentro de un `if` (no se permite), `na` en las coordenadas de `line.new` y `label.new`, y un
signo de distancia invertido. Si al pegarlo aparece un error, decímelo con el mensaje y lo
arreglo — pero esperá tener que iterar una vez.

La matemática de los niveles sí está verificada: el módulo `quant/niveles.py` la calcula
igual y tiene tests.

---

## El histórico de interés abierto, fabricado a mano

El feed devuelve **una sola foto del momento**, sin fecha: no hay forma de pedirle el
interés abierto de una sesión pasada. Y el interés abierto es diario por construcción,
porque la OCC lo publica a la mañana siguiente — durante la sesión se ven las posiciones
del cierre anterior. **No existe interés abierto intradía**, en ningún lado y a ningún
precio.

La única manera de tener la serie es fabricarla. `scripts/snapshot_oi.py` saca una foto por
día hábil tras el cierre de Nueva York y la deja commiteada: **el repositorio es la base de
datos**, porque el contenedor donde corre es efímero y cualquier cosa en disco local se
pierde al reciclarse. Se guarda en `data/opciones/{SPX,NDX}.jsonl`, una línea por captura,
para que el diff de git muestre exactamente lo que se agregó.

Lo que se captura, dentro de ±8% del spot: interés abierto y volumen por strike, más los
agregados (GEX total, régimen de gamma, max pain, gamma cero, muros de calls y puts,
ratios put/call de interés abierto y de volumen).

### El desfase de un día, que es la trampa de todo esto

En una misma fila, **el volumen y el interés abierto no son del mismo día**. El volumen es
de la sesión en curso; el interés abierto es del cierre anterior. Quien regrese "cambio de
interés abierto" contra "retorno de la sesión siguiente" sin saber esto se equivoca por un
día y obtiene un resultado que parece real.

Es exactamente el mismo tipo de error que ya apareció dos veces acá: la alineación por
timestamp exacto que daba 20 fechas comunes en vez de 2509 entre GC=F y GLD, y el nulo roto
del Gap-Fade. Por eso `serie()` devuelve `desfase_oi: -1` explícito en vez de dejarlo
implícito, y hay un test que lo fija.

### Por qué el volumen importa más que lo que se pidió

En un strike de SPX medido el 2026-10-15, el volumen era **126.152** contra un interés
abierto de **762**. Toda esa actividad abre y muere dentro de la sesión y nunca se convierte
en interés abierto. Justo lo que mueve al índice intradía —el 0DTE— es lo que el interés
abierto no ve. Por eso se captura el volumen por strike además del interés abierto: para el
scalping es el número que de verdad manda.

### Lo que todavía no se puede decir

Nada. Son datos crudos acumulándose. `serie()` lo avisa solo: con menos de 60 sesiones
cualquier patrón que aparezca es ruido, y cuando haya muestra la hipótesis —si el cambio de
interés abierto o de GEX predice algo de la sesión siguiente— va a pasar por el mismo
control al azar que hundió a la tasa de aguante de los niveles.

Un detalle que casi arruina el dataset antes de empezar: `market.options()` no tenía
reintento, y el feed devuelve `result=null` con HTTP 200 de forma intermitente (me pasó
mientras armaba esto). En un trabajo que corre **una vez por día**, un fallo transitorio
pierde esa observación para siempre y deja un agujero en la serie. Ahora reintenta tres
veces, igual que las velas.

---


Investigación cuantitativa, **no** asesoramiento de inversión. Los niveles son referencias
de precio, no señales de entrada: que mucha gente mire el mismo número no quiere decir que
el mercado lo respete.

## El diario: medir si el mapa sirve de verdad

Todo lo medido dice que los niveles no predicen rebotes. Lo que queda sin medir es si el
mapa igual ayuda a operar mejor: tamaño de posición, dónde va el stop, cómo comportarse
según el régimen de gamma. Decir "me ayuda" sin medirlo es una sensación, y acá las
sensaciones ya mintieron dos veces.

```
python3 scripts/diario.py abrir  MNQ=F largo 1 30150 30050 --nivel "Pivote S1"
python3 scripts/diario.py cerrar a1b2c3d4 30220 --motivo objetivo
python3 scripts/diario.py estado
python3 scripts/diario.py barras      # recupera las velas que falten
python3 scripts/diario.py analizar
```

El contexto del día —ATR, régimen de gamma, precio del nivel— lo completa solo desde el
tablero. A la hora de entrar no hay tiempo de tipear ocho datos, y un diario con fricción
es un diario vacío.

### Las dos decisiones que separan un diario de un relato

**El plan se registra antes que el resultado.** `abrir` guarda entrada, stop y nivel de
referencia; `cerrar` guarda la salida. Si las dos llegan en el mismo segundo, el registro
queda marcado `post_hoc` y el análisis lo **excluye**. Un stop "elegido" después de ver
cómo terminó el día no mide nada, y sin esa marca el diario se llena de aciertos
retroactivos sin que nadie mienta a propósito.

**Se guardan las velas de la sesión.** El feed entrega 8 semanas de velas de 5 minutos.
Sin guardarlas, dentro de tres meses el control al azar sobre los trades viejos es
imposible de calcular. Es el mismo error que casi arruina el histórico de interés abierto,
y acá se evita de entrada. Si el guardado falla —una operación cerrada antes de que abra
el RTH, o un fallo del feed—, `diario.py barras` lo reintenta, y avisa cuáles ya no se
pueden recuperar.

### Lo que se mide

El resultado se normaliza en **R** (R = riesgo inicial = |entrada − stop|), así un trade de
1 MNQ y uno de 3 ES son comparables. El análisis devuelve R medio con **error estándar y
t**, porque sin eso una racha de cinco parece una estrategia, y el intervalo de Wilson para
la tasa de acierto, que con 5 de 5 sigue admitiendo que puede ser suerte.

Tres cortes, y el segundo testea directamente el consejo que da este repositorio:

| Corte | Qué pregunta |
|---|---|
| Por régimen de gamma | ¿Comportarse distinto según el signo tiene respaldo? |
| Stop dentro / fuera de la banda de ruido (0,25 ATR del nivel) | ¿Poner el stop fuera del ruido mejora el resultado? |
| Por nivel de referencia | ¿Alguno se destaca, corrigiendo por multiplicidad? |

Por debajo de 30 operaciones con plan previo el reporte se niega a llamar medible a la
muestra y lo dice con todas las letras: *"lo que hay ahora es contabilidad, no evidencia"*.

### Lo que falta

El control al azar. Repetir cada operación anclada a un **precio sorteado** en vez del
nivel usado, con el mismo stop y el mismo objetivo, sobre las velas reales de esa sesión.
Si las operaciones de verdad no le ganan a eso, el nivel no aportó nada — exactamente como
pasó con la tasa de aguante. Las velas se guardan en `data/diario/barras/` justamente para
poder correrlo cuando haya muestra.

---
