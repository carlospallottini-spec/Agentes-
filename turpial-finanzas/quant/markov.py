"""Cadenas de Markov de regímenes de mercado.

Un proceso de Markov de primer orden asume que el futuro depende del presente y no de
todo el pasado:

    P(S_(t+1) = j | S_t = i, S_(t−1), …) = P(S_(t+1) = j | S_t = i) = P_ij

Discretizamos los retornos diarios en **regímenes** (bajista / lateral / alcista) usando
umbrales de ±k·σ, estimamos la matriz de transición P por conteo de frecuencias y de ahí
salen tres cosas que sirven para operar:

  1. **Persistencia**: P_ii alto ⇒ el régimen tiende a continuar. La duración media de
     una racha en el estado i es 1/(1 − P_ii) (esperanza de una geométrica).
  2. **Distribución estacionaria** π: el vector que cumple π·P = π, o sea la fracción de
     tiempo de largo plazo en cada régimen. Se obtiene por iteración de potencias.
  3. **Test de memoria** (χ²): compara los conteos de transición observados contra los
     esperados si los estados fueran independientes (iid). Si el p-valor es alto, NO hay
     evidencia de memoria y cualquier estrategia basada en el régimen es ruido.

El estimador usa suavizado de Laplace (α) para que un par (i,j) nunca visto no fabrique
una probabilidad exactamente 0 con muestras cortas.
"""
from __future__ import annotations

from quant.stats import chi2_sf, stdev

ESTADOS = ["bajista", "lateral", "alcista"]


def label_states(returns: list[float], k: float = 0.5) -> dict:
    """Discretiza retornos en 3 regímenes con umbrales ±k·σ.

    Devuelve los estados (0=bajista, 1=lateral, 2=alcista) y los umbrales usados.
    """
    if len(returns) < 10:
        return {"ok": False, "motivo": "Muy pocos retornos para etiquetar regímenes."}
    s = stdev(returns)
    if s <= 0:
        return {"ok": False, "motivo": "Retornos sin dispersión: no hay regímenes."}
    lo, hi = -k * s, k * s
    states = [0 if r < lo else (2 if r > hi else 1) for r in returns]
    return {"ok": True, "states": states, "umbral_bajo": lo, "umbral_alto": hi, "sigma": s}


def transition_matrix(states: list[int], n_states: int = 3, alpha: float = 1.0) -> dict:
    """Estima P por máxima verosimilitud con suavizado de Laplace α.

    P_ij = (conteo_ij + α) / (Σ_j conteo_ij + α·n_states)
    """
    if len(states) < 2:
        return {"ok": False, "motivo": "Se necesitan al menos 2 estados consecutivos."}
    counts = [[0 for _ in range(n_states)] for _ in range(n_states)]
    for i, j in zip(states[:-1], states[1:]):
        counts[i][j] += 1
    P = []
    for row in counts:
        tot = sum(row) + alpha * n_states
        P.append([(c + alpha) / tot for c in row])
    return {"ok": True, "P": P, "counts": counts, "n_transiciones": len(states) - 1}


def stationary(P: list[list[float]], iters: int = 2000, tol: float = 1e-12) -> list[float]:
    """Distribución estacionaria π (π·P = π) por iteración de potencias."""
    n = len(P)
    pi = [1.0 / n] * n
    for _ in range(iters):
        nxt = [sum(pi[i] * P[i][j] for i in range(n)) for j in range(n)]
        total = sum(nxt) or 1.0
        nxt = [v / total for v in nxt]
        if max(abs(a - b) for a, b in zip(pi, nxt)) < tol:
            return nxt
        pi = nxt
    return pi


def n_step(P: list[list[float]], n: int) -> list[list[float]]:
    """P^n — probabilidades de transición a n pasos (ecuación de Chapman-Kolmogorov)."""
    size = len(P)
    result = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for _ in range(n):
        result = [[sum(result[i][k] * P[k][j] for k in range(size)) for j in range(size)]
                  for i in range(size)]
    return result


def expected_duration(P: list[list[float]]) -> list[float]:
    """Duración media de una racha en cada estado: 1/(1 − P_ii)."""
    out = []
    for i, row in enumerate(P):
        p = min(row[i], 1.0 - 1e-12)
        out.append(1.0 / (1.0 - p))
    return out


def independence_test(counts: list[list[int]]) -> dict:
    """χ² de independencia sobre la tabla de contingencia de transiciones.

    H0: el próximo estado es independiente del actual (no hay memoria markoviana).
    Rechazar H0 (p < 0.05) es la evidencia mínima para usar el régimen como filtro.
    """
    n = len(counts)
    total = sum(sum(r) for r in counts)
    if total == 0:
        return {"ok": False, "motivo": "Sin transiciones observadas."}
    rows = [sum(r) for r in counts]
    cols = [sum(counts[i][j] for i in range(n)) for j in range(n)]
    stat, df_penal = 0.0, 0
    for i in range(n):
        for j in range(n):
            e = rows[i] * cols[j] / total
            if e <= 0:
                df_penal += 1
                continue
            stat += (counts[i][j] - e) ** 2 / e
    df = max((n - 1) ** 2 - df_penal, 1)
    p = chi2_sf(stat, df)
    return {"ok": True, "chi2": stat, "df": df, "p_valor": p,
            "hay_memoria_5pct": p < 0.05}


def analyze(returns: list[float], k: float = 0.5, alpha: float = 1.0) -> dict:
    """Reporte completo de régimen: matriz, π, persistencia, memoria y próximo paso."""
    lab = label_states(returns, k)
    if not lab.get("ok"):
        return {"ok": False, "motivo": lab["motivo"]}
    states = lab["states"]
    tm = transition_matrix(states, len(ESTADOS), alpha)
    if not tm.get("ok"):
        return {"ok": False, "motivo": tm["motivo"]}

    P = tm["P"]
    pi = stationary(P)
    dur = expected_duration(P)
    test = independence_test(tm["counts"])
    actual = states[-1]

    return {
        "ok": True,
        "estados": ESTADOS,
        "matriz": [[round(v, 4) for v in row] for row in P],
        "conteos": tm["counts"],
        "n_transiciones": tm["n_transiciones"],
        "estacionaria": {ESTADOS[i]: round(v, 4) for i, v in enumerate(pi)},
        "duracion_media": {ESTADOS[i]: round(v, 2) for i, v in enumerate(dur)},
        "umbrales": {"bajo_pct": round(lab["umbral_bajo"] * 100, 3),
                     "alto_pct": round(lab["umbral_alto"] * 100, 3)},
        "regimen_actual": ESTADOS[actual],
        "prob_siguiente": {ESTADOS[j]: round(P[actual][j], 4) for j in range(len(ESTADOS))},
        "prob_5_pasos": {ESTADOS[j]: round(n_step(P, 5)[actual][j], 4)
                         for j in range(len(ESTADOS))},
        "persistencia_actual": round(P[actual][actual], 4),
        "test_memoria": test,
        "series_estados": states,
    }
