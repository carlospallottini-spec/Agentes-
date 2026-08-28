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

from quant import backtest, markov, momentum, ou, pairs, regimen_vol, scan  # noqa: E402
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
