"""Orquestador cuantitativo: datos reales de mercado → OU, Markov, backtest y veredicto.

Es la capa que une los conectores de Turpial con `quant/`. Todo lo que devuelve es
serializable a JSON, para que lo consuman igual la API, la SPA, el CLI y el agente IA.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from connectors import market
from quant import backtest, markov, ou, pairs

RANGO_DEFECTO = "5y"


# Rangos en años -> días de calendario a pedir.
_ANIOS = {"6mo": 183, "1y": 365, "2y": 730, "3y": 1095, "5y": 1825, "7y": 2555,
          "10y": 3650, "15y": 5475, "20y": 7300, "max": 10950}


def closes(symbol: str, rng: str = RANGO_DEFECTO) -> dict:
    """Cierres diarios de cualquier activo, pedidos por timestamps.

    Se usa `velas()` en vez de `history()` porque los rangos con nombre degradan la
    granularidad en histórico largo: `range=max` con `interval=1d` devuelve velas
    MENSUALES. Pidiendo por días se obtienen las diarias hasta donde llegue el feed.
    """
    dias = _ANIOS.get(rng, _ANIOS[RANGO_DEFECTO])
    h = market.velas(symbol, "1d", dias)
    pts = [p for p in h.get("points", []) if p.get("c") and p["c"] > 0]
    return {"symbol": h.get("symbol", symbol.upper()), "rango": rng, "dias": dias,
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
    rep["sincronia"] = sincronia(a, b)
    hl = rep["ou"].get("half_life_dias")
    # Un símbolo que empieza con "^" es un ÍNDICE: se puede calcular, no comprar. Un par
    # con una pata así puede dar cointegración perfecta y no ser operable ni en teoría.
    rep["pata_no_operable"] = sym_a.startswith("^") or sym_b.startswith("^")
    rep["sospecha_artefacto"] = bool(
        rep["pata_no_operable"]
        or not rep["sincronia"]["sincronicas"]
        or (hl is not None and hl < 3.0))
    rep["rango"] = rng
    rep["desde"] = fechas[0]
    rep["hasta"] = fechas[-1]
    if con_backtest:
        bt = pairs.walk_forward(ca, cb, ventana=ventana, entrada=entrada, salida=salida,
                                stop=stop, cost_bps=cost_bps, fechas=fechas)
        if bt.get("ok"):
            bt["metricas"].pop("curva", None)
        rep["backtest"] = bt
    return rep


def _hora_modal(timestamps: list[int]) -> str:
    """Hora UTC más frecuente del sello de las velas (identifica la sesión)."""
    from collections import Counter
    if not timestamps:
        return "?"
    horas = Counter(datetime.fromtimestamp(t, tz=timezone.utc).strftime("%H:%M")
                    for t in timestamps[-500:])
    return horas.most_common(1)[0][0]


def sincronia(a: dict, b: dict) -> dict:
    """¿Las dos series cierran en el mismo momento?

    Es el chequeo que separa un spread real de un artefacto. Los futuros de metales
    liquidan a las 13:30 ET y los ETFs a las 16:00 ET: el "spread" entre el cierre de
    GC=F y el de GLD contiene 2.5 horas de movimiento del oro que el futuro no vio, y
    ese desfase revierte solo al día siguiente. Da cointegración altísima y un half-life
    de 1-2 días — o sea, del orden de UNA barra — y no se puede operar, porque no se
    puede comprar y vender en dos momentos distintos del mismo instante.

    Regla práctica: si las series no son sincrónicas, o si el half-life es del orden de
    una o dos barras, el resultado es del calendario y no del mercado.
    """
    ha, hb = _hora_modal(a["t"]), _hora_modal(b["t"])
    return {"hora_a": ha, "hora_b": hb, "sincronicas": ha == hb}


def _alinear(a: dict, b: dict) -> tuple[list[float], list[float], list[int]]:
    """Intersecta dos series diarias por FECHA de calendario (UTC), no por timestamp.

    Los futuros, los ETFs y los índices extranjeros estampan la vela diaria a horas
    distintas: un futuro cierra a las 21:00 UTC y un ETF a las 20:00, así que
    intersectar por timestamp exacto devuelve casi nada. Comparar GC=F con GLD daba
    20 fechas en común en vez de 2500. Se agrupa por día y se toma el último cierre.
    """
    def por_dia(serie: dict) -> dict[str, tuple[int, float]]:
        out: dict[str, tuple[int, float]] = {}
        for t, c in zip(serie["t"], serie["c"]):
            dia = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
            if dia not in out or t >= out[dia][0]:
                out[dia] = (t, c)
        return out

    ma, mb = por_dia(a), por_dia(b)
    ca, cb, ts = [], [], []
    for dia in sorted(set(ma) & set(mb)):
        ta, va = ma[dia]
        _, vb = mb[dia]
        ca.append(va)
        cb.append(vb)
        ts.append(ta)
    return ca, cb, ts
