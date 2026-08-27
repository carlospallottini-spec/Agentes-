"""Backtest walk-forward y métricas de performance.

Regla de oro: **nada de sesgo de anticipación (look-ahead)**. En cada barra t los
parámetros del OU (μ, σ_eq, half-life) y la matriz de Markov se estiman con una ventana
que termina en t, la señal se decide con esa información, y el P&L se cobra con el
retorno de t → t+1. Calibrar el OU sobre toda la muestra y después "operar" ese z-score
produce curvas espectaculares e irreproducibles: es leer el diario de mañana.

Costos: `cost_bps` se cobra sobre el cambio de posición (|Δpos|), así que dar vuelta una
posición de larga a corta paga dos veces. Cubre comisión + spread de forma aproximada.
"""
from __future__ import annotations

import math

from quant import markov, ou
from quant.stats import mean, stdev
from quant.strategies import FLAT, ou_position, regime_allows

ANUAL = 252  # barras de trading por año para anualizar


def metrics(rets: list[float], posiciones: list[int] | None = None,
            n_trades: int = 0, periodos_por_anio: int = ANUAL) -> dict:
    """Métricas sobre una serie de retornos LOG por barra."""
    n = len(rets)
    if n == 0:
        return {"n": 0}
    total_log = sum(rets)
    equity, peak, max_dd = 1.0, 1.0, 0.0
    curva = []
    for r in rets:
        equity *= math.exp(r)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curva.append(equity)

    m = mean(rets)
    s = stdev(rets) if n > 1 else 0.0
    neg = [r for r in rets if r < 0]
    s_down = stdev(neg) if len(neg) > 1 else 0.0
    anios = n / periodos_por_anio
    cagr = math.exp(total_log / anios) - 1.0 if anios > 0 else 0.0
    activos = [r for r, p in zip(rets, posiciones or [])if p != FLAT] if posiciones else rets
    ganadores = sum(1 for r in activos if r > 0)

    return {
        "n": n,
        "retorno_total_pct": round((math.exp(total_log) - 1.0) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "vol_anual_pct": round(s * math.sqrt(periodos_por_anio) * 100, 2),
        "sharpe": round(m / s * math.sqrt(periodos_por_anio), 2) if s > 0 else None,
        "sortino": round(m / s_down * math.sqrt(periodos_por_anio), 2) if s_down > 0 else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar": round(cagr / max_dd, 2) if max_dd > 1e-9 else None,
        "hit_rate_pct": round(ganadores / len(activos) * 100, 1) if activos else None,
        "trades": n_trades,
        "exposicion_pct": (round(sum(1 for p in posiciones if p != FLAT) / n * 100, 1)
                           if posiciones else 100.0),
        "equity_final": round(equity, 4),
        "curva": curva,
    }


def walk_forward(closes: list[float], ventana: int = 250, entrada: float = 1.5,
                 salida: float = 0.5, stop: float = 3.0, max_hold_hl: float = 3.0,
                 cost_bps: float = 5.0, usar_regimen: bool = True,
                 refit: int = 5) -> dict:
    """Corre la estrategia OU (+ filtro de régimen) sobre una serie de cierres.

    `ventana` es el largo de la ventana móvil de calibración, `refit` cada cuántas barras
    se re-estiman los parámetros (5 = una vez por semana bursátil; 1 = cada barra).
    """
    if len(closes) < ventana + 30:
        return {"ok": False,
                "motivo": f"Se necesitan al menos {ventana + 30} cierres; hay {len(closes)}."}
    if any(c <= 0 for c in closes):
        return {"ok": False, "motivo": "Hay cierres no positivos: el log-precio no está definido."}

    x = [math.log(c) for c in closes]
    costo = cost_bps / 10_000.0

    pos, bars_held, trades = FLAT, 0, 0
    params: dict | None = None
    regimen: dict | None = None
    rets: list[float] = []
    posiciones: list[int] = []
    bh: list[float] = []
    eventos: list[dict] = []
    bloqueos = 0

    for t in range(ventana - 1, len(x) - 1):
        win = x[t - ventana + 1: t + 1]
        if params is None or (t - (ventana - 1)) % refit == 0:
            params = ou.calibrate(win)
            if usar_regimen:
                r_win = [win[i] - win[i - 1] for i in range(1, len(win))]
                regimen = markov.analyze(r_win)

        if params.get("ok"):
            sigma_eq = params["sigma_eq"]
            z = (x[t] - params["mu"]) / sigma_eq if sigma_eq > 0 else 0.0
            objetivo, motivo = ou_position(z, pos, bars_held, params["half_life"],
                                           entrada, salida, stop, max_hold_hl)
            if objetivo != pos and objetivo != FLAT and usar_regimen:
                if not regime_allows(objetivo, regimen):
                    objetivo, motivo = pos, "bloqueado por régimen persistente"
                    bloqueos += 1
        else:
            # Sin reversión estimable no se opera: la hipótesis del modelo no se cumple.
            objetivo, z, motivo = FLAT, 0.0, params.get("motivo", "calibración inválida")

        turnover = abs(objetivo - pos)
        if turnover:
            trades += 1
            eventos.append({"i": t, "de": pos, "a": objetivo, "z": round(z, 3),
                            "motivo": motivo,
                            "half_life": round(params["half_life"], 2)
                                         if params.get("ok") else None})
        bars_held = bars_held + 1 if objetivo == pos and objetivo != FLAT else (
            1 if objetivo != FLAT else 0)
        pos = objetivo

        r_next = x[t + 1] - x[t]
        rets.append(pos * r_next - turnover * costo)
        posiciones.append(pos)
        bh.append(r_next)

    resultado = metrics(rets, posiciones, trades)
    resultado["curva"] = [round(v, 5) for v in resultado["curva"]]
    comparacion = metrics(bh)
    comparacion.pop("curva", None)

    return {
        "ok": True,
        "estrategia": "OU mean-reversion" + (" + filtro Markov" if usar_regimen else ""),
        "parametros": {"ventana": ventana, "entrada_z": entrada, "salida_z": salida,
                       "stop_z": stop, "max_hold_half_lives": max_hold_hl,
                       "costo_bps": cost_bps, "refit_cada": refit,
                       "filtro_regimen": usar_regimen},
        "metricas": resultado,
        "buy_and_hold": comparacion,
        "señales_bloqueadas_por_regimen": bloqueos,
        "ultimos_eventos": eventos[-15:],
        "n_eventos": len(eventos),
    }
