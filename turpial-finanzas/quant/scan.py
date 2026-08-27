"""Escaneo sistemático de instrumentos y pares, con estadística de verdad.

Correr un backtest y mirar el Sharpe es la forma más rápida de engañarse. Este módulo
existe para hacer las dos preguntas que evitan ese engaño:

  1. **¿Este Sharpe se distingue de cero?** Un Sharpe estimado sobre T años tiene error
     estándar ≈ sqrt((1 + S²/2) / T) — el resultado de Lo (2002). Con 2 meses de datos,
     T = 0.16, y el error estándar es 2.5: un Sharpe de 2 es indistinguible de nada.

  2. **¿Cuántas hipótesis probé para llegar acá?** Testeando 20 candidatos al 5%, el azar
     regala 1 ganador. Testeando 100, regala 5. Se aplican dos correcciones:
     **Bonferroni** (conservadora: exige p < α/N) y **Benjamini-Hochberg** (controla la
     proporción de falsos descubrimientos, menos brutal y más útil cuando N es grande).

El punto no es encontrar el mejor resultado de la tabla: es saber si el mejor resultado
de la tabla es distinguible del mejor resultado de una tabla de puro ruido.
"""
from __future__ import annotations

import math

from quant import backtest, ou
from quant.stats import normal_cdf


# ------------------------------------------------------- significancia del Sharpe
def sharpe_se(sharpe: float, n_obs: int, periodos_por_anio: float) -> float:
    """Error estándar de un Sharpe anualizado estimado sobre `n_obs` barras (Lo, 2002).

        SE(Ŝ) ≈ sqrt( (1 + Ŝ²/2) / T ),  con T = años de muestra

    Asume retornos iid; con autocorrelación el error real es MAYOR, así que esto es
    una cota optimista y aun así suele alcanzar para descartar resultados.
    """
    anios = n_obs / periodos_por_anio
    if anios <= 0:
        return float("inf")
    return math.sqrt((1.0 + 0.5 * sharpe * sharpe) / anios)


def sharpe_pvalue(sharpe: float, n_obs: int, periodos_por_anio: float) -> tuple[float, float]:
    """(t-stat, p-valor bilateral) de H0: Sharpe verdadero = 0."""
    se = sharpe_se(sharpe, n_obs, periodos_por_anio)
    if se == 0 or not math.isfinite(se):
        return 0.0, 1.0
    t = sharpe / se
    return t, 2.0 * (1.0 - normal_cdf(abs(t)))


# ------------------------------------------------------ corrección multiplicidad
def bonferroni(pvalores: list[float], alpha: float = 0.05) -> dict:
    """Corrección de Bonferroni: sobrevive quien cumple p < α/N."""
    n = len(pvalores)
    if n == 0:
        return {"umbral": alpha, "sobreviven": [], "n": 0}
    umbral = alpha / n
    return {"umbral": umbral, "sobreviven": [p < umbral for p in pvalores], "n": n}


def benjamini_hochberg(pvalores: list[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg: controla la tasa de falsos descubrimientos (FDR).

    Ordena los p-valores y busca el mayor k tal que p_(k) <= k·α/N; todos los p-valores
    hasta ese k se declaran descubrimientos.
    """
    n = len(pvalores)
    if n == 0:
        return {"umbral": 0.0, "sobreviven": [], "n": 0, "k": 0}
    indexados = sorted(enumerate(pvalores), key=lambda x: x[1])
    k = 0
    for rango, (_, p) in enumerate(indexados, start=1):
        if p <= rango * alpha / n:
            k = rango
    umbral = k * alpha / n if k else 0.0
    sobreviven = [False] * n
    for rango, (idx, _) in enumerate(indexados, start=1):
        if rango <= k:
            sobreviven[idx] = True
    return {"umbral": umbral, "sobreviven": sobreviven, "n": n, "k": k}


# --------------------------------------------------------------------- utilidades
def periodos_por_anio(timestamps: list[int]) -> float:
    """Cuántas barras tiene un año en ESTA serie, medido de los propios timestamps.

    Se calcula empíricamente en vez de asumir 252: una serie de 5 minutos de crypto
    (24/7) y una de 5 minutos de acciones (6.5 h/día) tienen anualizaciones muy distintas,
    y equivocarse acá cambia el Sharpe por un factor grande.
    """
    if len(timestamps) < 2:
        return 252.0
    span_seg = timestamps[-1] - timestamps[0]
    if span_seg <= 0:
        return 252.0
    barras_por_seg = (len(timestamps) - 1) / span_seg
    return barras_por_seg * 365.25 * 86400.0


def diagnostico_gaps(timestamps: list[int]) -> dict:
    """Mide los huecos de sesión: el OU asume barras equiespaciadas y los fines de
    semana o los cierres nocturnos rompen ese supuesto."""
    if len(timestamps) < 3:
        return {"mediana_seg": 0, "huecos_grandes": 0, "pct_huecos": 0.0}
    difs = sorted(timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps)))
    mediana = difs[len(difs) // 2]
    grandes = sum(1 for d in difs if d > 3 * mediana)
    return {"mediana_seg": mediana, "huecos_grandes": grandes,
            "pct_huecos": round(100.0 * grandes / len(difs), 2)}


# ------------------------------------------------------------------------ escaneo
def evaluar(closes: list[float], timestamps: list[int], etiqueta: str,
            ventana: int = 250, entrada: float = 1.5, salida: float = 0.5,
            stop: float = 3.0, max_hold_hl: float = 3.0, cost_bps: float = 1.0,
            usar_regimen: bool = True, refit: int = 5,
            exigir_estacionaria: bool = False) -> dict | None:
    """Corre la estrategia sobre una serie y devuelve la fila del escaneo."""
    if len(closes) < ventana + 60:
        return None
    ppa = periodos_por_anio(timestamps)
    bt = backtest.walk_forward(closes, ventana=ventana, entrada=entrada, salida=salida,
                               stop=stop, max_hold_hl=max_hold_hl, cost_bps=cost_bps,
                               usar_regimen=usar_regimen, refit=refit,
                               periodos_por_anio=int(ppa),
                               exigir_estacionaria=exigir_estacionaria)
    if not bt.get("ok"):
        return None
    m = bt["metricas"]
    m.pop("curva", None)
    sh = m.get("sharpe") or 0.0
    t, p = sharpe_pvalue(sh, m["n"], ppa)

    # ¿Con qué frecuencia el gate de Dickey-Fuller habilitaría a operar?
    x = [math.log(c) for c in closes]
    pasa = tot = 0
    for i in range(ventana - 1, len(x), max(refit, 1) * 10):
        par = ou.calibrate(x[i - ventana + 1: i + 1])
        tot += 1
        if par.get("ok") and par["estacionaria_5pct"]:
            pasa += 1

    return {
        "etiqueta": etiqueta,
        "n_barras": m["n"],
        "anios": round(m["n"] / ppa, 3),
        "periodos_por_anio": round(ppa),
        "sharpe": sh,
        "t_stat": round(t, 2),
        "p_valor": p,
        "retorno_pct": m["retorno_total_pct"],
        "max_dd_pct": m["max_drawdown_pct"],
        "trades": m["trades"],
        "exposicion_pct": m["exposicion_pct"],
        "gate_pasa_pct": round(100.0 * pasa / tot, 1) if tot else 0.0,
        "gate_activo": exigir_estacionaria,
        "bh_sharpe": bt["buy_and_hold"].get("sharpe"),
        "gaps": diagnostico_gaps(timestamps),
    }


def resumir(filas: list[dict], alpha: float = 0.05) -> dict:
    """Aplica las correcciones por multiplicidad y arma el veredicto del escaneo."""
    if not filas:
        return {"n": 0}
    ps = [f["p_valor"] for f in filas]
    bonf = bonferroni(ps, alpha)
    bh = benjamini_hochberg(ps, alpha)
    for f, b1, b2 in zip(filas, bonf["sobreviven"], bh["sobreviven"]):
        f["sobrevive_bonferroni"] = b1
        f["sobrevive_bh"] = b2
    shs = [f["sharpe"] for f in filas]
    n = len(shs)
    media = sum(shs) / n
    var = sum((s - media) ** 2 for s in shs) / (n - 1) if n > 1 else 0.0
    desvio = math.sqrt(var)
    se_media = desvio / math.sqrt(n) if n > 1 else float("inf")
    return {
        "n": n,
        "sharpe_medio": round(media, 3),
        "sharpe_desvio": round(desvio, 3),
        "t_de_la_media": round(media / se_media, 2) if se_media > 0 else 0.0,
        "positivos": sum(1 for s in shs if s > 0),
        "nominales_5pct": sum(1 for p in ps if p < alpha),
        "esperados_por_azar": round(alpha * n, 1),
        "sobreviven_bonferroni": sum(bonf["sobreviven"]),
        "umbral_bonferroni": bonf["umbral"],
        "sobreviven_bh": sum(bh["sobreviven"]),
        "umbral_bh": bh["umbral"],
    }
