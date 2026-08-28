"""Momentum como CONTROL POSITIVO del motor.

Todo el repo hasta acá dice "no encontré nada". Eso sólo vale si la maquinaria sería
capaz de encontrar algo cuando lo hay. Este módulo implementa los dos efectos de momentum
mejor documentados de la literatura, para usarlos como control:

  · **Cross-sectional (XSMOM)** — Jegadeesh & Titman (1993). Se ordenan los activos por su
    retorno de los últimos 12 meses saltando el último (12-1, para esquivar la reversión
    de corto plazo), se compra el tercio de arriba y se vende el de abajo, dólar-neutral.

  · **Time-series (TSMOM)** — Moskowitz, Ooi & Pedersen (2012). Cada activo se compra si su
    propio retorno a 12 meses fue positivo y se vende si fue negativo. No compite contra
    los demás: compite contra su propio pasado.

Y el complemento que hace válido al control: **un nulo empírico por permutación**. Se
repite exactamente la misma mecánica —mismas fechas, mismo rebalanceo, mismos costos,
misma matriz de covarianzas de los retornos— pero con la señal barajada al azar, cientos
de veces. El p-valor sale de comparar el Sharpe observado contra esa distribución, sin
asumir normalidad ni independencia.

Si el momentum no se distingue del ruido barajado, el problema es la maquinaria. Si se
distingue, el "no hay reversión a la media" del resto del repo es creíble.
"""
from __future__ import annotations

import math
import random

from quant.backtest import metrics


def alinear(series: dict[str, list[dict]]) -> tuple[list[int], dict[str, list[float]]]:
    """Intersecta varias series de puntos {t, c} por timestamp.

    Sin fechas comunes no hay cartera: un activo que cotiza cuando otro no, mete un
    retorno inventado en la cartera.
    """
    if not series:
        return [], {}
    comunes: set[int] | None = None
    mapas: dict[str, dict[int, float]] = {}
    for sym, pts in series.items():
        m = {p["t"]: p["c"] for p in pts if p.get("c") and p["c"] > 0}
        mapas[sym] = m
        comunes = set(m) if comunes is None else (comunes & set(m))
    fechas = sorted(comunes or [])
    return fechas, {sym: [mapas[sym][t] for t in fechas] for sym in series}


def _cartera(fechas: list[int], precios: dict[str, list[float]],
             pesos_en: callable, lookback: int, rebalanceo: int,
             cost_bps: float) -> dict:
    """Motor común: aplica `pesos_en(t)` en cada rebalanceo y acumula el P&L.

    `pesos_en` recibe el índice t y devuelve {símbolo: peso}, usando SÓLO precios hasta t.
    Los pesos se mantienen fijos entre rebalanceos; el costo se cobra sobre el turnover.
    """
    simbolos = list(precios)
    n = len(fechas)
    if n < lookback + rebalanceo + 2:
        return {"ok": False, "motivo": f"Se necesitan más de {lookback + rebalanceo + 2} "
                                       f"fechas comunes; hay {n}."}
    costo = cost_bps / 10_000.0
    pesos: dict[str, float] = {s: 0.0 for s in simbolos}
    rets: list[float] = []
    turnover_total = 0.0
    rebalanceos = 0

    for t in range(lookback, n - 1):
        if (t - lookback) % rebalanceo == 0:
            nuevos = pesos_en(t)
            turn = sum(abs(nuevos.get(s, 0.0) - pesos.get(s, 0.0)) for s in simbolos)
            turnover_total += turn
            rebalanceos += 1
            pesos = nuevos
            cargo = turn * costo
        else:
            cargo = 0.0

        # Retorno simple de la cartera: los retornos log no se suman entre activos.
        r = 0.0
        for s in simbolos:
            w = pesos.get(s, 0.0)
            if w == 0.0:
                continue
            r += w * (precios[s][t + 1] / precios[s][t] - 1.0)
        r -= cargo
        rets.append(math.log(max(1.0 + r, 1e-12)))

    m = metrics(rets, None, rebalanceos, 252)
    m.pop("curva", None)
    # rets[i] es el retorno de t -> t+1 con t = lookback + i. Para condicionar por
    # régimen hay que mirar la fecha t (cuando la posición ya estaba puesta), no la t+1.
    return {"ok": True, "metricas": m, "retornos": rets,
            "fechas_senal": fechas[lookback: n - 1],
            "rebalanceos": rebalanceos,
            "turnover_medio": round(turnover_total / max(rebalanceos, 1), 3)}


def cross_sectional(fechas: list[int], precios: dict[str, list[float]],
                    lookback: int = 252, skip: int = 21, rebalanceo: int = 21,
                    fraccion: float = 1 / 3, cost_bps: float = 5.0,
                    barajar: random.Random | None = None) -> dict:
    """XSMOM 12-1: largo el tercio ganador, corto el perdedor, dólar-neutral.

    Con `barajar` se reemplaza la señal por un orden al azar — es el nulo por permutación.
    """
    simbolos = list(precios)
    k = max(1, int(round(len(simbolos) * fraccion)))

    def pesos_en(t: int) -> dict[str, float]:
        if barajar is not None:
            orden = simbolos[:]
            barajar.shuffle(orden)
        else:
            señal = {s: precios[s][t - skip] / precios[s][t - lookback] - 1.0
                     for s in simbolos}
            orden = sorted(simbolos, key=lambda s: señal[s], reverse=True)
        w = {s: 0.0 for s in simbolos}
        for s in orden[:k]:
            w[s] = 0.5 / k          # exposición bruta total = 1.0
        for s in orden[-k:]:
            w[s] = -0.5 / k
        return w

    res = _cartera(fechas, precios, pesos_en, lookback, rebalanceo, cost_bps)
    if res.get("ok"):
        res["estrategia"] = ("XSMOM 12-1 (nulo barajado)" if barajar is not None
                             else "XSMOM 12-1")
        res["parametros"] = {"lookback": lookback, "skip": skip, "rebalanceo": rebalanceo,
                             "fraccion": fraccion, "costo_bps": cost_bps, "n_activos": len(simbolos)}
    return res


def time_series(fechas: list[int], precios: dict[str, list[float]],
                lookback: int = 252, rebalanceo: int = 21, cost_bps: float = 5.0,
                barajar: random.Random | None = None) -> dict:
    """TSMOM: cada activo largo si su retorno a `lookback` fue positivo, corto si no."""
    simbolos = list(precios)
    n_act = len(simbolos)

    def pesos_en(t: int) -> dict[str, float]:
        if barajar is not None:
            return {s: (1.0 if barajar.random() < 0.5 else -1.0) / n_act for s in simbolos}
        w = {}
        for s in simbolos:
            señal = precios[s][t] / precios[s][t - lookback] - 1.0
            w[s] = (1.0 if señal > 0 else -1.0) / n_act
        return w

    res = _cartera(fechas, precios, pesos_en, lookback, rebalanceo, cost_bps)
    if res.get("ok"):
        res["estrategia"] = ("TSMOM 12m (nulo barajado)" if barajar is not None
                             else "TSMOM 12m")
        res["parametros"] = {"lookback": lookback, "rebalanceo": rebalanceo,
                             "costo_bps": cost_bps, "n_activos": n_act}
    return res


def nulo_por_permutacion(fn, fechas, precios, repeticiones: int = 200,
                         semilla: int = 20260828, **kw) -> dict:
    """Distribución nula empírica del Sharpe: la misma estrategia con señal al azar.

    Devuelve los Sharpes del nulo, sus cuantiles y el p-valor empírico de un Sharpe
    observado (unilateral: fracción del nulo que iguala o supera al observado).
    """
    sharpes = []
    for i in range(repeticiones):
        r = fn(fechas, precios, barajar=random.Random(semilla + i), **kw)
        if r.get("ok") and r["metricas"].get("sharpe") is not None:
            sharpes.append(r["metricas"]["sharpe"])
    sharpes.sort()
    if not sharpes:
        return {"ok": False, "motivo": "El nulo no produjo resultados."}
    n = len(sharpes)
    return {
        "ok": True,
        "n": n,
        "media": sum(sharpes) / n,
        "desvio": math.sqrt(sum((s - sum(sharpes) / n) ** 2 for s in sharpes) / (n - 1))
                  if n > 1 else 0.0,
        "p05": sharpes[int(0.05 * (n - 1))],
        "p50": sharpes[(n - 1) // 2],
        "p95": sharpes[int(0.95 * (n - 1))],
        "max": sharpes[-1],
        "sharpes": sharpes,
    }


def p_empirico(observado: float, nulo: dict) -> float:
    """Fracción del nulo que iguala o supera al Sharpe observado (test unilateral)."""
    if not nulo.get("ok"):
        return float("nan")
    s = nulo["sharpes"]
    superan = sum(1 for v in s if v >= observado)
    # Corrección de Davison-Hinkley: nunca devolver p = 0 exacto con un nulo finito.
    return (superan + 1) / (len(s) + 1)


def simular_universo(n_activos: int = 20, n_dias: int = 5000, persistencia: int = 500,
                     dispersion: float = 0.0008, ruido: float = 0.010,
                     semilla: int = 1) -> tuple[list[int], dict[str, list[float]]]:
    """Universo sintético donde el momentum EXISTE por construcción.

    Cada activo tiene una deriva que se mantiene `persistencia` días y después cambia.
    Si `persistencia` supera al lookback, el retorno pasado predice el futuro y una
    estrategia de momentum tiene que encontrarlo. Es el meta-control del motor: si acá
    no lo detecta, el motor está roto y cualquier resultado negativo sobre datos reales
    no significa nada.

    Ojo con el caso inverso: con `persistencia` MENOR que el lookback la señal queda
    vieja y el momentum no se detecta aunque exista. Eso no es una falla del motor sino
    un desajuste entre el horizonte de la señal y el del efecto.
    """
    import random as _random

    rng = _random.Random(semilla)
    fechas = [i * 86400 for i in range(n_dias)]
    precios: dict[str, list[float]] = {}
    for a in range(n_activos):
        drift = rng.gauss(0, dispersion)
        px = [100.0]
        for i in range(1, n_dias):
            if i % persistencia == 0:
                drift = rng.gauss(0, dispersion)
            px.append(px[-1] * math.exp(drift + rng.gauss(0, ruido)))
        precios[f"SIM{a}"] = px
    return fechas, precios
