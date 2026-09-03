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


def skew(xs: list[float]) -> float:
    """Asimetría muestral (tercer momento estandarizado)."""
    n = len(xs)
    if n < 3:
        return 0.0
    m, sd = mean(xs), stdev(xs, ddof=0)
    if sd <= 0:
        return 0.0
    return sum(((x - m) / sd) ** 3 for x in xs) / n


def kurtosis(xs: list[float]) -> float:
    """Curtosis muestral NO centrada (3.0 = normal)."""
    n = len(xs)
    if n < 4:
        return 3.0
    m, sd = mean(xs), stdev(xs, ddof=0)
    if sd <= 0:
        return 3.0
    return sum(((x - m) / sd) ** 4 for x in xs) / n


def normal_ppf(p: float) -> float:
    """Inversa de la normal estándar (probit), por la aproximación de Acklam.

    Error absoluto < 1.15e-9. Hace falta para el Sharpe desinflado, que necesita
    cuantiles de la normal para estimar cuánto sube el máximo por puro azar cuando se
    prueban muchas combinaciones.
    """
    if not 0.0 < p < 1.0:
        return float("-inf") if p <= 0.0 else float("inf")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
