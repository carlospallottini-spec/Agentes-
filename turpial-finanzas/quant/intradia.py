"""Motores intradía de sesión: compra en la apertura, sale en el cierre.

Réplica en Python de las dos estrategias del EA DualNasdaq, para poder pasarlas por el
mismo marco estadístico que el resto del repo (Sharpe con error estándar, nulo por
permutación, sensibilidad al costo, régimen de VIX).

  · **SessionMarkov (motor S)** — mira la sesión RTH de ayer: cuánto cayó medido en ATR
    de sesión, y en qué parte del rango cerró. Compra en la apertura de hoy si cayó más
    de `atr_drop` ATR **o** cerró en el `close_pos` inferior del rango. Stop en múltiplos
    de ATR, salida al cierre.

  · **Gap-Fade (motor G)** — si hoy abre con un hueco bajista de entre `min_gap` y
    `max_gap` por ciento contra el cierre de ayer, y la tendencia diaria es alcista
    (cierre > SMA200), compra en la apertura apostando a que el hueco se cierra. TP en el
    cierre de ayer, SL simétrico.

Las dos son estrategias de "comprar debilidad y mantener el día". El punto crítico al
evaluarlas: **el Nasdaq tiene deriva intradía positiva**, así que comprar en la apertura y
vender en el cierre gana plata en días elegidos al azar. La pregunta no es si el backtest
da positivo, sino si la SEÑAL le gana a elegir la misma cantidad de días tirando una
moneda. Para eso está `nulo_por_permutacion`.

Ambigüedad de la barra diaria: cuando en el mismo día se tocan el stop y el objetivo, no
se sabe cuál ocurrió primero. Acá se asume siempre el **stop** — es el supuesto
conservador, y el que evita inflar el resultado.
"""
from __future__ import annotations

import math
import random

from quant.backtest import metrics

SIN_OPERAR = 0.0


def atr_sesion(ohlc: list[dict], t: int, periodo: int = 14) -> float | None:
    """ATR de sesión tal como lo calcula el EA: TR sobre las `periodo` sesiones previas.

    En el índice t se usan las sesiones t-1 .. t-periodo, cada una contra el cierre de la
    anterior. Sólo datos pasados.
    """
    if t - periodo - 1 < 0:
        return None
    suma = 0.0
    for k in range(1, periodo + 1):
        s = ohlc[t - k]
        pc = ohlc[t - k - 1]["c"]
        tr = max(s["h"] - s["l"], abs(s["h"] - pc), abs(s["l"] - pc))
        suma += tr
    atr = suma / periodo
    return atr if atr > 0 else None


def señal_session_markov(ohlc: list[dict], periodo: int = 14, atr_drop: float = 1.0,
                         close_pos: float = 0.20, exigir_ambas: bool = False) -> list[bool]:
    """Máscara de días en que el motor S compraría, con los datos de la sesión anterior."""
    mask = [False] * len(ohlc)
    for t in range(periodo + 2, len(ohlc)):
        atr = atr_sesion(ohlc, t, periodo)
        if atr is None:
            continue
        ayer = ohlc[t - 1]
        rango = ayer["h"] - ayer["l"]
        if rango <= 0:
            continue
        mov = (ayer["c"] - ayer["o"]) / atr
        pos = (ayer["c"] - ayer["l"]) / rango
        a, b = mov <= -atr_drop, pos <= close_pos
        mask[t] = (a and b) if exigir_ambas else (a or b)
    return mask


def señal_gap_fade(ohlc: list[dict], min_gap: float = 0.30, max_gap: float = 2.00,
                   sma: int = 200) -> list[bool]:
    """Máscara del motor G: hueco bajista dentro de rango y tendencia diaria alcista."""
    mask = [False] * len(ohlc)
    cierres = [b["c"] for b in ohlc]
    for t in range(sma + 1, len(ohlc)):
        media = sum(cierres[t - sma:t]) / sma          # SMA200 hasta ayer inclusive
        if cierres[t - 1] <= media:
            continue
        gap = (ohlc[t]["o"] - cierres[t - 1]) / cierres[t - 1] * 100.0
        mask[t] = (-max_gap <= gap <= -min_gap)
    return mask


def simular_session_markov(ohlc: list[dict], mask: list[bool], periodo: int = 14,
                           riesgo_pct: float = 1.5, stop_atr: float = 2.0,
                           max_leverage: float = 3.0, cost_bps: float = 1.0) -> dict:
    """P&L diario del motor S: entra en la apertura, stop en ATR, sale en el cierre.

    Dimensionamiento del EA: 1 ATR de movimiento = `riesgo_pct` % del capital, con tope
    de apalancamiento. O sea que el apalancamiento es (riesgo_pct/100)·(precio/ATR).
    """
    rets = [0.0] * len(ohlc)
    trades = 0
    for t in range(len(ohlc)):
        if not mask[t]:
            continue
        atr = atr_sesion(ohlc, t, periodo)
        if atr is None:
            continue
        d = ohlc[t]
        entrada = d["o"]
        if entrada <= 0:
            continue
        apal = min(riesgo_pct / 100.0 * entrada / atr, max_leverage)
        stop = entrada - stop_atr * atr if stop_atr > 0 else None
        salida = stop if (stop is not None and d["l"] <= stop) else d["c"]
        rets[t] = apal * ((salida - entrada) / entrada - 2.0 * cost_bps / 10_000.0)
        trades += 1
    return {"retornos": rets, "trades": trades}


def simular_gap_fade(ohlc: list[dict], mask: list[bool], riesgo_pct: float = 1.0,
                     cost_bps: float = 1.0, piso_stop_pct: float = 0.15,
                     ambiguo: str = "stop") -> dict:
    """P&L diario del motor G: TP en el cierre de ayer, SL simétrico, si no cierre.

    `piso_stop_pct` sólo interviene en el nulo: en un día elegido al azar puede no haber
    hueco bajista, y sin él la distancia del stop sería cero o negativa. En los días de
    señal real el hueco siempre es de al menos `min_gap`, así que el piso no toca nada.

    `ambiguo` decide qué se supone cuando en el mismo día se tocan el stop Y el objetivo:
    "stop" (conservador, por defecto) u "objetivo" (optimista). **No es un detalle**: con
    barras diarias es imposible saber cuál ocurrió primero, y en esta estrategia de
    barreras simétricas ese caso decide el resultado entero. Correr las dos versiones y
    comparar es la forma honesta de mostrar cuánta incertidumbre queda.
    """
    rets = [0.0] * len(ohlc)
    trades = 0
    for t in range(1, len(ohlc)):
        if not mask[t]:
            continue
        d = ohlc[t]
        entrada, ayer = d["o"], ohlc[t - 1]["c"]
        if entrada <= 0:
            continue
        dist = max(ayer - entrada, entrada * piso_stop_pct / 100.0)
        objetivo, stop = entrada + dist, entrada - dist
        toca_stop, toca_obj = d["l"] <= stop, d["h"] >= objetivo
        if toca_stop and toca_obj:
            salida = stop if ambiguo == "stop" else objetivo
        elif toca_stop:
            salida = stop
        elif toca_obj:
            salida = objetivo
        else:
            salida = d["c"]
        apal = riesgo_pct / 100.0 * entrada / dist
        rets[t] = apal * ((salida - entrada) / entrada - 2.0 * cost_bps / 10_000.0)
        trades += 1
    return {"retornos": rets, "trades": trades}


def evaluar(rets: list[float], trades: int, periodos_por_anio: int = 252) -> dict:
    """Métricas de una serie de retornos diarios de capital (0 en los días sin operar)."""
    logs = [math.log(max(1.0 + r, 1e-9)) for r in rets]
    m = metrics(logs, None, trades, periodos_por_anio)
    m.pop("curva", None)
    operados = [r for r in rets if r != 0.0]
    m["trades"] = trades
    m["dias_operados_pct"] = round(100.0 * len(operados) / len(rets), 1) if rets else 0.0
    m["ganadores_pct"] = (round(100.0 * sum(1 for r in operados if r > 0) / len(operados), 1)
                          if operados else None)
    ganancia = sum(r for r in operados if r > 0)
    perdida = -sum(r for r in operados if r < 0)
    m["profit_factor"] = round(ganancia / perdida, 3) if perdida > 0 else None
    m["retorno_medio_por_trade_bps"] = (round(sum(operados) / len(operados) * 10_000, 2)
                                        if operados else None)
    return m


def universo_gaps(ohlc: list[dict], min_gap: float = 0.30, max_gap: float = 2.00) -> list[int]:
    """Días con un hueco bajista del tamaño que busca el motor G, sin filtrar tendencia.

    Es el universo correcto para el nulo de Gap-Fade. Repartir esas operaciones sobre
    días CUALESQUIERA no sirve: en un día sin hueco la distancia del stop cae al piso y
    el apalancamiento se dispara (1% de riesgo sobre 0.15% de stop son 6.7x), así que el
    nulo quedaría comparando contra una estrategia mucho más apalancada. Restringirlo a
    días con hueco real mantiene el apalancamiento comparable, y convierte el test en la
    pregunta que importa: ¿el filtro de tendencia aporta algo por encima de operar todos
    los huecos que califican?
    """
    out = []
    for t in range(1, len(ohlc)):
        ayer = ohlc[t - 1]["c"]
        if ayer <= 0:
            continue
        gap = (ohlc[t]["o"] - ayer) / ayer * 100.0
        if -max_gap <= gap <= -min_gap:
            out.append(t)
    return out


def nulo_por_permutacion(simular, ohlc: list[dict], mask: list[bool],
                         repeticiones: int = 500, semilla: int = 20260829,
                         universo: list[int] | None = None, **kw) -> dict:
    """Distribución nula: los MISMOS días de operación, repartidos al azar en el tiempo.

    Preserva la cantidad de trades, el dimensionamiento y las reglas de salida; lo único
    que cambia es CUÁNDO se opera. Si la estrategia no le gana a esto, la señal no aporta
    nada por encima de la deriva intradía del activo.

    `universo` restringe los días candidatos. Sin él se sortea sobre todos los días, que
    es lo correcto cuando el dimensionamiento no depende de la señal (motor S). Cuando sí
    depende —el motor G calibra el stop con el tamaño del hueco— hay que pasar el universo
    de días con hueco, o el nulo compara contra otra estrategia.
    """
    n_ops = sum(1 for x in mask if x)
    if n_ops == 0:
        return {"ok": False, "motivo": "La señal no genera operaciones."}
    inicio = next((i for i, x in enumerate(mask) if x), 0)
    elegibles = ([i for i in universo if i >= inicio] if universo is not None
                 else list(range(max(inicio, 210), len(ohlc))))
    if len(elegibles) < n_ops:
        return {"ok": False, "motivo": "Muy pocos días elegibles para el nulo."}

    rng = random.Random(semilla)
    sharpes = []
    for _ in range(repeticiones):
        m2 = [False] * len(ohlc)
        for i in rng.sample(elegibles, n_ops):
            m2[i] = True
        r = simular(ohlc, m2, **kw)
        met = evaluar(r["retornos"], r["trades"])
        if met.get("sharpe") is not None:
            sharpes.append(met["sharpe"])
    if not sharpes:
        return {"ok": False, "motivo": "El nulo no produjo resultados."}
    sharpes.sort()
    n = len(sharpes)
    media = sum(sharpes) / n
    return {"ok": True, "n": n, "media": media,
            "desvio": math.sqrt(sum((s - media) ** 2 for s in sharpes) / (n - 1)) if n > 1 else 0.0,
            "p05": sharpes[int(0.05 * (n - 1))], "p50": sharpes[(n - 1) // 2],
            "p95": sharpes[int(0.95 * (n - 1))], "max": sharpes[-1], "sharpes": sharpes}


def p_empirico(observado: float, nulo: dict) -> float:
    """Fracción del nulo que iguala o supera al Sharpe observado (Davison-Hinkley)."""
    if not nulo.get("ok"):
        return float("nan")
    s = nulo["sharpes"]
    return (sum(1 for v in s if v >= observado) + 1) / (len(s) + 1)


def dias_ambiguos(ohlc: list[dict], mask: list[bool], piso_stop_pct: float = 0.15) -> dict:
    """Cuántos días de señal tocan el stop Y el objetivo (la barra diaria no los resuelve)."""
    amb = tot = 0
    for t in range(1, len(ohlc)):
        if not mask[t]:
            continue
        d = ohlc[t]
        entrada, ayer = d["o"], ohlc[t - 1]["c"]
        if entrada <= 0:
            continue
        dist = max(ayer - entrada, entrada * piso_stop_pct / 100.0)
        tot += 1
        if d["l"] <= entrada - dist and d["h"] >= entrada + dist:
            amb += 1
    return {"ambiguos": amb, "total": tot,
            "pct": round(100.0 * amb / tot, 1) if tot else 0.0}
