"""Arbitraje estadístico de pares — el hábitat natural del Ornstein-Uhlenbeck.

El precio de una acción sola casi nunca revierte a una media: tiene tendencia y su log
suele comportarse como un random walk (por eso el test de Dickey-Fuller casi nunca lo
rechaza). Pero la **combinación lineal de dos activos cointegrados** sí puede ser
estacionaria, y ahí el OU deja de ser una analogía y pasa a ser el modelo correcto.

Procedimiento de Engle-Granger en dos etapas:

  1. Regresión de cointegración:  log A_t = α + β·log B_t + s_t
     β es el **hedge ratio**: cuántas unidades de B shortear por cada unidad de A.
     El residuo s_t es el **spread**, la cartera de valor neto ≈ 0.

  2. Test de raíz unitaria sobre s_t. Si el spread es estacionario, el par está
     cointegrado y s_t se modela como OU: la fuerza restauradora θ·(μ − s)·dt es la
     que devuelve el spread a su nivel de equilibrio, y ln(2)/θ dice en cuántos días.

Ojo con los valores críticos: como β se estimó de los mismos datos, el estadístico ADF
sobre el residuo necesita la tabla de Engle-Granger (más exigente), no la de Dickey-Fuller.
La cointegración tampoco es eterna: se rompe con fusiones, cambios de negocio o de régimen
de tasas. Por eso el backtest re-estima β en cada ventana.
"""
from __future__ import annotations

import math

from quant import ou
from quant.backtest import metrics
from quant.stats import ols, pearson
from quant.strategies import FLAT, ou_position


def spread(log_a: list[float], log_b: list[float]) -> dict:
    """Regresión de cointegración: devuelve hedge ratio β, α y la serie del spread."""
    if len(log_a) != len(log_b) or len(log_a) < 30:
        return {"ok": False, "motivo": "Se necesitan dos series alineadas de ≥30 puntos."}
    fit = ols(log_b, log_a)
    return {"ok": True, "beta": fit["slope"], "alpha": fit["intercept"],
            "r2": fit["r2"], "spread": fit["residuals"],
            "correlacion": pearson(log_a, log_b)}


def analyze(closes_a: list[float], closes_b: list[float], sym_a: str = "A",
            sym_b: str = "B") -> dict:
    """Cointegración + OU sobre el spread: hedge ratio, half-life, z-score y veredicto."""
    if any(c <= 0 for c in closes_a) or any(c <= 0 for c in closes_b):
        return {"ok": False, "motivo": "Hay cierres no positivos en alguna de las series."}
    la = [math.log(c) for c in closes_a]
    lb = [math.log(c) for c in closes_b]
    sp = spread(la, lb)
    if not sp.get("ok"):
        return {"ok": False, "motivo": sp["motivo"]}

    params = ou.calibrate(sp["spread"])
    cointegrado = bool(params.get("ok") and
                       params["df_stat"] < ou.EG_CRITICAL["5%"])

    out = {
        "ok": True,
        "par": f"{sym_a}/{sym_b}",
        "n": len(la),
        "hedge_ratio_beta": round(sp["beta"], 4),
        "alpha": round(sp["alpha"], 4),
        "r2_cointegracion": round(sp["r2"], 4),
        "correlacion_logs": round(sp["correlacion"], 4),
        "spread_actual": round(sp["spread"][-1], 5),
        "ou": _resumen_ou(params),
        "engle_granger": {
            "estadistico": round(params["df_stat"], 3) if params.get("df_stat") is not None else None,
            "criticos": ou.EG_CRITICAL,
            "cointegrado_5pct": cointegrado,
        },
        "veredicto": _veredicto(params, cointegrado),
    }
    if params.get("ok"):
        out["curva_decaimiento"] = ou.expected_path(params)
        out["prob_reversion"] = ou.prob_reversion(params)
    return out


def _resumen_ou(p: dict) -> dict:
    if not p.get("ok"):
        return {"ok": False, "motivo": p.get("motivo")}
    return {"ok": True, "theta": round(p["theta"], 5), "mu": round(p["mu"], 5),
            "sigma": round(p["sigma"], 5), "sigma_eq": round(p["sigma_eq"], 5),
            "half_life_dias": round(p["half_life"], 2), "z": round(p["z"], 3),
            "r2_ar1": round(p["r2"], 4)}


def _veredicto(p: dict, cointegrado: bool) -> str:
    if not p.get("ok"):
        return ("El spread no revierte de forma estimable: no hay par que operar. "
                f"({p.get('motivo')})")
    hl, z = p["half_life"], p["z"]
    if not cointegrado:
        return ("El spread NO pasa el test de cointegración de Engle-Granger al 5%: "
                f"aunque salga un half-life de {hl:.1f} días, no hay evidencia estadística "
                "de reversión. Operar esto es apostar a una relación que los datos no sostienen.")
    if hl > 60:
        return (f"Cointegrado, pero el half-life es de {hl:.1f} días: la fuerza restauradora "
                "es tan débil que el capital queda inmovilizado meses por cada trade.")
    lado = "spread caro (vender A / comprar B)" if z > 0 else "spread barato (comprar A / vender B)"
    if abs(z) < 1.0:
        return (f"Cointegrado con half-life de {hl:.1f} días, pero el spread está cerca del "
                f"equilibrio (z={z:.2f}): no hay resorte estirado que aprovechar todavía.")
    return (f"Cointegrado con half-life de {hl:.1f} días y z={z:.2f} — {lado}. "
            f"El modelo espera que la mitad de la desviación se cierre en ~{hl:.0f} días.")


def walk_forward(closes_a: list[float], closes_b: list[float], ventana: int = 250,
                 entrada: float = 2.0, salida: float = 0.5, stop: float = 3.5,
                 max_hold_hl: float = 3.0, cost_bps: float = 5.0,
                 refit: int = 5, periodos_por_anio: int = 252,
                 fechas: list[int] | None = None) -> dict:
    """Backtest del par re-estimando β y el OU en cada ventana (sin look-ahead).

    El retorno de la pata es Δlog A − β·Δlog B, y el costo se cobra sobre el turnover de
    ambas patas (por eso el multiplicador (1 + |β|)).
    """
    n = min(len(closes_a), len(closes_b))
    if n < ventana + 30:
        return {"ok": False, "motivo": f"Se necesitan ≥{ventana + 30} cierres alineados; hay {n}."}
    if any(c <= 0 for c in closes_a[:n]) or any(c <= 0 for c in closes_b[:n]):
        return {"ok": False, "motivo": "Hay cierres no positivos en alguna de las series."}

    la = [math.log(c) for c in closes_a[-n:]]
    lb = [math.log(c) for c in closes_b[-n:]]
    costo = cost_bps / 10_000.0

    pos, bars_held, trades = FLAT, 0, 0
    beta, alpha, params = None, None, None
    rets: list[float] = []
    posiciones: list[int] = []
    eventos: list[dict] = []

    for t in range(ventana - 1, n - 1):
        wa, wb = la[t - ventana + 1: t + 1], lb[t - ventana + 1: t + 1]
        if params is None or (t - (ventana - 1)) % refit == 0:
            sp = spread(wa, wb)
            if sp.get("ok"):
                beta, alpha = sp["beta"], sp["alpha"]
                params = ou.calibrate(sp["spread"])
            else:
                params = {"ok": False, "motivo": sp["motivo"]}

        if params.get("ok") and beta is not None:
            # El OU se calibró sobre los residuos del OLS, que tienen media cero por
            # construcción; el nivel del spread en unidades absolutas se recentra con el
            # intercepto α de la ventana.
            s_t = la[t] - beta * lb[t]
            mu_abs = alpha + params["mu"]
            z = (s_t - mu_abs) / params["sigma_eq"] if params["sigma_eq"] > 0 else 0.0
            objetivo, motivo = ou_position(z, pos, bars_held, params["half_life"],
                                           entrada, salida, stop, max_hold_hl)
        else:
            objetivo, z, motivo = FLAT, 0.0, params.get("motivo", "calibración inválida")

        turnover = abs(objetivo - pos)
        if turnover:
            trades += 1
            eventos.append({"i": t, "de": pos, "a": objetivo, "z": round(z, 3),
                            "beta": round(beta, 4) if beta else None, "motivo": motivo})
        bars_held = bars_held + 1 if objetivo == pos and objetivo != FLAT else (
            1 if objetivo != FLAT else 0)
        pos = objetivo

        r_par = (la[t + 1] - la[t]) - (beta or 0.0) * (lb[t + 1] - lb[t])
        rets.append(pos * r_par - turnover * costo * (1.0 + abs(beta or 0.0)))
        posiciones.append(pos)

    res = metrics(rets, posiciones, trades, periodos_por_anio)
    res["curva"] = [round(v, 5) for v in res["curva"]]
    # rets[i] se gana entre la barra t = ventana-1+i y la siguiente; para condicionar por
    # régimen hace falta la fecha t, cuando la posición ya estaba puesta.
    primera = ventana - 1
    fechas_senal = (fechas[-n:][primera: primera + len(rets)]
                    if fechas and len(fechas) >= n else None)
    return {"ok": True, "estrategia": "Pares cointegrados (OU sobre el spread)",
            "retornos": rets, "fechas_senal": fechas_senal, "primera_barra": primera,
            "parametros": {"ventana": ventana, "entrada_z": entrada, "salida_z": salida,
                           "stop_z": stop, "max_hold_half_lives": max_hold_hl,
                           "costo_bps": cost_bps, "refit_cada": refit,
                           "periodos_por_anio": periodos_por_anio},
            "beta_final": round(beta, 4) if beta else None,
            "metricas": res, "ultimos_eventos": eventos[-15:], "n_eventos": len(eventos)}
