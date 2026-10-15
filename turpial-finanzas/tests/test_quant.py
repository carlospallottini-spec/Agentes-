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

from quant import (backtest, intradia, markov, momentum, niveles, opciones,  # noqa: E402
                   optimizacion, ou, pairs, regimen_vol, scan, snapshots, toques)
from quant.stats import chi2_sf, normal_cdf, ols, quantile  # noqa: E402
from quant.stats import wilson as stats_wilson  # noqa: E402
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


def test_gate_de_estacionariedad_reduce_la_operativa():
    """Con el gate activo se opera sólo donde Dickey-Fuller rechaza: menos exposición."""
    rng = random.Random(77)
    px, x = [100.0], math.log(100.0)
    for _ in range(1499):
        x += rng.gauss(0, 0.012)
        px.append(math.exp(x))
    sin = backtest.walk_forward(px, ventana=250, exigir_estacionaria=False)
    con = backtest.walk_forward(px, ventana=250, exigir_estacionaria=True)
    assert sin["ok"] and con["ok"]
    # Sobre un random walk el gate casi nunca habilita: debe operar mucho menos.
    assert con["metricas"]["exposicion_pct"] < sin["metricas"]["exposicion_pct"]
    assert con["metricas"]["trades"] <= sin["metricas"]["trades"]
    assert "gate Dickey-Fuller" in con["estrategia"]
    assert con["parametros"]["gate_estacionariedad"] is True


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


# ------------------------------------------------- estadística del escaneo
def test_sharpe_se_formula_de_lo():
    """SE(S) = sqrt((1 + S²/2)/T). Con 4 años y S=0.5 da 0.53."""
    assert abs(scan.sharpe_se(0.5, 4, 1.0) - math.sqrt((1 + 0.125) / 4)) < 1e-12
    # Más años => más precisión.
    assert scan.sharpe_se(1.0, 10, 1.0) < scan.sharpe_se(1.0, 2, 1.0)
    # Un Sharpe alto medido sobre 2 meses no puede ser significativo.
    t, p = scan.sharpe_pvalue(2.0, 1, 6.25)
    assert abs(t) < 1.0 and p > 0.5
    # El mismo Sharpe sobre 20 años sí lo es.
    t2, p2 = scan.sharpe_pvalue(2.0, 20, 1.0)
    assert t2 > 5 and p2 < 1e-6


def test_bonferroni_y_benjamini_hochberg():
    ps = [0.001, 0.008, 0.02, 0.04, 0.2, 0.5, 0.7, 0.9, 0.95, 0.99]
    b = scan.bonferroni(ps, 0.05)
    assert abs(b["umbral"] - 0.005) < 1e-12
    assert b["sobreviven"] == [True] + [False] * 9      # sólo p=0.001 < 0.005

    bh = scan.benjamini_hochberg(ps, 0.05)
    # p_(1)=0.001<=0.005 ok; p_(2)=0.008<=0.010 ok; p_(3)=0.02>0.015 no.
    assert bh["k"] == 2
    assert bh["sobreviven"][:2] == [True, True]
    assert not any(bh["sobreviven"][2:])
    # BH nunca es más estricto que Bonferroni.
    assert sum(bh["sobreviven"]) >= sum(b["sobreviven"])


def test_correcciones_sobre_ruido_puro():
    """Con 100 p-valores uniformes (todo ruido), no debería sobrevivir casi nada."""
    rng = random.Random(99)
    ps = [rng.random() for _ in range(100)]
    assert sum(scan.bonferroni(ps)["sobreviven"]) <= 1
    assert sum(scan.benjamini_hochberg(ps)["sobreviven"]) <= 2


def test_periodos_por_anio_desde_timestamps():
    """Se mide de los datos, no se asume 252: equivocarse acá rompe el Sharpe."""
    diario = [i * 86400 for i in range(400)]
    assert abs(scan.periodos_por_anio(diario) - 365.25) < 1.0
    cinco_min = [i * 300 for i in range(5000)]
    assert abs(scan.periodos_por_anio(cinco_min) - 365.25 * 288) < 100


def test_diagnostico_gaps_detecta_fines_de_semana():
    ts = []
    t = 0
    for semana in range(4):
        for i in range(120):        # 120 barras horarias de "semana"
            ts.append(t)
            t += 3600
        t += 48 * 3600              # hueco de fin de semana
    g = scan.diagnostico_gaps(ts)
    assert g["mediana_seg"] == 3600
    assert g["huecos_grandes"] == 3   # 3 huecos entre 4 semanas


def test_resumir_marca_lo_que_sobrevive():
    filas = [{"p_valor": 0.0001, "sharpe": 2.0}, {"p_valor": 0.5, "sharpe": 0.1},
             {"p_valor": 0.8, "sharpe": -0.3}, {"p_valor": 0.9, "sharpe": -0.5}]
    r = scan.resumir(filas)
    assert r["n"] == 4 and r["positivos"] == 2
    assert r["sobreviven_bonferroni"] == 1
    assert filas[0]["sobrevive_bonferroni"] is True
    assert filas[1]["sobrevive_bonferroni"] is False
    assert abs(r["esperados_por_azar"] - 0.2) < 1e-9


# --------------------------------------------- meta-control: ¿el motor VE un efecto?
def test_momentum_detecta_efecto_inyectado():
    """Sobre un universo donde el momentum existe por construcción, hay que detectarlo.

    Es el test que le da valor a todos los resultados negativos del repo: si el motor
    no encontrara un efecto puesto a mano, sus "no encontré nada" no probarían nada.
    """
    f, p = momentum.simular_universo(n_activos=20, persistencia=2000, semilla=5)
    xs = momentum.cross_sectional(f, p, cost_bps=0.0)
    ts = momentum.time_series(f, p, cost_bps=0.0)
    assert xs["ok"] and ts["ok"]
    assert xs["metricas"]["sharpe"] > 1.5
    assert ts["metricas"]["sharpe"] > 1.5

    nulo = momentum.nulo_por_permutacion(momentum.cross_sectional, f, p,
                                         repeticiones=60, cost_bps=0.0)
    assert nulo["ok"]
    assert momentum.p_empirico(xs["metricas"]["sharpe"], nulo) < 0.05


def test_momentum_no_inventa_efecto_en_random_walks():
    """Sobre random walks puros, el momentum no puede separarse del nulo barajado."""
    rng = random.Random(11)
    fechas = [i * 86400 for i in range(3000)]
    precios = {}
    for a in range(12):
        px = [100.0]
        for _ in range(2999):
            px.append(px[-1] * math.exp(rng.gauss(0, 0.01)))
        precios[f"RW{a}"] = px
    xs = momentum.cross_sectional(fechas, precios, cost_bps=0.0)
    nulo = momentum.nulo_por_permutacion(momentum.cross_sectional, fechas, precios,
                                         repeticiones=60, cost_bps=0.0)
    assert momentum.p_empirico(xs["metricas"]["sharpe"], nulo) > 0.05


def test_nulo_por_permutacion_esta_centrado_en_cero():
    """El nulo debe rodear al cero: si estuviera sesgado, los p-valores mentirían."""
    f, p = momentum.simular_universo(n_activos=15, n_dias=3000, semilla=8)
    nulo = momentum.nulo_por_permutacion(momentum.cross_sectional, f, p,
                                         repeticiones=100, cost_bps=0.0)
    assert abs(nulo["media"]) < 0.35
    assert nulo["p05"] < 0 < nulo["p95"]


def test_momentum_alinea_por_fecha():
    """Sin fechas comunes no hay cartera: la intersección tiene que ser exacta."""
    dia = 86400
    series = {"A": [{"t": dia, "c": 10.0}, {"t": 2 * dia, "c": 11.0}, {"t": 3 * dia, "c": 12.0}],
              "B": [{"t": 2 * dia, "c": 20.0}, {"t": 3 * dia, "c": 21.0}, {"t": 4 * dia, "c": 22.0}]}
    fechas, precios = momentum.alinear(series)
    assert len(fechas) == 2
    assert precios["A"] == [11.0, 12.0] and precios["B"] == [20.0, 21.0]


def test_alineacion_tolera_horas_de_cierre_distintas():
    """Un futuro cierra a las 21:00 UTC y un ETF a las 20:00: mismo día, distinto sello.

    Antes se intersectaba por timestamp exacto y comparar GC=F con GLD devolvía 20 fechas
    en común en vez de 2500. La alineación tiene que ser por fecha de calendario.
    """
    dia = 86400
    fut = [{"t": i * dia + 21 * 3600, "c": 100.0 + i} for i in range(1, 6)]
    etf = [{"t": i * dia + 20 * 3600, "c": 50.0 + i} for i in range(1, 6)]
    fechas, precios = momentum.alinear({"FUT": fut, "ETF": etf})
    assert len(fechas) == 5
    assert precios["FUT"] == [101.0, 102.0, 103.0, 104.0, 105.0]
    assert precios["ETF"] == [51.0, 52.0, 53.0, 54.0, 55.0]


def test_momentum_costos_reducen_retorno():
    f, p = momentum.simular_universo(n_activos=15, n_dias=3000, persistencia=2000, semilla=4)
    sin = momentum.cross_sectional(f, p, cost_bps=0.0)
    con = momentum.cross_sectional(f, p, cost_bps=50.0)
    assert con["metricas"]["retorno_total_pct"] < sin["metricas"]["retorno_total_pct"]


# ------------------------------------------------- régimen de volatilidad (VIX)
def test_regimen_vix_clasifica_en_las_bandas():
    assert regimen_vol.clasificar(12.0) == "bajo"
    assert regimen_vol.clasificar(17.0) == "medio"     # borde inferior incluido
    assert regimen_vol.clasificar(21.0) == "medio"     # borde superior incluido
    assert regimen_vol.clasificar(21.01) == "alto"
    assert regimen_vol.clasificar(16.99) == "bajo"


def test_regimen_vix_alinea_sin_mirar_el_futuro():
    """Para una fecha sin VIX exacto se usa el ÚLTIMO anterior, nunca uno posterior."""
    fechas = [100, 150, 200, 250]
    fvix = [90, 160, 240]
    vals = [15.0, 19.0, 25.0]
    out = regimen_vol.alinear(fechas, fvix, vals)
    assert out == [15.0, 15.0, 19.0, 25.0]
    # Antes del primer dato de VIX no se inventa nada.
    assert regimen_vol.alinear([50], fvix, vals) == [None]


def test_regimen_vix_separa_los_retornos():
    """Retornos buenos sólo en el régimen medio: tiene que verse en las métricas."""
    rng = random.Random(3)
    rets, vix = [], []
    for i in range(600):
        en_medio = (i % 3 == 0)
        vix.append(19.0 if en_medio else 12.0)
        rets.append(rng.gauss(0.002, 0.01) if en_medio else rng.gauss(-0.0005, 0.01))
    r = regimen_vol.por_regimen(rets, vix)
    assert r["medio"]["suficiente"] and r["bajo"]["suficiente"]
    assert r["medio"]["sharpe"] > r["bajo"]["sharpe"]
    assert abs(r["medio"]["pct_del_tiempo"] - 33.3) < 1.0
    d = regimen_vol.diferencia_de_medias(rets, vix, "medio")
    assert d["ok"] and d["significativa_5pct"] is True and d["diferencia_bps"] > 0


def test_regimen_vix_no_afirma_con_pocos_datos():
    r = regimen_vol.por_regimen([0.001] * 10, [19.0] * 10)
    assert r["medio"]["suficiente"] is False


# ------------------------------------------------ motores intradía de sesión
def _ohlc(n=400, seed=2):
    rng = random.Random(seed)
    px, out = 100.0, []
    for i in range(n):
        o = px
        h = o * (1 + abs(rng.gauss(0, 0.01)))
        l = o * (1 - abs(rng.gauss(0, 0.01)))
        c = rng.uniform(l, h)
        out.append({"t": i * 86400, "o": o, "h": h, "l": l, "c": c})
        px = c
    return out


def test_atr_de_sesion_usa_solo_el_pasado():
    o = _ohlc(60)
    atr = intradia.atr_sesion(o, 30, 14)
    assert atr is not None and atr > 0
    # Cambiar el futuro no puede cambiar el ATR de hoy.
    o2 = [dict(b) for b in o]
    for i in range(30, 60):
        o2[i]["h"] *= 5
    assert abs(intradia.atr_sesion(o2, 30, 14) - atr) < 1e-12
    assert intradia.atr_sesion(o, 5, 14) is None       # sin historia suficiente


def test_señal_session_markov_dispara_con_caida_fuerte():
    o = _ohlc(60)
    # Se fuerza a que la sesión previa cierre muy abajo de su apertura y del rango.
    o[40] = {"t": 40 * 86400, "o": 100.0, "h": 100.5, "l": 90.0, "c": 90.2}
    mask = intradia.señal_session_markov(o)
    assert mask[41] is True


def test_gap_fade_respeta_el_rango_de_hueco():
    o = _ohlc(300)
    for b in o:                                   # tendencia alcista clara
        pass
    cierres = [b["c"] for b in o]
    t = 250
    ayer = cierres[t - 1]
    o[t]["o"] = ayer * 0.99                       # hueco de -1%: dentro del rango
    mask = intradia.señal_gap_fade(o, sma=200)
    if cierres[t - 1] > sum(cierres[t - 200:t]) / 200:
        assert mask[t] is True
    o[t]["o"] = ayer * 0.95                       # -5%: fuera del rango
    assert intradia.señal_gap_fade(o, sma=200)[t] is False


def test_gap_fade_el_supuesto_ambiguo_cambia_el_signo():
    """En un día que toca stop y objetivo, el supuesto decide el resultado."""
    o = [{"t": 0, "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0},
         {"t": 86400, "o": 99.0, "h": 101.5, "l": 97.5, "c": 99.0}]
    mask = [False, True]
    cons = intradia.simular_gap_fade(o, mask, cost_bps=0.0, ambiguo="stop")
    opt = intradia.simular_gap_fade(o, mask, cost_bps=0.0, ambiguo="objetivo")
    assert cons["retornos"][1] < 0 < opt["retornos"][1]
    assert intradia.dias_ambiguos(o, mask)["ambiguos"] == 1


def test_stop_del_motor_s_corta_la_perdida():
    o = _ohlc(60)
    o[40] = {"t": 40 * 86400, "o": 100.0, "h": 100.5, "l": 90.0, "c": 90.2}
    o[41] = {"t": 41 * 86400, "o": 90.0, "h": 90.5, "l": 50.0, "c": 55.0}
    mask = intradia.señal_session_markov(o)
    r = intradia.simular_session_markov(o, mask, cost_bps=0.0)
    # Con stop a 2 ATR la pérdida no puede ser la del cierre (mucho peor).
    sin_stop = intradia.simular_session_markov(o, mask, cost_bps=0.0, stop_atr=0)
    assert r["retornos"][41] > sin_stop["retornos"][41]


def test_nulo_intradia_conserva_la_cantidad_de_trades():
    o = _ohlc(500)
    mask = intradia.señal_session_markov(o)
    n = sum(1 for x in mask if x)
    if n < 5:
        return
    nulo = intradia.nulo_por_permutacion(intradia.simular_session_markov, o, mask,
                                         repeticiones=20, cost_bps=0.0)
    assert nulo["ok"] and nulo["n"] == 20
    assert nulo["p05"] <= nulo["p50"] <= nulo["p95"]


# --------------------------------------------- optimización sin autoengaño
def test_grilla_y_ventanas():
    g = optimizacion.grilla({"a": [1, 2, 3], "b": [0.1, 0.2]})
    assert len(g) == 6 and {"a": 2, "b": 0.1} in g
    v = optimizacion.ventanas_walk_forward(100, 40, 10)
    assert len(v) == 6
    for tr, te in v:                       # la prueba SIEMPRE va después del entrenamiento
        assert tr.stop == te.start and te.stop <= 100


def test_sharpe_desinflado_castiga_probar_mucho():
    """Los mismos retornos valen menos si se llegó a ellos probando 500 combinaciones."""
    rng = random.Random(3)
    rets = [rng.gauss(0.0005, 0.01) for _ in range(2000)]
    una = optimizacion.sharpe_desinflado(rets, [0.0, 0.001])
    muchas = optimizacion.sharpe_desinflado(rets, [rng.gauss(0, 0.02) for _ in range(500)])
    assert una["ok"] and muchas["ok"]
    assert muchas["dsr"] < una["dsr"]
    assert muchas["sharpe_max_azar"] > una["sharpe_max_azar"]


def test_walk_forward_no_optimiza_sobre_lo_que_mide():
    """El tramo de prueba nunca debe influir en la elección de parámetros.

    Se arma una serie donde el combo A gana sólo en la primera mitad y el B sólo en la
    segunda. Un optimizador correcto elige A mirando el pasado y cobra el resultado de A
    en el futuro — o sea, pierde. Uno con fuga elegiría B y ganaría.
    """
    n = 400
    datos = {"A": [1.0 if i < 200 else -1.0 for i in range(n)],
             "B": [-1.0 if i < 200 else 1.0 for i in range(n)]}
    combos = [{"c": "A"}, {"c": "B"}]
    correr = lambda combo, idx: [datos[combo["c"]][i] for i in idx]  # noqa: E731
    r = optimizacion.optimizar_walk_forward(n, combos, correr, train=200, test=100,
                                            criterio=lambda x: sum(x))
    assert r["ok"]
    # Entrena en [0,200) donde gana A, y cobra A en [200,300): pierde.
    assert r["elegidos"][0]["params"]["c"] == "A"
    assert sum(r["retornos_oos"][:100]) < 0


def test_estabilidad_es_determinista():
    elegidos = [{"params": {"x": 1}}, {"params": {"x": 2}}, {"params": {"x": 1}},
                {"params": {"x": 2}}]
    modas = {optimizacion.estabilidad(elegidos)["x"]["moda"] for _ in range(20)}
    assert len(modas) == 1          # el empate se resuelve siempre igual
    est = optimizacion.estabilidad([{"params": {"x": 5}}] * 4)
    assert est["x"]["estabilidad_pct"] == 100.0


# ------------------------------------------ niveles de sesión de futuros
def _barra(ts, o, h, l, c, v=1000):
    return {"t": ts, "o": o, "h": h, "l": l, "c": c, "v": v}


def test_horario_de_nueva_york_con_dst():
    """Verano -4, invierno -5, con los domingos de cambio en su lugar."""
    import calendar
    enero = calendar.timegm((2026, 1, 15, 18, 0, 0, 0, 0, 0))
    julio = calendar.timegm((2026, 7, 15, 18, 0, 0, 0, 0, 0))
    assert niveles.offset_ny(enero) == -5
    assert niveles.offset_ny(julio) == -4
    # 14:30 UTC en julio son las 10:30 de Nueva York: dentro del RTH.
    media = calendar.timegm((2026, 7, 15, 14, 30, 0, 0, 0, 0))
    assert niveles.hora_ny(media).hour == 10


def test_agrupar_separa_rth_de_globex():
    """La rueda nocturna pertenece al día de negociación siguiente, no al propio."""
    import calendar
    barras = []
    # 2026-07-14, 22:00 UTC = 18:00 NY -> Globex del día 15
    barras.append(_barra(calendar.timegm((2026, 7, 14, 22, 0, 0, 0, 0, 0)), 100, 102, 99, 101))
    # 2026-07-15, 13:35 UTC = 9:35 NY -> RTH del día 15
    barras.append(_barra(calendar.timegm((2026, 7, 15, 13, 35, 0, 0, 0, 0)), 101, 105, 100, 104))
    # 2026-07-15, 20:30 UTC = 16:30 NY -> pausa, se descarta
    barras.append(_barra(calendar.timegm((2026, 7, 15, 20, 30, 0, 0, 0, 0)), 104, 110, 90, 95))
    ses = niveles.agrupar_sesiones(barras)
    dia15 = [s for s in ses if s["dia"] == "2026-07-15"][0]
    assert dia15["globex"]["h"] == 102          # la nocturna del 14 cuenta para el 15
    assert dia15["rth"]["h"] == 105
    assert dia15["rth"]["l"] == 100
    # La barra de la pausa no entra en ningún tramo.
    assert dia15["rth"]["h"] != 110


def test_pivotes_son_la_formula_de_piso():
    p = niveles.pivotes(110.0, 90.0, 100.0)
    assert abs(p["PP"] - 100.0) < 1e-12
    assert abs(p["R1"] - 110.0) < 1e-12          # 2·PP − mínimo
    assert abs(p["S1"] - 90.0) < 1e-12           # 2·PP − máximo
    assert abs(p["R2"] - 120.0) < 1e-12          # PP + rango
    assert abs(p["S2"] - 80.0) < 1e-12
    assert p["R3"] > p["R2"] > p["R1"] > p["PP"] > p["S1"] > p["S2"] > p["S3"]


def test_vwap_necesita_volumen():
    """Sin volumen devuelve None: un promedio simple no es un VWAP."""
    sin = [{"t": 0, "o": 10, "h": 11, "l": 9, "c": 10, "v": 0}]
    assert niveles.vwap(sin) is None
    con = [{"t": 0, "o": 10, "h": 12, "l": 9, "c": 12, "v": 100},
           {"t": 300, "o": 12, "h": 12, "l": 12, "c": 12, "v": 300}]
    v = niveles.vwap(con)
    assert v is not None
    # El segundo precio pesa el triple, así que el VWAP tiene que estar más cerca de 12.
    assert 11.0 < v <= 12.0


def test_rango_apertura_toma_solo_los_primeros_minutos():
    barras = [_barra(i * 300, 100, 100 + i, 100 - i, 100) for i in range(12)]
    ib = niveles.rango_apertura(barras, minutos=30)   # 30 min = 6 velas de 5m
    assert ib["barras"] == 6
    assert ib["alto"] == 105 and ib["bajo"] == 95


# --------------------------------------------- niveles desde las opciones
def test_gamma_es_maxima_en_el_dinero():
    """La gamma de Black-Scholes pica en el strike at-the-money y cae a los costados."""
    atm = opciones.gamma_bs(100.0, 100.0, 0.20, 0.08)
    otm = opciones.gamma_bs(100.0, 130.0, 0.20, 0.08)
    itm = opciones.gamma_bs(100.0, 70.0, 0.20, 0.08)
    assert atm > otm and atm > itm
    assert opciones.gamma_bs(100.0, 100.0, 0.0, 0.08) == 0.0     # sin vol, sin gamma
    # El piso de T evita que con vencimiento cero la gamma se vaya al infinito.
    assert math.isfinite(opciones.gamma_bs(100.0, 100.0, 0.20, 0.0))


def test_max_pain_en_una_cadena_construida():
    """El max pain cae donde el valor intrínseco total es mínimo.

    La cadena se carga de forma ASIMÉTRICA a propósito. Con interés abierto simétrico el
    dolor empata en varios strikes y el test no verifica nada: la primera versión de este
    fixture tenía tres strikes con dolor idéntico. Acá los calls van abajo, los puts
    arriba y con más peso, de modo que el mínimo sea único.

    Se compara contra una implementación independiente de la definición, no contra un
    número elegido a mano.
    """
    carga = {90.0: ("oi_call", 1000), 95.0: ("oi_call", 1000),
             105.0: ("oi_put", 3000), 110.0: ("oi_put", 1000)}
    por_strike = {}
    for k in (90.0, 95.0, 100.0, 105.0, 110.0):
        por_strike[k] = {"strike": k, "oi_call": 0, "oi_put": 0, "vol_call": 0,
                         "vol_put": 0, "gamma_call": 0.0, "gamma_put": 0.0,
                         "iv_call": None, "iv_put": None}
    for k, (campo, v) in carga.items():
        por_strike[k][campo] = v

    dolores = {}
    for s_ in sorted(por_strike):
        dolores[s_] = sum((s_ - k) * por_strike[k]["oi_call"] if k < s_
                          else ((k - s_) * por_strike[k]["oi_put"] if k > s_ else 0)
                          for k in por_strike)
    minimo = min(dolores.values())
    ganadores = [k for k, v in dolores.items() if v == minimo]
    assert len(ganadores) == 1, f"el fixture quedó degenerado: empatan {ganadores}"
    assert opciones.max_pain(por_strike) == ganadores[0]


def test_strikes_se_traducen_a_puntos_del_futuro():
    """Sin corregir por la base, los niveles quedan desplazados decenas de puntos."""
    cadena = {"status": "ok", "selected_expiration": None,
              "calls": [{"strike": 7800.0, "open_interest": 5000, "volume": 100, "iv": 16.0}],
              "puts": [{"strike": 7700.0, "open_interest": 9000, "volume": 200, "iv": 18.0}]}
    r = opciones.analizar([cadena], spot_indice=7800.0, spot_futuro=7860.0, rango_pct=5.0)
    assert r["ok"]
    base_exacta = 7860.0 / 7800.0
    assert abs(r["base"] - base_exacta) < 1e-5     # el informe la redondea a 5 decimales
    muro = [n for n in r["niveles"] if n["nombre"] == "Muro de puts"]
    assert muro, "debería detectar el muro de puts por debajo del precio"
    # strike 7700 del índice -> ~7759 en puntos del futuro. Se compara contra la base
    # EXACTA, no contra la redondeada del informe, con tolerancia de medio centavo.
    assert abs(muro[0]["precio"] - 7700.0 * base_exacta) < 0.005
    assert muro[0]["precio"] > 7700.0              # el futuro cotiza sobre el índice


def test_filtro_de_cercania_descarta_coberturas_lejanas():
    """Un muro a 20% del precio es real y no sirve para operar la sesión."""
    cadena = {"status": "ok", "selected_expiration": None, "calls": [],
              "puts": [{"strike": 6200.0, "open_interest": 90000, "volume": 10, "iv": 25.0},
                       {"strike": 7700.0, "open_interest": 4000, "volume": 10, "iv": 18.0}]}
    r = opciones.analizar([cadena], 7800.0, 7860.0, rango_pct=5.0)
    muro = [n for n in r["niveles"] if n["nombre"] == "Muro de puts"][0]
    assert muro["strike"] == 7700.0      # no el de 6200, aunque tenga 20 veces más OI
    assert r["n_strikes_cerca"] < r["n_strikes"]


# --------------------------------------- estadística de toques de nivel
def test_wilson_es_honesto_con_muestras_chicas():
    """La aproximación normal se sale de [0,1]; Wilson no."""
    lo, hi = stats_wilson(3, 4)
    assert 0.0 <= lo < 0.75 < hi <= 1.0
    assert hi - lo > 0.5               # con 4 datos la incertidumbre es enorme
    lo2, hi2 = stats_wilson(300, 400)
    assert hi2 - lo2 < 0.1             # con 400 se angosta
    # Los extremos quedan acotados en vez de colapsar a un punto.
    assert stats_wilson(0, 10)[1] > 0.0
    assert stats_wilson(10, 10)[0] < 1.0


def _sesion_sintetica(ohlc_rth, dia="2026-07-15"):
    """Arma barras de 5 minutos dentro del RTH de Nueva York para un día dado."""
    import calendar
    y, m, d = (int(x) for x in dia.split("-"))
    base = calendar.timegm((y, m, d, 13, 35, 0, 0, 0, 0))   # 9:35 NY en julio
    return [{"t": base + i * 300, "o": o, "h": h, "l": lo, "c": c, "v": 100}
            for i, (o, h, lo, c) in enumerate(ohlc_rth)]


def test_toque_que_aguanta_y_toque_que_rompe():
    """Desde abajo el nivel es resistencia: alejarse = aguantó, pasarlo = rompió."""
    nivel = {"N": 100.0}
    # Llega desde abajo, toca 100 y se cae a 97: aguantó (margen = 0.25·ATR = 2.5)
    aguanta = _sesion_sintetica([(95, 96, 94, 95), (96, 100, 96, 99),
                                 (99, 99, 97, 97), (97, 97, 96, 96)])
    acc = {}
    toques._recorrer_sesion(aguanta, nivel, 10.0, 0.10, 0.25, 24, acc)
    assert acc["N"]["toques"] == 1 and acc["N"]["aguanto"] == 1 and acc["N"]["rompio"] == 0

    # Mismo arranque pero sigue a 103: rompió
    rompe = _sesion_sintetica([(95, 96, 94, 95), (96, 100, 96, 99),
                               (99, 103, 99, 103), (103, 104, 102, 103)])
    acc2 = {}
    toques._recorrer_sesion(rompe, nivel, 10.0, 0.10, 0.25, 24, acc2)
    assert acc2["N"]["toques"] == 1 and acc2["N"]["rompio"] == 1 and acc2["N"]["aguanto"] == 0


def test_vela_ambigua_no_se_decide():
    """Si una sola vela cumple las dos condiciones, no se sabe cuál pasó primero."""
    barras = _sesion_sintetica([(95, 96, 94, 95), (96, 100, 96, 99),
                                (99, 104, 96, 100)])     # esa vela va a +4 y a −3
    acc = {}
    toques._recorrer_sesion(barras, {"N": 100.0}, 10.0, 0.10, 0.25, 24, acc)
    assert acc["N"]["ambiguos"] == 1
    assert acc["N"]["aguanto"] == 0 and acc["N"]["rompio"] == 0


def test_toque_sin_resolver_no_suma_a_ningun_lado():
    barras = _sesion_sintetica([(95, 96, 94, 95), (96, 100, 96, 99)] +
                               [(99, 100, 99, 99)] * 8)   # queda pegado al nivel
    acc = {}
    toques._recorrer_sesion(barras, {"N": 100.0}, 10.0, 0.10, 0.25, 3, acc)
    assert acc["N"]["toques"] == 1
    assert acc["N"]["aguanto"] == 0 and acc["N"]["rompio"] == 0
    assert acc["N"]["sin_resolver"] >= 1


def _foto(sesion, momento, gex, oi_c, oi_p, strikes=None):
    return {"ok": True, "indice": "^TEST", "sesion": sesion, "momento": momento,
            "spot": 100.0, "vencimientos": [1],
            "agregados": {"gex_total": gex, "oi_calls": oi_c, "oi_puts": oi_p,
                          "max_pain": 100.0, "gamma_cero": 99.0,
                          "muro_calls": 110.0, "muro_puts": 90.0},
            "strikes": strikes or [{"k": 100.0, "vc": 10, "vp": 5, "oic": oi_c, "oip": oi_p}]}


def test_el_parte_de_sesion_marca_donde_esta_el_precio():
    """El parte ordena los niveles por precio y mete una marca en el lugar del precio.

    Sin esa marca hay que comparar número por número para saber qué está arriba y qué
    abajo, que es justo lo que no se puede hacer a las nueve de la mañana.
    """
    import importlib.util
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "brief_sesion.py")
    spec = importlib.util.spec_from_file_location("brief_sesion", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    falso = {
        "ok": True, "precio": 100.0, "valor_punto": 50.0,
        "sesion": {"rth_previo": {"c": 98.0}, "atr_sesion": 10.0},
        "opciones": {"regimen_gamma": "negativa (movimiento amplificado)"},
        "niveles": [
            {"nombre": "Muro de calls", "precio": 120.0, "origen": "opciones"},
            {"nombre": "Pivote R1", "precio": 105.0, "origen": "sesion"},
            {"nombre": "Pivote S1", "precio": 95.0, "origen": "sesion"},
            {"nombre": "Muro de puts", "precio": 80.0, "origen": "opciones"},
            {"nombre": "VWAP de sesión", "precio": 99.0, "origen": "sesion"},
        ],
    }
    original = mod.futuros.tablero
    try:
        mod.futuros.tablero = lambda *a, **k: falso
        texto = mod.parte("XX=F")
    finally:
        mod.futuros.tablero = original

    lineas = texto.split("\n")
    i_marca = next(i for i, l in enumerate(lineas) if "── precio" in l)
    arriba = "\n".join(lineas[:i_marca])
    abajo = "\n".join(lineas[i_marca:])
    assert "Muro de calls" in arriba and "Pivote R1" in arriba
    assert "Pivote S1" in abajo and "Muro de puts" in abajo
    # El VWAP no va: antes de la apertura todavía no existe.
    assert "VWAP" not in texto, "incluyó un nivel que no existe antes de abrir"
    assert "+2.00" in texto, "no calculó el hueco contra el cierre previo"
    assert "◆" in arriba, "no distingue los niveles de opciones"


def test_snapshot_no_duplica_la_misma_captura():
    """Correr el script dos veces el mismo minuto no debe inventar una observación."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = _foto("2026-10-15", "2026-10-15T20:48:00+00:00", -10.0, 100, 120)
        r1 = snapshots.guardar(f, d)
        r2 = snapshots.guardar(f, d)
        assert r1["duplicada"] is False and r1["total"] == 1
        assert r2["duplicada"] is True, "duplicó la misma captura"
        assert len(snapshots.leer("^TEST", d)) == 1


def test_serie_se_queda_con_la_ultima_foto_de_cada_sesion():
    """Si hubo varias capturas intradía, la que vale es la del cierre."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        snapshots.guardar(_foto("2026-10-15", "2026-10-15T14:00:00+00:00", -1.0, 100, 100), d)
        snapshots.guardar(_foto("2026-10-15", "2026-10-15T20:48:00+00:00", -9.0, 111, 122), d)
        snapshots.guardar(_foto("2026-10-16", "2026-10-16T20:48:00+00:00", -4.0, 131, 142), d)
        s = snapshots.serie("^TEST", d)
        assert s["n"] == 2, f"contó capturas en vez de sesiones: {s['n']}"
        assert s["capturas"] == 3
        # De la sesión del 15 tiene que quedar la de las 20:48, no la de las 14:00.
        assert s["serie"][0]["gex_total"] == -9.0
        # Y el cambio se calcula contra ESA, no contra la intradía.
        assert s["serie"][1]["d_oi_calls"] == 20     # 131 - 111
        assert s["serie"][1]["d_gex_total"] == 5.0   # -4 - (-9)


def test_serie_detecta_si_el_interes_abierto_roto_en_el_dia():
    """Comparar la foto previa a la apertura con la del cierre mide el desfase real.

    Si el interés abierto de las dos fotos de una misma sesión es el mismo, el feed no
    rotó el dato en el medio y el desfase de un día es el que se supone. Si difiere, rotó,
    y la suposición estaba mal. Mejor medirlo que creerlo.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        previa = _foto("2026-10-16", "2026-10-16T13:07:00+00:00", -3.0, 100, 120)
        previa["fase"] = "previa"
        cierre = _foto("2026-10-16", "2026-10-16T20:48:00+00:00", -4.0, 100, 120)
        cierre["fase"] = "cierre"
        snapshots.guardar(previa, d)
        snapshots.guardar(cierre, d)
        f = snapshots.serie("^TEST", d)["serie"][0]
        assert f["fase"] == "cierre", "la fila tiene que ser la foto del cierre"
        assert f["oi_calls_previa"] == 100
        assert f["oi_roto_en_el_dia"] is False

        # Ahora una sesión donde el feed SÍ rotó el dato entre las dos fotos.
        pv2 = _foto("2026-10-17", "2026-10-17T13:07:00+00:00", -3.0, 100, 120)
        pv2["fase"] = "previa"
        ci2 = _foto("2026-10-17", "2026-10-17T20:48:00+00:00", -4.0, 155, 166)
        ci2["fase"] = "cierre"
        snapshots.guardar(pv2, d)
        snapshots.guardar(ci2, d)
        f2 = snapshots.serie("^TEST", d)["serie"][1]
        assert f2["oi_roto_en_el_dia"] is True, "no detectó que el dato cambió en el día"


def test_serie_declara_el_desfase_del_interes_abierto():
    """El oi va un día atrasado respecto del volumen; eso tiene que estar dicho.

    Si queda implícito, alguien regresa cambio de oi contra el retorno siguiente, se
    equivoca por un día y obtiene un resultado que parece real.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        snapshots.guardar(_foto("2026-10-15", "2026-10-15T20:48:00+00:00", -9.0, 111, 122), d)
        assert snapshots.serie("^TEST", d)["desfase_oi"] == -1


def test_serie_avisa_que_la_muestra_no_alcanza():
    """Con 2 sesiones no se mide nada, y el reporte tiene que decirlo solo."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        snapshots.guardar(_foto("2026-10-15", "2026-10-15T20:48:00+00:00", -9.0, 111, 122), d)
        snapshots.guardar(_foto("2026-10-16", "2026-10-16T20:48:00+00:00", -4.0, 131, 142), d)
        s = snapshots.serie("^TEST", d)
        assert s["medible"] is False
        assert "control al azar" in s["aviso"], "no advierte que falta el control"
        assert snapshots.serie("^TEST", d + "/vacio")["n"] == 0


def test_snapshot_sobrevive_una_linea_rota():
    """Un archivo con una línea corrupta no debe tirar abajo el histórico entero."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        snapshots.guardar(_foto("2026-10-15", "2026-10-15T20:48:00+00:00", -9.0, 111, 122), d)
        with open(snapshots.ruta("^TEST", d), "a", encoding="utf-8") as f:
            f.write("{esto no es json\n")
        snapshots.guardar(_foto("2026-10-16", "2026-10-16T20:48:00+00:00", -4.0, 131, 142), d)
        assert len(snapshots.leer("^TEST", d)) == 2


def test_enfriamiento_no_recuenta_una_consolidacion_pegada_al_nivel():
    """Un toque resuelto no se vuelve a contar hasta que el precio se aleja.

    Sin enfriamiento, una consolidación de una hora sobre el nivel registraba un toque por
    vela y la muestra se inflaba sola. El criterio es: el toque cuenta de nuevo recién
    cuando una vela deja de tocar la banda de tolerancia.
    """
    # Toca 100 desde abajo, aguanta (cae a 97), y se queda pegado al nivel 6 velas más.
    barras = _sesion_sintetica([(95, 96, 94, 95), (96, 100, 96, 99), (99, 99, 97, 97)] +
                               [(99, 100, 99, 99)] * 6)
    acc = {}
    toques._recorrer_sesion(barras, {"N": 100.0}, 10.0, 0.10, 0.25, 24, acc)
    assert acc["N"]["aguanto"] == 1
    assert acc["N"]["toques"] == 1, f"se recontó la consolidación: {acc['N']}"

    # En cambio, si el precio SE ALEJA y vuelve, eso sí es un toque nuevo.
    barras = _sesion_sintetica([(95, 96, 94, 95), (96, 100, 96, 99), (99, 99, 97, 97),
                                (97, 97, 90, 91),    # se va lejos: se arma de nuevo
                                (91, 100, 91, 99), (99, 99, 97, 97)])
    acc = {}
    toques._recorrer_sesion(barras, {"N": 100.0}, 10.0, 0.10, 0.25, 24, acc)
    assert acc["N"]["toques"] == 2, f"no reconoció el segundo acercamiento: {acc['N']}"
    assert acc["N"]["aguanto"] == 2


def test_direccion_de_aproximacion():
    """Desde arriba el nivel es soporte y las condiciones se dan vuelta."""
    # Viene de arriba (105), toca 100 y sube a 103: para un soporte eso es AGUANTAR
    barras = _sesion_sintetica([(105, 106, 104, 105), (104, 104, 100, 101),
                                (101, 103, 101, 103)])
    acc = {}
    toques._recorrer_sesion(barras, {"N": 100.0}, 10.0, 0.10, 0.25, 24, acc)
    assert acc["N"]["aguanto"] == 1
    assert "desde_arriba" in str(acc["N"]["por_direccion"])


def test_el_procedimiento_tiene_sesgo_y_queda_documentado():
    """Niveles AL AZAR sobre un paseo aleatorio dan muy por encima del 50%.

    Esto NO es un error: es la propiedad que obliga a comparar siempre contra el
    control. Una vela que toca un nivel desde abajo suele cerrar por debajo, así que
    arranca más cerca de la condición de 'aguantó'. Si alguien 'arregla' el motor para
    que dé 50%, habrá cambiado la definición, no corregido un bug.
    """
    rng = random.Random(4)
    px = 100.0
    barras = []
    import calendar
    base = calendar.timegm((2026, 7, 15, 13, 35, 0, 0, 0, 0))
    for i in range(300):
        o = px
        h = o + abs(rng.gauss(0, 0.4))
        lo = o - abs(rng.gauss(0, 0.4))
        c = rng.uniform(lo, h)
        barras.append({"t": base + i * 300, "o": o, "h": h, "l": lo, "c": c, "v": 10})
        px = c
    acc = {}
    # Cinco niveles repartidos por el rango recorrido
    precios = {f"L{j}": 98.0 + j * 1.0 for j in range(5)}
    toques._recorrer_sesion(barras, precios, 2.0, 0.10, 0.25, 24, acc)
    res = sum(a["aguanto"] + a["rompio"] for a in acc.values())
    ag = sum(a["aguanto"] for a in acc.values())
    assert res >= 20, "el fixture debería producir toques suficientes"
    tasa = ag / res
    assert tasa > 0.55, (f"el sesgo del procedimiento debería elevar la tasa muy por "
                         f"encima del 50%; dio {tasa:.2%}")


def test_contra_el_nulo_marca_lo_que_no_informa():
    """Un nivel con tasa igual a la del control no puede declararse informativo."""
    rep = {"ok": True,
           "global": {"tasa_aguante": 73.0},
           "niveles": [{"nivel": "A", "resueltos": 100, "aguanto": 73, "toques": 100,
                        "suficiente": True},
                       {"nivel": "B", "resueltos": 100, "aguanto": 95, "toques": 100,
                        "suficiente": True}]}
    nulo = {"ok": True, "media": 73.0, "tasas": [73.0] * 50}
    r = toques.contra_el_nulo(rep, nulo)
    a, b = r["niveles"]
    assert a["exceso"] == 0.0 and a["informativo"] is False
    assert b["exceso"] > 20 and b["supera_azar"] is True
    assert r["niveles_informativos"] == 1


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
