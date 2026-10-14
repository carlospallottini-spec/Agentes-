"""¿Los niveles aguantan o se rompen? Estadística de toques por nivel.

Un nivel dibujado en el gráfico no dice nada por sí solo. Lo que sirve saber es: de las
veces que el precio llegó hasta acá, ¿cuántas rebotó y cuántas pasó de largo? Este módulo
lo cuenta sobre el historial disponible y lo devuelve con intervalo de confianza, porque
"aguantó el 62%" sobre 8 toques y sobre 80 son dos afirmaciones muy distintas.

**Cómo se clasifica un toque.** El precio *toca* el nivel cuando la vela lo contiene dentro
de una tolerancia (una fracción del ATR de sesión). A partir de la vela SIGUIENTE se mira
qué pasa primero:

  · Si venía **desde abajo**, el nivel actúa de resistencia:
      *aguantó* = el precio se alejó `margen` por debajo del nivel
      *rompió*  = el precio superó el nivel por `margen`
  · Si venía **desde arriba**, el nivel actúa de soporte, y las dos condiciones se invierten.

**Los casos ambiguos no se cuentan.** Si una sola vela cumple las dos condiciones —algo que
pasa en las velas anchas— con datos de 5 minutos es imposible saber cuál ocurrió primero.
Igual que en el análisis del Gap-Fade, esos toques se reportan aparte en vez de decidirse
con un supuesto. Lo mismo con los que nunca se resuelven dentro del horizonte.

**Sin mirar el futuro.** Los niveles de cada sesión salen de datos cerrados *antes* de que
esa sesión empiece: RTH previo, rueda nocturna ya terminada, pivotes y ATR de las sesiones
anteriores. El contador avanza sesión por sesión en orden.
"""
from __future__ import annotations

import math

from quant import niveles as nv
from quant.stats import normal_cdf, wilson

# Niveles que se conocen ANTES de que abra la sesión y por eso son medibles.
# El VWAP queda afuera a propósito: se mueve con cada vela y "tocarlo" no está definido
# al principio de la rueda.
ESTATICOS = ["Cierre RTH previo", "Máximo RTH previo", "Mínimo RTH previo",
             "Máximo Globex", "Mínimo Globex",
             "Pivote PP", "Pivote R1", "Pivote S1", "Pivote R2", "Pivote S2",
             "Techo esperado (apertura + ATR)", "Piso esperado (apertura − ATR)"]

DESDE_ABAJO, DESDE_ARRIBA = 1, -1


def _niveles_de_sesion(sesiones: list[dict], i: int, periodo_atr: int) -> dict[str, float]:
    """Niveles de la sesión `i`, calculados sólo con lo que cerró antes de que abriera."""
    if i < 1:
        return {}
    prev = sesiones[i - 1].get("rth")
    if not prev:
        return {}
    out = {"Cierre RTH previo": prev["c"], "Máximo RTH previo": prev["h"],
           "Mínimo RTH previo": prev["l"]}
    glx = sesiones[i].get("globex")
    if glx:
        out["Máximo Globex"] = glx["h"]
        out["Mínimo Globex"] = glx["l"]
    for k, v in nv.pivotes(prev["h"], prev["l"], prev["c"]).items():
        out[f"Pivote {k}"] = v
    atr = nv.atr_sesiones(sesiones[:i], periodo_atr)
    rth = sesiones[i].get("rth")
    if atr and rth:
        out["Techo esperado (apertura + ATR)"] = rth["o"] + atr
        out["Piso esperado (apertura − ATR)"] = rth["o"] - atr
    return {k: v for k, v in out.items() if k in ESTATICOS}


def _recorrer_sesion(barras: list[dict], niveles_ses: dict[str, float], atr: float,
                     tol_atr: float, margen_atr: float, max_barras: int,
                     acc: dict) -> None:
    """Cuenta los toques de una sesión y los suma al acumulador `acc`."""
    tol = tol_atr * atr
    margen = margen_atr * atr
    estado: dict[str, dict] = {}

    for idx, b in enumerate(barras):
        alto = b.get("h", b["c"])
        bajo = b.get("l", b["c"])
        for nombre, precio in niveles_ses.items():
            a = acc.setdefault(nombre, {"toques": 0, "aguanto": 0, "rompio": 0,
                                        "ambiguos": 0, "sin_resolver": 0,
                                        "por_hora": {}, "por_direccion": {}})
            st = estado.get(nombre)

            toca = bajo <= precio + tol and alto >= precio - tol

            if st is not None and st.get("espera"):
                # Enfriamiento: tras resolver, el precio tiene que ALEJARSE del nivel
                # antes de que cuente un toque nuevo. Sin esto, una consolidación
                # pegada al nivel registra un toque por vela.
                if not toca:
                    del estado[nombre]
                continue

            if st is None:
                # Todavía no hay un toque abierto: ¿esta vela toca el nivel?
                if toca:
                    anterior = barras[idx - 1]["c"] if idx > 0 else b.get("o", b["c"])
                    direccion = DESDE_ABAJO if anterior < precio else DESDE_ARRIBA
                    estado[nombre] = {"dir": direccion, "i": idx,
                                      "hora": nv.hora_ny(b["t"]).hour}
                    a["toques"] += 1
                continue

            if idx <= st["i"]:
                continue   # la resolución se mira recién desde la vela siguiente

            rompe_arriba = alto >= precio + margen
            rompe_abajo = bajo <= precio - margen
            resultado = None
            if rompe_arriba and rompe_abajo:
                resultado = "ambiguos"       # una sola vela hizo las dos cosas
            elif st["dir"] == DESDE_ABAJO:
                resultado = "rompio" if rompe_arriba else ("aguanto" if rompe_abajo else None)
            else:
                resultado = "rompio" if rompe_abajo else ("aguanto" if rompe_arriba else None)

            if resultado is None and idx - st["i"] >= max_barras:
                resultado = "sin_resolver"
            if resultado:
                a[resultado] += 1
                if resultado in ("aguanto", "rompio"):
                    h = a["por_hora"].setdefault(st["hora"], {"aguanto": 0, "rompio": 0})
                    h[resultado] += 1
                    d = "desde_abajo" if st["dir"] == DESDE_ABAJO else "desde_arriba"
                    dd = a["por_direccion"].setdefault(d, {"aguanto": 0, "rompio": 0})
                    dd[resultado] += 1
                # Siempre se pasa por enfriamiento, aun cuando el precio ya se alejó:
                # la vela siguiente lo resuelve sin costo.
                estado[nombre] = {"espera": True}

    # Los toques que quedaron abiertos al cierre de la sesión no se deciden.
    for nombre, st in estado.items():
        if not st.get("espera"):
            acc[nombre]["sin_resolver"] += 1


def estadistica(barras: list[dict], tol_atr: float = 0.10, margen_atr: float = 0.25,
                max_barras: int = 24, periodo_atr: int = 14,
                min_toques: int = 8) -> dict:
    """Tasa de aguante por nivel sobre todo el historial disponible.

    `tol_atr` y `margen_atr` van en fracciones del ATR de sesión, así que el criterio se
    adapta solo entre ES (ATR ~60 puntos) y NQ (ATR ~350): un margen fijo en puntos haría
    que el mismo número significara cosas distintas en cada contrato.
    """
    sesiones = nv.agrupar_sesiones(barras)
    if len(sesiones) < periodo_atr + 3:
        return {"ok": False, "motivo": f"Hacen falta al menos {periodo_atr + 3} sesiones; "
                                        f"hay {len(sesiones)}."}

    acc: dict[str, dict] = {}
    usadas = 0
    for i in range(1, len(sesiones)):
        rth = sesiones[i].get("rth")
        barras_rth = sesiones[i].get("barras_rth") or []
        if not rth or len(barras_rth) < 10:
            continue
        ns = _niveles_de_sesion(sesiones, i, periodo_atr)
        atr = nv.atr_sesiones(sesiones[:i], periodo_atr)
        if not ns or not atr:
            continue
        _recorrer_sesion(barras_rth, ns, atr, tol_atr, margen_atr, max_barras, acc)
        usadas += 1

    filas = []
    for nombre, a in acc.items():
        resueltos = a["aguanto"] + a["rompio"]
        if resueltos == 0:
            continue
        lo, hi = wilson(a["aguanto"], resueltos)
        fila = {
            "nivel": nombre,
            "toques": a["toques"],
            "resueltos": resueltos,
            "aguanto": a["aguanto"],
            "rompio": a["rompio"],
            "ambiguos": a["ambiguos"],
            "sin_resolver": a["sin_resolver"],
            "tasa_aguante": round(100.0 * a["aguanto"] / resueltos, 1),
            "ic95_bajo": round(100.0 * lo, 1),
            "ic95_alto": round(100.0 * hi, 1),
            # Un nivel "informativo" es aquel cuyo intervalo no contiene el 50%:
            # si lo contiene, no se distingue de tirar una moneda.
            "distinto_de_azar": bool(lo > 0.5 or hi < 0.5),
            "suficiente": a["toques"] >= min_toques,
        }
        for d in ("desde_abajo", "desde_arriba"):
            dd = a["por_direccion"].get(d)
            if dd:
                n = dd["aguanto"] + dd["rompio"]
                fila[d] = {"n": n, "tasa": round(100.0 * dd["aguanto"] / n, 1) if n else None}
        filas.append(fila)

    filas.sort(key=lambda f: -f["resueltos"])
    total_res = sum(f["resueltos"] for f in filas)
    total_ag = sum(f["aguanto"] for f in filas)
    glo_lo, glo_hi = wilson(total_ag, total_res) if total_res else (0.0, 1.0)

    return {
        "ok": True,
        "sesiones_usadas": usadas,
        "parametros": {"tolerancia_atr": tol_atr, "margen_atr": margen_atr,
                       "max_barras": max_barras, "periodo_atr": periodo_atr,
                       "min_toques": min_toques},
        "global": {"resueltos": total_res, "aguanto": total_ag,
                   "tasa_aguante": round(100.0 * total_ag / total_res, 1) if total_res else None,
                   "ic95_bajo": round(100.0 * glo_lo, 1),
                   "ic95_alto": round(100.0 * glo_hi, 1)},
        "niveles": filas,
    }


def nulo_niveles_aleatorios(barras: list[dict], repeticiones: int = 200,
                            semilla: int = 20261015, tol_atr: float = 0.10,
                            margen_atr: float = 0.25, max_barras: int = 24,
                            periodo_atr: int = 14) -> dict:
    """Tasa de aguante de niveles puestos AL AZAR, con el mismo procedimiento.

    Es el control que decide si la estadística mide algo. El procedimiento tiene un sesgo
    propio: una vela que toca una resistencia desde abajo suele cerrar por debajo del
    nivel, así que ya arranca más cerca de la condición de "aguantó" que de la de
    "rompió". Ese sesgo produce tasas altas **aunque el nivel no signifique nada**.

    Para medirlo se repite todo con niveles colocados al azar dentro del rango de la
    sesión previa ampliado por un ATR, en la misma cantidad y con las mismas reglas. Si
    los niveles de verdad no le ganan a esto, lo que se está midiendo es la mecánica de
    la medición y no el mercado.
    """
    import random

    sesiones = nv.agrupar_sesiones(barras)
    if len(sesiones) < periodo_atr + 3:
        return {"ok": False, "motivo": "Historial insuficiente para el nulo."}

    rng = random.Random(semilla)
    tasas = []
    for _ in range(repeticiones):
        acc: dict[str, dict] = {}
        for i in range(1, len(sesiones)):
            rth = sesiones[i].get("rth")
            barras_rth = sesiones[i].get("barras_rth") or []
            if not rth or len(barras_rth) < 10:
                continue
            reales = _niveles_de_sesion(sesiones, i, periodo_atr)
            atr = nv.atr_sesiones(sesiones[:i], periodo_atr)
            if not reales or not atr:
                continue
            prev = sesiones[i - 1]["rth"]
            lo, hi = prev["l"] - atr, prev["h"] + atr
            falsos = {f"azar{j}": rng.uniform(lo, hi) for j in range(len(reales))}
            _recorrer_sesion(barras_rth, falsos, atr, tol_atr, margen_atr, max_barras, acc)
        res = sum(a["aguanto"] + a["rompio"] for a in acc.values())
        ag = sum(a["aguanto"] for a in acc.values())
        if res > 0:
            tasas.append(100.0 * ag / res)

    if not tasas:
        return {"ok": False, "motivo": "El nulo no produjo toques resueltos."}
    tasas.sort()
    n = len(tasas)
    media = sum(tasas) / n
    return {"ok": True, "n": n, "media": round(media, 2),
            "p05": round(tasas[int(0.05 * (n - 1))], 2),
            "p50": round(tasas[(n - 1) // 2], 2),
            "p95": round(tasas[int(0.95 * (n - 1))], 2),
            "min": round(tasas[0], 2), "max": round(tasas[-1], 2),
            "tasas": tasas}


def p_empirico(observada: float, nulo: dict) -> float:
    """Fracción del nulo que iguala o supera la tasa observada (Davison-Hinkley)."""
    if not nulo.get("ok"):
        return float("nan")
    t = nulo["tasas"]
    return (sum(1 for v in t if v >= observada) + 1) / (len(t) + 1)


def contra_el_nulo(rep: dict, nulo: dict, alpha: float = 0.05) -> dict:
    """Compara cada nivel contra la tasa que dan los niveles al azar.

    La tasa absoluta no sirve: el procedimiento de medición produce ~73% con CUALQUIER
    precio. Lo único informativo es el **exceso** sobre esa base, y si ese exceso se
    distingue de cero. Se usa la aproximación normal a la binomial contra la base del
    nulo, y se corrige por la cantidad de niveles probados (Bonferroni), porque mirar
    doce niveles y quedarse con el mejor es la receta conocida para encontrar nada.
    """
    if not rep.get("ok") or not nulo.get("ok"):
        return rep
    base = nulo["media"] / 100.0
    filas = rep.get("niveles", [])
    n_pruebas = max(len(filas), 1)
    umbral = alpha / n_pruebas

    for f in filas:
        n = f["resueltos"]
        p = f["aguanto"] / n if n else 0.0
        se = math.sqrt(base * (1.0 - base) / n) if n > 0 else 0.0
        z = (p - base) / se if se > 0 else 0.0
        pv = 2.0 * (1.0 - normal_cdf(abs(z)))
        f["base_azar"] = round(nulo["media"], 1)
        f["exceso"] = round(100.0 * (p - base), 1)
        f["z_vs_azar"] = round(z, 2)
        f["p_vs_azar"] = pv
        f["supera_azar"] = bool(pv < alpha and z > 0)
        f["supera_azar_corregido"] = bool(pv < umbral and z > 0)
        # La tasa absoluta induce a error: se marca explícitamente.
        f["informativo"] = f["supera_azar_corregido"] and f["suficiente"]

    rep["nulo"] = {k: v for k, v in nulo.items() if k != "tasas"}
    rep["p_empirico_global"] = p_empirico(rep["global"]["tasa_aguante"], nulo)
    rep["umbral_bonferroni"] = round(umbral, 5)
    rep["niveles_informativos"] = sum(1 for f in filas if f["informativo"])
    rep["veredicto"] = (
        "Ningún nivel supera a colocar una línea al azar dentro del rango. La tasa de "
        "aguante alta es del PROCEDIMIENTO, no de los niveles: una vela que toca una "
        "resistencia desde abajo suele cerrar por debajo, así que arranca más cerca de "
        "'aguantó'. Los niveles sirven como mapa de dónde mirar, no como probabilidad."
        if rep["niveles_informativos"] == 0 else
        f"{rep['niveles_informativos']} nivel(es) superan al azar tras corregir por "
        f"multiplicidad. Verificarlo con más historial antes de confiar.")
    return rep
