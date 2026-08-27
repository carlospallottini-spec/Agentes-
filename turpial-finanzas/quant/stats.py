"""Estadística base en Python puro — sin numpy, sin scipy.

Todo el stack cuantitativo de Turpial (Ornstein-Uhlenbeck, Markov, backtest) se apoya
en estas primitivas. Se mantienen en la librería estándar a propósito: el servicio
deployado no necesita compilar ruedas científicas para calcular una regresión de 2
parámetros ni una matriz de transición de 3x3.
"""
from __future__ import annotations

import math

# --------------------------------------------------------------------- momentos


def mean(xs: list[float]) -> float:
    if not xs:
        raise ValueError("mean() de una serie vacía")
    return sum(xs) / len(xs)


def variance(xs: list[float], ddof: int = 1) -> float:
    """Varianza muestral (ddof=1) o poblacional (ddof=0)."""
    n = len(xs)
    if n - ddof <= 0:
        raise ValueError("varianza indefinida: muy pocos puntos")
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - ddof)


def stdev(xs: list[float], ddof: int = 1) -> float:
    return math.sqrt(variance(xs, ddof))


def pearson(xs: list[float], ys: list[float]) -> float:
    """Correlación lineal de Pearson en [-1, 1]."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("pearson() necesita dos series de igual largo (>=2)")
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def quantile(xs: list[float], q: float) -> float:
    """Cuantil por interpolación lineal (mismo criterio que numpy.quantile)."""
    if not xs:
        raise ValueError("quantile() de una serie vacía")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


# ------------------------------------------------------------------- regresión


def ols(x: list[float], y: list[float]) -> dict:
    """Mínimos cuadrados de y = a + b·x.

    Devuelve pendiente, intercepto, sus errores estándar, el t-stat de la pendiente,
    R², la desviación estándar de los residuos y los residuos mismos. Los errores
    estándar son los que después alimentan el test de estacionariedad (Dickey-Fuller).
    """
    n = len(x)
    if n != len(y) or n < 3:
        raise ValueError("ols() necesita dos series de igual largo (>=3)")
    mx, my = mean(x), mean(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx <= 0:
        raise ValueError("ols() con regresor constante: pendiente indefinida")
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    b = sxy / sxx
    a = my - b * mx
    resid = [yi - (a + b * xi) for xi, yi in zip(x, y)]
    sse = sum(r * r for r in resid)
    sst = sum((yi - my) ** 2 for yi in y)
    dof = n - 2
    s2 = sse / dof                      # varianza residual insesgada
    se_b = math.sqrt(s2 / sxx)
    se_a = math.sqrt(s2 * (1.0 / n + mx * mx / sxx))
    return {
        "slope": b,
        "intercept": a,
        "se_slope": se_b,
        "se_intercept": se_a,
        "t_slope": b / se_b if se_b > 0 else float("inf"),
        "r2": 1.0 - sse / sst if sst > 0 else 0.0,
        "resid_std": math.sqrt(s2),
        "residuals": resid,
        "n": n,
    }


# ------------------------------------------------------- distribuciones (colas)


def normal_cdf(z: float) -> float:
    """Φ(z): probabilidad acumulada de una normal estándar."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _gamma_p(s: float, x: float) -> float:
    """P(s, x) — gamma incompleta regularizada inferior, por serie de potencias."""
    total, term = 1.0 / s, 1.0 / s
    for k in range(1, 500):
        term *= x / (s + k)
        total += term
        if abs(term) < abs(total) * 1e-14:
            break
    return total * math.exp(-x + s * math.log(x) - math.lgamma(s))


def _gamma_q(s: float, x: float) -> float:
    """Q(s, x) — gamma incompleta regularizada superior, por fracción continua."""
    tiny = 1e-300
    b, c, d = x + 1.0 - s, 1.0 / tiny, 1.0 / (x + 1.0 - s)
    h = d
    for i in range(1, 500):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h * math.exp(-x + s * math.log(x) - math.lgamma(s))


def chi2_sf(stat: float, df: int) -> float:
    """P(X > stat) para una chi-cuadrado con `df` grados de libertad (p-valor)."""
    if df <= 0:
        return float("nan")
    if stat <= 0:
        return 1.0
    s, x = df / 2.0, stat / 2.0
    return 1.0 - _gamma_p(s, x) if x < s + 1.0 else _gamma_q(s, x)
