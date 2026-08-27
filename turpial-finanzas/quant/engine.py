"""Orquestador cuantitativo: datos reales de mercado → OU, Markov, backtest y veredicto.

Es la capa que une los conectores de Turpial con `quant/`. Todo lo que devuelve es
serializable a JSON, para que lo consuman igual la API, la SPA, el CLI y el agente IA.
"""
from __future__ import annotations

import math

from connectors import market
from quant import backtest, markov, ou, pairs

RANGO_DEFECTO = "5y"


def closes(symbol: str, rng: str = RANGO_DEFECTO) -> dict:
    """Cierres diarios de cualquier activo. Fuerza velas diarias aun en rangos largos."""
    h = market.history(symbol, rng, interval="1d")
    pts = h.get("points", [])
    return {"symbol": h.get("symbol", symbol.upper()), "rango": rng,
            "t": [p["t"] for p in pts], "c": [p["c"] for p in pts]}


def _diagnostico(p: dict, mk: dict) -> str:
    """Veredicto honesto sobre si el activo es candidato a reversión a la media."""
    if not p.get("ok"):
        return (f"No hay reversión estimable sobre el log-precio ({p.get('motivo')}). "
                "Es el resultado normal en una acción o un índice: el precio tiene tendencia. "
                "Para aplicar Ornstein-Uhlenbeck con sentido, buscá un spread cointegrado "
                "(pestaña de pares) en vez del precio suelto.")
    hl, z = p["half_life"], p["z"]
    base = (f"Half-life de {hl:.1f} días (θ={p['theta']:.4f}): la mitad de cualquier "
            f"desviación se disipa en ~{hl:.0f} días si el modelo vale. z actual = {z:.2f}.")
    if not p["estacionaria_5pct"]:
        return (base + " PERO el test de Dickey-Fuller no rechaza la raíz unitaria al 5% "
                f"(estadístico {p['df_stat']:.2f} vs crítico {ou.DF_CRITICAL['5%']}): "
                "el log-precio se comporta como un random walk. Ese half-life es un artefacto "
                "de la muestra, no una fuerza restauradora real: no hay reversión que operar. "
                "Probá el análisis de pares, donde el OU sí tiene sustento.")
    lado = "caro respecto del equilibrio" if z > 0 else "barato respecto del equilibrio"
    fuerza = ("y el resorte está estirado" if abs(z) >= 1.5
              else "pero está cerca del equilibrio: poca señal")
    mem = ""
    if mk.get("ok"):
        mem = (f" El régimen actual es {mk['regimen_actual']} con persistencia "
               f"{mk['persistencia_actual']:.0%} y duración media de "
               f"{mk['duracion_media'][mk['regimen_actual']]:.1f} barras.")
        if not mk["test_memoria"]["hay_memoria_5pct"]:
            mem += (" El χ² no encuentra memoria markoviana (p="
                    f"{mk['test_memoria']['p_valor']:.3f}): el filtro de régimen queda desactivado.")
    return (base + f" El log-precio SÍ pasa el test de estacionariedad al 5%, está {lado} "
            f"{fuerza}." + mem)


def analyze(symbol: str, rng: str = RANGO_DEFECTO, ventana: int = 250,
            entrada: float = 1.5, salida: float = 0.5, stop: float = 3.0,
            max_hold_hl: float = 3.0, cost_bps: float = 5.0,
            usar_regimen: bool = True, con_backtest: bool = True) -> dict:
    """Reporte cuantitativo completo de un activo."""
    serie = closes(symbol, rng)
    px = serie["c"]
    if len(px) < 60:
        return {"ok": False, "symbol": symbol.upper(),
                "motivo": f"Sin historial suficiente para {symbol.upper()} "
                          f"({len(px)} cierres). Probá otro símbolo o un rango mayor."}
    if any(c <= 0 for c in px):
        return {"ok": False, "symbol": symbol.upper(),
                "motivo": "La serie tiene cierres no positivos (típico de yields): "
                          "el log-precio no está definido."}

    x = [math.log(c) for c in px]
    rets = [x[i] - x[i - 1] for i in range(1, len(x))]

    params = ou.calibrate(x)
    mk = markov.analyze(rets)
    mk.pop("series_estados", None)

    out = {
        "ok": True,
        "symbol": serie["symbol"],
        "rango": rng,
        "n_cierres": len(px),
        "precio_actual": px[-1],
        "ou": _ou_publico(params),
        "markov": mk,
        "diagnostico": _diagnostico(params, mk),
    }
    if params.get("ok"):
        curva = ou.expected_path(params)
        # Se publica en precio, no en log-precio: es lo que el usuario lee en pantalla.
        for pt in curva["puntos"]:
            pt["precio_esperado"] = round(math.exp(pt["esperado"]), 4)
            pt["precio_sup"] = round(math.exp(pt["banda_sup"]), 4)
            pt["precio_inf"] = round(math.exp(pt["banda_inf"]), 4)
        for h in curva["hitos"]:
            h["precio_esperado"] = round(math.exp(h["esperado"]), 4)
        curva["precio_equilibrio"] = round(math.exp(curva["mu"]), 4)
        out["curva_decaimiento"] = curva
        out["prob_reversion"] = ou.prob_reversion(params)

    if con_backtest:
        bt = backtest.walk_forward(px, ventana=ventana, entrada=entrada, salida=salida,
                                   stop=stop, max_hold_hl=max_hold_hl, cost_bps=cost_bps,
                                   usar_regimen=usar_regimen)
        if bt.get("ok"):
            bt["metricas"].pop("curva", None)
        out["backtest"] = bt
    return out


def _ou_publico(p: dict) -> dict:
    """Parámetros del OU redondeados para API/UI (el crudo queda dentro del motor)."""
    if not p.get("ok"):
        return {"ok": False, "motivo": p.get("motivo"),
                "df_stat": round(p["df_stat"], 3) if p.get("df_stat") is not None else None,
                "df_criticos": ou.DF_CRITICAL}
    return {
        "ok": True,
        "theta": round(p["theta"], 5),
        "mu_log": round(p["mu"], 5),
        "mu_precio": round(math.exp(p["mu"]), 4),
        "sigma": round(p["sigma"], 5),
        "sigma_eq": round(p["sigma_eq"], 5),
        "half_life_dias": round(p["half_life"], 2),
        "tau_dias": round(p["tau"], 2),
        "z": round(p["z"], 3),
        "r2_ar1": round(p["r2"], 4),
        "df_stat": round(p["df_stat"], 3),
        "df_criticos": ou.DF_CRITICAL,
        "estacionaria_5pct": p["estacionaria_5pct"],
        "n": p["n"],
    }


def analyze_pair(sym_a: str, sym_b: str, rng: str = RANGO_DEFECTO, ventana: int = 250,
                 entrada: float = 2.0, salida: float = 0.5, stop: float = 3.5,
                 cost_bps: float = 5.0, con_backtest: bool = True) -> dict:
    """Cointegración + OU sobre el spread de dos activos, con series alineadas por fecha."""
    a, b = closes(sym_a, rng), closes(sym_b, rng)
    ca, cb, fechas = _alinear(a, b)
    if len(ca) < 60:
        return {"ok": False, "par": f"{sym_a.upper()}/{sym_b.upper()}",
                "motivo": f"Solo {len(ca)} fechas en común entre {a['symbol']} y {b['symbol']}: "
                          "insuficiente para estimar cointegración."}

    rep = pairs.analyze(ca, cb, a["symbol"], b["symbol"])
    if not rep.get("ok"):
        return rep
    rep["n_fechas_comunes"] = len(ca)
    rep["rango"] = rng
    rep["desde"] = fechas[0]
    rep["hasta"] = fechas[-1]
    if con_backtest:
        bt = pairs.walk_forward(ca, cb, ventana=ventana, entrada=entrada, salida=salida,
                                stop=stop, cost_bps=cost_bps)
        if bt.get("ok"):
            bt["metricas"].pop("curva", None)
        rep["backtest"] = bt
    return rep


def _alinear(a: dict, b: dict) -> tuple[list[float], list[float], list[int]]:
    """Intersecta dos series por timestamp: sin fechas comunes no hay spread válido."""
    mb = dict(zip(b["t"], b["c"]))
    ca, cb, ts = [], [], []
    for t, c in zip(a["t"], a["c"]):
        if t in mb:
            ca.append(c)
            cb.append(mb[t])
            ts.append(t)
    return ca, cb, ts
