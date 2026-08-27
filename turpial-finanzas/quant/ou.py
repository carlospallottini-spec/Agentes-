"""Proceso de Ornstein-Uhlenbeck — la fuerza restauradora, y su curva de decaimiento.

La ecuación diferencial estocástica (EDE) es:

    dX_t = θ·(μ − X_t)·dt + σ·dW_t

    · θ (theta) > 0  : velocidad de reversión — la "constante del resorte".
    · μ (mu)         : nivel de equilibrio al que el proceso es atraído.
    · σ (sigma)      : volatilidad instantánea del shock browniano dW.

El término θ·(μ − X_t)·dt es literalmente una **fuerza restauradora**: si X está por
encima de μ, el drift es negativo y empuja hacia abajo; si está por debajo, empuja hacia
arriba. La fuerza es proporcional a la distancia al equilibrio, igual que la ley de Hooke.

**Solución determinística (curva de decaimiento).** Tomando esperanza sobre la EDE se
cancela el ruido (E[dW]=0) y queda una EDO lineal de primer orden:

    dE[X_t]/dt = θ·(μ − E[X_t])   ⟹   E[X_t | X_0] = μ + (X_0 − μ)·e^(−θ·t)

La desviación respecto al equilibrio decae **exponencialmente** con constante de tiempo
1/θ. El **half-life** es el tiempo en que esa desviación se reduce a la mitad:

    (X_0 − μ)·e^(−θ·t½) = ½·(X_0 − μ)   ⟹   t½ = ln(2) / θ

**Varianza condicional y distribución estacionaria.**

    Var[X_t | X_0] = σ²·(1 − e^(−2θt)) / (2θ)   →   σ²_eq = σ² / (2θ)  cuando t → ∞

El proceso no explota como un random walk: su dispersión satura en σ_eq. Por eso el
z-score z = (X − μ)/σ_eq es una medida estacionaria de "cuán estirado está el resorte".

**Calibración (discretización exacta).** Muestreando cada Δt, el OU tiene solución
exacta AR(1) — no hace falta discretizar por Euler:

    X_(i+1) = X_i·e^(−θΔt) + μ·(1 − e^(−θΔt)) + ε_i ,  ε_i ~ N(0, σ²(1−e^(−2θΔt))/(2θ))

que es una regresión lineal X_(i+1) = a + b·X_i + ε. Deshaciendo el cambio de variable:

    θ = −ln(b)/Δt        μ = a/(1−b)        σ = σ_ε·sqrt(2θ / (1 − b²))

Si b ≥ 1 no hay reversión (random walk o explosivo) y la calibración se declara inválida.
"""
from __future__ import annotations

import math

from quant.stats import normal_cdf, ols

# Valores críticos de Dickey-Fuller (regresión con constante, sin tendencia).
# El t-stat de (b−1) NO sigue una t de Student bajo la hipótesis nula de raíz
# unitaria, por eso se compara contra esta tabla y no contra ±1.96.
DF_CRITICAL = {"1%": -3.43, "5%": -2.86, "10%": -2.57}

# Engle-Granger: al testear el residuo de una cointegración estimada (2 series), los
# valores críticos son más exigentes porque la regresión ya "buscó" estacionariedad.
EG_CRITICAL = {"1%": -3.90, "5%": -3.34, "10%": -3.04}


def calibrate(series: list[float], dt: float = 1.0) -> dict:
    """Calibra θ, μ, σ por OLS sobre la discretización exacta AR(1) del OU.

    `series` son observaciones equiespaciadas (ej. log-precios diarios) y `dt` el paso
    en las mismas unidades en que se quiere leer θ y el half-life (dt=1 → días).

    Devuelve siempre un dict con `ok`: si `ok` es False, `motivo` explica por qué la
    reversión no es estimable (serie corta, pendiente ≥ 1, etc.).
    """
    if len(series) < 30:
        return {"ok": False, "motivo": "Serie demasiado corta para calibrar (mínimo 30 puntos)."}

    x, y = series[:-1], series[1:]
    try:
        fit = ols(x, y)
    except ValueError as e:
        return {"ok": False, "motivo": str(e)}

    b, a = fit["slope"], fit["intercept"]

    # Test de estacionariedad (Dickey-Fuller): ΔX = a + (b−1)·X + ε.
    # El t-stat de (b−1) es el mismo que el de b desplazado, con idéntico error estándar.
    df_stat = (b - 1.0) / fit["se_slope"] if fit["se_slope"] > 0 else float("-inf")

    if b <= 0.0:
        return {"ok": False, "motivo": "Pendiente AR(1) ≤ 0: oscilación, no reversión suave.",
                "df_stat": df_stat}
    if b >= 1.0:
        return {"ok": False,
                "motivo": "Pendiente AR(1) ≥ 1: la serie no revierte (random walk o explosiva).",
                "df_stat": df_stat}

    theta = -math.log(b) / dt
    mu = a / (1.0 - b)
    sigma_eps = fit["resid_std"]
    sigma = sigma_eps * math.sqrt(2.0 * theta / (1.0 - b * b))
    sigma_eq = sigma / math.sqrt(2.0 * theta)      # = sigma_eps / sqrt(1 − b²)
    half_life = math.log(2.0) / theta

    last = series[-1]
    z = (last - mu) / sigma_eq if sigma_eq > 0 else 0.0

    return {
        "ok": True,
        "theta": theta,                 # velocidad de reversión (1/unidad de tiempo)
        "mu": mu,                       # nivel de equilibrio
        "sigma": sigma,                 # volatilidad instantánea
        "sigma_eq": sigma_eq,           # desvío estándar de la distribución estacionaria
        "half_life": half_life,         # ln(2)/θ, en unidades de dt
        "tau": 1.0 / theta,             # constante de tiempo: decae al 36.8% (1/e)
        "ar1_b": b,
        "ar1_a": a,
        "r2": fit["r2"],
        "n": fit["n"],
        "last": last,
        "z": z,                         # z-score estacionario del último dato
        "df_stat": df_stat,
        "df_criticos": DF_CRITICAL,
        "estacionaria_5pct": df_stat < DF_CRITICAL["5%"],
        "dt": dt,
    }


def expected_path(params: dict, x0: float | None = None, horizon: float | None = None,
                  steps: int = 60) -> dict:
    """Curva de decaimiento del half-life: E[X_t|X_0] = μ + (X_0−μ)·e^(−θt).

    Devuelve los puntos para graficar la trayectoria esperada y su banda de ±1σ
    condicional, más las marcas de 1, 2 y 3 half-lives (50%, 25% y 12.5% de la
    desviación inicial). El horizonte por defecto son 3 half-lives.
    """
    if not params.get("ok"):
        return {"ok": False, "motivo": params.get("motivo", "Calibración inválida.")}

    theta, mu, sigma = params["theta"], params["mu"], params["sigma"]
    hl = params["half_life"]
    x0 = params["last"] if x0 is None else x0
    horizon = 3.0 * hl if horizon is None else horizon
    dev0 = x0 - mu

    pts = []
    for i in range(steps + 1):
        t = horizon * i / steps
        decay = math.exp(-theta * t)
        var_t = sigma * sigma * (1.0 - math.exp(-2.0 * theta * t)) / (2.0 * theta)
        sd = math.sqrt(max(var_t, 0.0))
        pts.append({
            "t": round(t, 4),
            "esperado": mu + dev0 * decay,
            "desvio_restante_pct": round(decay * 100.0, 2),
            "banda_sup": mu + dev0 * decay + sd,
            "banda_inf": mu + dev0 * decay - sd,
        })

    hitos = [{
        "half_lives": k,
        "t": round(k * hl, 3),
        "desvio_restante_pct": round(100.0 / (2 ** k), 2),
        "esperado": mu + dev0 / (2 ** k),
    } for k in (1, 2, 3)]

    return {"ok": True, "mu": mu, "x0": x0, "half_life": hl, "horizonte": horizon,
            "puntos": pts, "hitos": hitos}


def prob_reversion(params: dict, horizon: float | None = None) -> dict:
    """P(el proceso cruce el equilibrio antes del horizonte) — cota por distribución final.

    Usa la ley condicional X_h | X_0 ~ N(m_h, v_h) del OU y calcula la probabilidad de
    estar del otro lado de μ en h. Es una cota inferior de la probabilidad de *tocar* μ
    (el proceso pudo cruzar y volver), y se reporta como tal.
    """
    if not params.get("ok"):
        return {"ok": False, "motivo": params.get("motivo", "Calibración inválida.")}

    theta, mu, sigma, x0 = params["theta"], params["mu"], params["sigma"], params["last"]
    h = params["half_life"] if horizon is None else horizon
    m = mu + (x0 - mu) * math.exp(-theta * h)
    v = sigma * sigma * (1.0 - math.exp(-2.0 * theta * h)) / (2.0 * theta)
    sd = math.sqrt(max(v, 1e-18))
    # Si arrancó por debajo de μ, "revertir" es terminar por encima, y viceversa.
    p = 1.0 - normal_cdf((mu - m) / sd) if x0 < mu else normal_cdf((mu - m) / sd)
    return {"ok": True, "horizonte": h, "media_h": m, "desvio_h": sd,
            "prob_cruce_en_h": round(p, 4)}


def simulate(theta: float, mu: float, sigma: float, x0: float, n: int,
             dt: float = 1.0, seed: int = 7) -> list[float]:
    """Simula un OU por su discretización EXACTA (no Euler): sirve para tests y stress."""
    import random

    rng = random.Random(seed)
    b = math.exp(-theta * dt)
    sd_eps = sigma * math.sqrt((1.0 - b * b) / (2.0 * theta))
    out, x = [x0], x0
    for _ in range(n - 1):
        x = x * b + mu * (1.0 - b) + rng.gauss(0.0, sd_eps)
        out.append(x)
    return out
