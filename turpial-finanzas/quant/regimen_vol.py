"""Régimen de volatilidad implícita (VIX): condicionar los resultados por estado del mercado.

Un Sharpe promedio esconde que casi toda estrategia se comporta distinto según el clima.
El VIX parte el tiempo en tres regímenes con carácter propio:

  · **Bajo** (VIX < 17): complacencia. Tendencias suaves, poca dispersión, spreads finos.
  · **Medio** (17 ≤ VIX ≤ 21): el régimen "normal-tenso". Hay movimiento real sin pánico:
    es donde una estrategia de reversión tiene, en teoría, sus mejores condiciones —
    suficiente dispersión para que el resorte se estire, sin los saltos que lo rompen.
  · **Alto** (VIX > 21): estrés. Las correlaciones se van a 1, la reversión se convierte en
    "atrapar un cuchillo cayendo" y los costos de ejecución se disparan.

Las bandas son configurables; 17 y 21 son los cortes por defecto.

Nota metodológica: se condiciona por el VIX del cierre de t y se mide el retorno de
t → t+1. El VIX de t ya es información pública al cierre de t, así que no hay look-ahead.
Lo que SÍ hay es una advertencia estadística: partir la muestra en tres multiplica por
tres las hipótesis, y cada subconjunto tiene menos datos y por lo tanto más error estándar.
Un Sharpe alto en un régimen que ocupa el 20% del tiempo es un Sharpe medido sobre un
quinto de la muestra.
"""
from __future__ import annotations

import math

from quant.backtest import metrics
from quant.stats import mean, stdev

BAJO_DEFECTO = 17.0
ALTO_DEFECTO = 21.0
REGIMENES = ["bajo", "medio", "alto"]


def clasificar(vix: float, bajo: float = BAJO_DEFECTO, alto: float = ALTO_DEFECTO) -> str:
    """Nombre del régimen para un valor de VIX."""
    if vix < bajo:
        return "bajo"
    if vix <= alto:
        return "medio"
    return "alto"


def alinear(fechas: list[int], fechas_vix: list[int], vix: list[float]) -> list[float | None]:
    """Valor del VIX en cada fecha de la estrategia.

    Si una fecha no tiene VIX exacto (feriados que no coinciden), se usa el último valor
    disponible ANTERIOR — nunca uno posterior, que sería mirar el futuro.
    """
    mapa = dict(zip(fechas_vix, vix))
    ordenadas = sorted(mapa)
    out: list[float | None] = []
    j = 0
    ultimo: float | None = None
    for t in fechas:
        while j < len(ordenadas) and ordenadas[j] <= t:
            ultimo = mapa[ordenadas[j]]
            j += 1
        out.append(ultimo)
    return out


def por_regimen(rets: list[float], vix_en_fecha: list[float | None],
                bajo: float = BAJO_DEFECTO, alto: float = ALTO_DEFECTO,
                periodos_por_anio: int = 252) -> dict:
    """Métricas de la estrategia dentro de cada régimen de VIX.

    `rets[i]` es el retorno log ganado ENTRE la fecha i y la i+1, y `vix_en_fecha[i]` el
    VIX al cierre de la fecha i: el régimen se conoce antes de ganar el retorno.
    """
    if len(rets) != len(vix_en_fecha):
        raise ValueError("rets y vix_en_fecha deben tener el mismo largo")

    grupos: dict[str, list[float]] = {r: [] for r in REGIMENES}
    sin_dato = 0
    for r, v in zip(rets, vix_en_fecha):
        if v is None:
            sin_dato += 1
            continue
        grupos[clasificar(v, bajo, alto)].append(r)

    total = sum(len(g) for g in grupos.values())
    salida = {}
    for nombre, serie in grupos.items():
        if len(serie) < 20:
            salida[nombre] = {"n": len(serie), "suficiente": False,
                              "pct_del_tiempo": round(100.0 * len(serie) / total, 1)
                              if total else 0.0}
            continue
        m = metrics(serie, None, 0, periodos_por_anio)
        m.pop("curva", None)
        salida[nombre] = {
            "n": len(serie),
            "suficiente": True,
            "pct_del_tiempo": round(100.0 * len(serie) / total, 1),
            "anios": round(len(serie) / periodos_por_anio, 2),
            "sharpe": m["sharpe"],
            "retorno_total_pct": m["retorno_total_pct"],
            "vol_anual_pct": m["vol_anual_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "media_diaria_bps": round(mean(serie) * 10_000, 2),
        }
    salida["_sin_vix"] = sin_dato
    salida["_bandas"] = {"bajo": f"VIX < {bajo}", "medio": f"{bajo} ≤ VIX ≤ {alto}",
                         "alto": f"VIX > {alto}"}
    return salida


def diferencia_de_medias(rets: list[float], vix_en_fecha: list[float | None],
                         regimen: str = "medio", bajo: float = BAJO_DEFECTO,
                         alto: float = ALTO_DEFECTO) -> dict:
    """¿El retorno medio DENTRO de un régimen difiere del de afuera? (t de Welch)

    Es la pregunta que importa cuando alguien dice "esto anda bien cuando el VIX está
    entre 17 y 21": no alcanza con que el Sharpe de adentro sea mayor, hay que ver si la
    diferencia sobrevive al ruido de partir la muestra.
    """
    dentro, fuera = [], []
    for r, v in zip(rets, vix_en_fecha):
        if v is None:
            continue
        (dentro if clasificar(v, bajo, alto) == regimen else fuera).append(r)

    if len(dentro) < 20 or len(fuera) < 20:
        return {"ok": False, "motivo": "Muy pocos datos en alguno de los dos lados.",
                "n_dentro": len(dentro), "n_fuera": len(fuera)}

    m1, m2 = mean(dentro), mean(fuera)
    s1, s2 = stdev(dentro), stdev(fuera)
    n1, n2 = len(dentro), len(fuera)
    se = math.sqrt(s1 * s1 / n1 + s2 * s2 / n2)
    if se <= 0:
        return {"ok": False, "motivo": "Varianza nula."}
    t = (m1 - m2) / se
    # Welch-Satterthwaite; con n grande la t es prácticamente una normal.
    from quant.stats import normal_cdf
    p = 2.0 * (1.0 - normal_cdf(abs(t)))
    return {"ok": True, "regimen": regimen, "n_dentro": n1, "n_fuera": n2,
            "media_dentro_bps": round(m1 * 10_000, 3),
            "media_fuera_bps": round(m2 * 10_000, 3),
            "diferencia_bps": round((m1 - m2) * 10_000, 3),
            "t": round(t, 2), "p_valor": p, "significativa_5pct": p < 0.05}
