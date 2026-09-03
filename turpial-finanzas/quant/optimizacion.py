"""Optimización que no se miente: walk-forward y Sharpe desinflado.

Optimizar sobre toda la muestra y quedarse con el mejor resultado es la forma más
confiable de fabricar una estrategia que no existe. Con 750 combinaciones sobre una serie
de puro ruido, la mejor va a tener un Sharpe respetable **por construcción**. Este módulo
implementa las dos defensas estándar:

**1. Walk-forward.** Se optimiza en una ventana y se mide en la SIGUIENTE, que el
optimizador nunca vio. Se avanza y se repite. El resultado honesto es la concatenación de
los tramos fuera de muestra: es lo que habría pasado operando de verdad, reoptimizando
cada tanto.

**2. Sharpe desinflado** (Bailey y López de Prado, 2014). Corrige el Sharpe por la
cantidad de combinaciones probadas. La idea: si se prueban N estrategias con Sharpe
verdadero cero, el máximo esperado no es cero sino

    SR₀ = sqrt(V)·[(1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e))]

con V la varianza de los Sharpe probados y γ la constante de Euler-Mascheroni. El DSR es
la probabilidad de que el Sharpe observado supere a ese máximo por azar, ajustando además
por asimetría y curtosis de los retornos — que en trading nunca son normales.

Un Sharpe de 1.2 elegido entre 500 pruebas puede tener un DSR de 0.3: significa que hay
un 70% de probabilidad de que sea suerte.
"""
from __future__ import annotations

import itertools
import math

from quant.stats import kurtosis, mean, normal_cdf, normal_ppf, skew, stdev

GAMMA = 0.5772156649015329   # Euler-Mascheroni


def grilla(espacio: dict[str, list]) -> list[dict]:
    """Producto cartesiano de un espacio de parámetros -> lista de combinaciones."""
    claves = list(espacio)
    return [dict(zip(claves, valores))
            for valores in itertools.product(*(espacio[k] for k in claves))]


def ventanas_walk_forward(n: int, train: int, test: int, paso: int | None = None
                          ) -> list[tuple[range, range]]:
    """Tramos (entrenamiento, prueba) deslizantes. El de prueba nunca se usa para elegir."""
    paso = paso or test
    out = []
    ini = 0
    while ini + train + test <= n:
        out.append((range(ini, ini + train), range(ini + train, ini + train + test)))
        ini += paso
    return out


def sharpe_por_periodo(rets: list[float]) -> float:
    """Sharpe SIN anualizar: es el que piden las fórmulas del Sharpe desinflado."""
    if len(rets) < 2:
        return 0.0
    sd = stdev(rets)
    return mean(rets) / sd if sd > 0 else 0.0


def sharpe_maximo_esperado(sharpes: list[float]) -> float:
    """SR₀: el mejor Sharpe que aparece por puro azar al probar N combinaciones.

    `sharpes` son los Sharpe (por período) de TODAS las combinaciones probadas.
    """
    n = len(sharpes)
    if n < 2:
        return 0.0
    v = stdev(sharpes)
    if v <= 0:
        return 0.0
    return v * ((1 - GAMMA) * normal_ppf(1 - 1.0 / n)
                + GAMMA * normal_ppf(1 - 1.0 / (n * math.e)))


def sharpe_desinflado(rets: list[float], sharpes_probados: list[float]) -> dict:
    """Probabilidad de que el Sharpe observado no sea producto de haber probado mucho.

    Devuelve el DSR en [0,1]: por encima de 0.95 el resultado sobrevive al descuento por
    multiplicidad; por debajo de 0.5 es más probable que sea suerte que no.
    """
    t = len(rets)
    if t < 30:
        return {"ok": False, "motivo": "Muy pocas observaciones para el Sharpe desinflado."}
    sr = sharpe_por_periodo(rets)
    sr0 = sharpe_maximo_esperado(sharpes_probados)
    g3, g4 = skew(rets), kurtosis(rets)
    den = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr
    if den <= 0:
        return {"ok": False, "motivo": "Denominador no positivo (momentos extremos)."}
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(den)
    return {"ok": True, "dsr": round(normal_cdf(z), 4),
            "sharpe_periodo": round(sr, 5), "sharpe_max_azar": round(sr0, 5),
            "n_probadas": len(sharpes_probados), "skew": round(g3, 3),
            "kurtosis": round(g4, 3), "z": round(z, 3), "n_obs": t}


def optimizar_walk_forward(n: int, combos: list[dict], correr, train: int, test: int,
                           paso: int | None = None, criterio=None) -> dict:
    """Optimiza en cada tramo de entrenamiento y mide en el siguiente, que no vio.

    `correr(combo, indices)` devuelve la lista de retornos de esa combinación en esos
    índices. `criterio(rets)` puntúa un tramo de entrenamiento (por defecto, el Sharpe).
    """
    criterio = criterio or sharpe_por_periodo
    ventanas = ventanas_walk_forward(n, train, test, paso)
    if not ventanas:
        return {"ok": False, "motivo": f"No entran ventanas de {train}+{test} en {n} barras."}

    oos: list[float] = []
    elegidos: list[dict] = []
    for tr, te in ventanas:
        mejor, mejor_score = None, float("-inf")
        for combo in combos:
            score = criterio(correr(combo, tr))
            if score > mejor_score:
                mejor, mejor_score = combo, score
        oos.extend(correr(mejor, te))
        elegidos.append({"desde": te.start, "hasta": te.stop, "params": mejor,
                         "score_entrenamiento": round(mejor_score, 5)})
    return {"ok": True, "retornos_oos": oos, "elegidos": elegidos,
            "n_ventanas": len(ventanas), "n_combos": len(combos)}


def estabilidad(elegidos: list[dict]) -> dict:
    """¿El optimizador elige siempre lo mismo, o salta de parámetros en cada tramo?

    Si en cada ventana gana una combinación distinta, no está encontrando una regularidad:
    está persiguiendo ruido, y lo que elija para el futuro es una tirada de dados.
    """
    if not elegidos:
        return {}
    claves = list(elegidos[0]["params"])
    out = {}
    for k in claves:
        vals = [e["params"][k] for e in elegidos]
        # Desempate determinista: a igual frecuencia gana el que apareció primero. Con
        # max(set(...)) el orden del set variaba entre corridas y la "moda" cambiaba.
        orden = []
        for v in map(str, vals):
            if v not in orden:
                orden.append(v)
        modo = max(orden, key=lambda v: (sum(1 for x in vals if str(x) == v), -orden.index(v)))
        out[k] = {"valores": vals, "moda": modo,
                  "estabilidad_pct": round(100.0 * sum(1 for x in vals if str(x) == modo)
                                           / len(vals), 1)}
    return out
