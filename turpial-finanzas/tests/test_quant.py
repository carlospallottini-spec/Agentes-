"""Tests del motor cuantitativo — deterministas y sin red.

Todo se valida contra procesos simulados con parámetros CONOCIDOS: si el calibrador no
recupera el θ, el μ y el σ con los que se generó la serie, no sirve para datos reales.

Se corre con pytest o directo:  python tests/test_quant.py
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import backtest, markov, ou, pairs  # noqa: E402
from quant.stats import chi2_sf, normal_cdf, ols, quantile  # noqa: E402
from quant.strategies import FLAT, LONG, SHORT, ou_position, regime_allows  # noqa: E402


# ------------------------------------------------------------------ estadística
def test_ols_recupera_recta():
    x = list(range(50))
    y = [3.0 + 2.5 * xi for xi in x]
    fit = ols(x, y)
    assert abs(fit["slope"] - 2.5) < 1e-9
    assert abs(fit["intercept"] - 3.0) < 1e-9
    assert fit["r2"] > 0.999999


def test_chi2_y_normal_contra_tabla():
    assert abs(chi2_sf(3.841, 1) - 0.05) < 1e-3     # crítico al 5% con 1 gl
    assert abs(chi2_sf(11.070, 5) - 0.05) < 1e-3    # crítico al 5% con 5 gl
    assert abs(normal_cdf(1.959964) - 0.975) < 1e-6
    assert abs(quantile([1, 2, 3, 4], 0.5) - 2.5) < 1e-12


# ---------------------------------------------------- Ornstein-Uhlenbeck: núcleo
def test_ou_recupera_parametros_conocidos():
    theta, mu, sigma = 0.05, 4.0, 0.2
    serie = ou.simulate(theta, mu, sigma, x0=4.6, n=40000, seed=11)
    p = ou.calibrate(serie)
    assert p["ok"]
    assert abs(p["theta"] - theta) / theta < 0.10
    assert abs(p["mu"] - mu) < 0.10
    assert abs(p["sigma"] - sigma) / sigma < 0.05
    # half-life teórico = ln(2)/θ
    assert abs(p["half_life"] - math.log(2) / theta) / (math.log(2) / theta) < 0.10
    # σ_eq teórico = σ/sqrt(2θ)
    assert abs(p["sigma_eq"] - sigma / math.sqrt(2 * theta)) < 0.02
    assert p["estacionaria_5pct"] is True


def test_ou_rechaza_random_walk():
    """Un paseo aleatorio no tiene fuerza restauradora: no debe declararse estacionario."""
    rng = random.Random(4)
    serie, x = [0.0], 0.0
    for _ in range(2000):
        x += rng.gauss(0, 0.01)
        serie.append(x)
    p = ou.calibrate(serie)
    # O la pendiente sale ≥1 (calibración inválida) o el test de DF no rechaza.
    assert (not p["ok"]) or (not p["estacionaria_5pct"])


def test_ou_serie_corta_falla_con_motivo():
    p = ou.calibrate([1.0, 2.0, 3.0])
    assert p["ok"] is False and "corta" in p["motivo"].lower()


def test_curva_decaimiento_es_exponencial():
    """En cada half-life la desviación restante se parte al medio: 50% → 25% → 12.5%."""
    p = ou.calibrate(ou.simulate(0.05, 4.0, 0.2, 4.6, 20000, seed=3))
    curva = ou.expected_path(p, x0=5.0)
    hitos = curva["hitos"]
    assert [h["desvio_restante_pct"] for h in hitos] == [50.0, 25.0, 12.5]
    # el t de cada hito es múltiplo exacto del half-life
    for k, h in zip((1, 2, 3), hitos):
        assert abs(h["t"] - k * p["half_life"]) < 1e-2
    # la curva converge a μ y arranca en x0
    assert abs(curva["puntos"][0]["esperado"] - 5.0) < 1e-9
    assert abs(curva["puntos"][-1]["esperado"] - p["mu"]) < abs(5.0 - p["mu"]) * 0.15
    # las bandas se abren con el tiempo (varianza condicional creciente)
    ancho = [pt["banda_sup"] - pt["banda_inf"] for pt in curva["puntos"]]
    assert ancho[0] < ancho[len(ancho) // 2] < ancho[-1]


def test_prob_reversion_en_rango():
    p = ou.calibrate(ou.simulate(0.05, 4.0, 0.2, 4.6, 5000, seed=8))
    r = ou.prob_reversion(p)
    assert 0.0 <= r["prob_cruce_en_h"] <= 1.0


# ----------------------------------------------------------------------- Markov
def _cadena(P, n, seed=3):
    rng = random.Random(seed)
    s = [0]
    for _ in range(n):
        u, acc = rng.random(), 0.0
        for j, prob in enumerate(P[s[-1]]):
            acc += prob
            if u < acc:
                s.append(j)
                break
    return s


def test_markov_recupera_matriz():
    P = [[0.85, 0.10, 0.05], [0.10, 0.80, 0.10], [0.05, 0.10, 0.85]]
    s = _cadena(P, 30000)
    est = markov.transition_matrix(s)["P"]
    for i in range(3):
        for j in range(3):
            assert abs(est[i][j] - P[i][j]) < 0.02
    pi = markov.stationary(est)
    assert abs(sum(pi) - 1.0) < 1e-9
    # duración media de la racha = 1/(1−P_ii)
    dur = markov.expected_duration(est)
    assert abs(dur[0] - 1 / (1 - P[0][0])) < 0.5


def test_markov_detecta_memoria_y_su_ausencia():
    P = [[0.85, 0.10, 0.05], [0.10, 0.80, 0.10], [0.05, 0.10, 0.85]]
    con = markov.independence_test(markov.transition_matrix(_cadena(P, 20000))["counts"])
    assert con["hay_memoria_5pct"] is True
    rng = random.Random(17)
    iid = [rng.choice([0, 1, 2]) for _ in range(5000)]
    sin = markov.independence_test(markov.transition_matrix(iid)["counts"])
    assert sin["hay_memoria_5pct"] is False


def test_markov_chapman_kolmogorov():
    """P^n debe tener filas que suman 1 y converger a la estacionaria."""
    P = [[0.85, 0.10, 0.05], [0.10, 0.80, 0.10], [0.05, 0.10, 0.85]]
    P50 = markov.n_step(P, 50)
    pi = markov.stationary(P)
    for fila in P50:
        assert abs(sum(fila) - 1.0) < 1e-9
        for j in range(3):
            assert abs(fila[j] - pi[j]) < 1e-3


def test_markov_analyze_sobre_retornos():
    rng = random.Random(5)
    rets = [rng.gauss(0, 0.01) for _ in range(1000)]
    r = markov.analyze(rets)
    assert r["ok"] and r["regimen_actual"] in markov.ESTADOS
    assert abs(sum(r["estacionaria"].values()) - 1.0) < 1e-6
    for fila in r["matriz"]:
        assert abs(sum(fila) - 1.0) < 1e-3


# -------------------------------------------------------------------- señales
def test_reglas_de_posicion():
    assert ou_position(-2.0, FLAT, 0, 10)[0] == LONG
    assert ou_position(2.0, FLAT, 0, 10)[0] == SHORT
    assert ou_position(-1.0, FLAT, 0, 10)[0] == FLAT
    assert ou_position(-0.2, LONG, 5, 10)[0] == FLAT      # objetivo alcanzado
    assert ou_position(-3.5, LONG, 5, 10)[0] == FLAT      # stop
    assert ou_position(-2.0, LONG, 5, 10)[0] == LONG      # sigue estirado: mantener
    # límite temporal: 3 half-lives de 10 barras = 30 barras
    assert ou_position(-2.0, LONG, 31, 10)[0] == FLAT
    assert "half-life" in ou_position(-2.0, LONG, 31, 10)[1]


def test_filtro_de_regimen():
    bajista = {"ok": True, "regimen_actual": "bajista", "persistencia_actual": 0.8,
               "test_memoria": {"hay_memoria_5pct": True}}
    assert regime_allows(LONG, bajista) is False     # no comprar la caída en tendencia
    assert regime_allows(SHORT, bajista) is True
    sin_memoria = dict(bajista, test_memoria={"hay_memoria_5pct": False})
    assert regime_allows(LONG, sin_memoria) is True  # sin evidencia, no se filtra
    assert regime_allows(LONG, None) is True


# ------------------------------------------------------------------- backtest
def _precios_ou(seed=5, n=1500):
    logp = ou.simulate(0.04, math.log(100), 0.02, math.log(100), n, seed=seed)
    return [math.exp(v) for v in logp]


def test_backtest_gana_en_serie_reversiva():
    r = backtest.walk_forward(_precios_ou(), ventana=250)
    assert r["ok"]
    m = r["metricas"]
    assert m["sharpe"] > 0.8            # el modelo es el proceso: debería funcionar
    assert m["trades"] > 5
    assert 0 < m["exposicion_pct"] < 100
    assert m["max_drawdown_pct"] > 0


def test_backtest_no_inventa_alfa_en_random_walk():
    rng = random.Random(21)
    px, x = [100.0], math.log(100.0)
    for _ in range(1499):
        x += rng.gauss(0, 0.012)
        px.append(math.exp(x))
    r = backtest.walk_forward(px, ventana=250)
    assert r["ok"]
    # Sin fuerza restauradora real no puede salir un Sharpe de estrategia ganadora.
    assert (r["metricas"]["sharpe"] or 0) < 1.0


def test_backtest_sin_look_ahead():
    """Truncar el futuro no puede cambiar el pasado.

    Si el backtest usara información posterior a t, los retornos de las primeras barras
    cambiarían al agregar datos al final. Se corre sobre una serie corta y sobre la misma
    serie extendida, y se exige que el tramo común sea idéntico bit a bit.
    """
    px = _precios_ou(seed=6, n=1200)
    corto = backtest.walk_forward(px[:900], ventana=250, usar_regimen=True)
    largo = backtest.walk_forward(px, ventana=250, usar_regimen=True)
    a = corto["metricas"]["curva"]
    b = largo["metricas"]["curva"]
    assert len(a) < len(b)
    for i in range(len(a)):
        assert a[i] == b[i], f"divergencia en la barra {i}: {a[i]} vs {b[i]}"


def test_backtest_costos_reducen_retorno():
    sin = backtest.walk_forward(_precios_ou(), ventana=250, cost_bps=0.0)
    con = backtest.walk_forward(_precios_ou(), ventana=250, cost_bps=50.0)
    assert con["metricas"]["retorno_total_pct"] < sin["metricas"]["retorno_total_pct"]


def test_backtest_serie_corta_falla_con_motivo():
    r = backtest.walk_forward([100.0] * 50, ventana=250)
    assert r["ok"] is False and "Se necesitan" in r["motivo"]


def test_backtest_serie_constante_no_opera():
    """Sin dispersión no hay regresión posible: el motor se abstiene, no explota."""
    r = backtest.walk_forward([100.0] * 400, ventana=250)
    assert r["ok"] is True
    assert r["metricas"]["trades"] == 0


def test_metricas_drawdown_conocido():
    """Serie que sube 10% y baja 20%: el drawdown máximo debe ser ~20%."""
    rets = [math.log(1.10), math.log(0.80)]
    m = backtest.metrics(rets)
    assert abs(m["max_drawdown_pct"] - 20.0) < 1e-6
    assert abs(m["retorno_total_pct"] - (1.10 * 0.80 - 1) * 100) < 1e-6


# ---------------------------------------------------------------------- pares
def test_pares_recupera_cointegracion():
    rng = random.Random(9)
    lb = [math.log(50)]
    for _ in range(1499):
        lb.append(lb[-1] + rng.gauss(0, 0.012))
    sp = ou.simulate(0.06, 0.0, 0.02, 0.0, 1500, seed=21)
    la = [0.5 + 1.2 * b + s for b, s in zip(lb, sp)]
    A = [math.exp(v) for v in la]
    B = [math.exp(v) for v in lb]

    r = pairs.analyze(A, B, "A", "B")
    assert r["ok"]
    assert r["engle_granger"]["cointegrado_5pct"] is True
    assert 0.8 < r["hedge_ratio_beta"] < 1.6           # β verdadero = 1.2 (sesgo conocido)
    assert 5 < r["ou"]["half_life_dias"] < 25          # teórico ln2/0.06 ≈ 11.6
    bt = pairs.walk_forward(A, B, ventana=250)
    assert bt["ok"] and bt["metricas"]["sharpe"] > 0.5


def test_pares_rechaza_series_independientes():
    """Dos random walks sin relación no están cointegrados."""
    rng = random.Random(31)
    A, B, xa, xb = [100.0], [100.0], math.log(100), math.log(100)
    for _ in range(999):
        xa += rng.gauss(0, 0.012)
        xb += rng.gauss(0, 0.012)
        A.append(math.exp(xa))
        B.append(math.exp(xb))
    r = pairs.analyze(A, B, "A", "B")
    assert r["ok"]
    assert r["engle_granger"]["cointegrado_5pct"] is False
    assert "NO pasa el test" in r["veredicto"]


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    fallos = 0
    for nombre, fn in tests:
        try:
            fn()
            print(f"  ok   {nombre}")
        except AssertionError as e:
            fallos += 1
            print(f"  FALLA {nombre}: {e}")
        except Exception as e:  # noqa: BLE001
            fallos += 1
            print(f"  ERROR {nombre}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - fallos}/{len(tests)} tests pasaron")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
