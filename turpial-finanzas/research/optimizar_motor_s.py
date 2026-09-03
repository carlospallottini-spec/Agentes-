"""Optimización honesta del motor S (SessionMarkov) del EA DualNasdaq.

Optimizar sobre toda la muestra y quedarse con el mejor es cómo se fabrica una estrategia
que no existe. Acá se hacen las dos cosas, a propósito:

  1. **La forma ingenua**: barrer las 750 combinaciones sobre los 20 años y quedarse con
     la mejor. Sirve para medir cuánto infla, no para operar.
  2. **La forma honesta**: walk-forward. Se optimiza en 6 años y se mide en los 2
     siguientes, que el optimizador nunca vio; se avanza y se repite. 12 años fuera de
     muestra.

Y tres controles sobre el resultado:
  · **Sharpe desinflado** (Bailey y López de Prado): descuenta el Sharpe por haber probado
    750 combinaciones.
  · **Nulo por combinación al azar**: en vez de elegir la mejor de cada ventana, elegir una
    cualquiera. Si optimizar no le gana a sortear, el optimizador no está aprendiendo nada.
  · **Estabilidad de parámetros**: si cada ventana elige valores distintos, está
    persiguiendo ruido.

  python research/optimizar_motor_s.py --guardar
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors import market  # noqa: E402
from quant import intradia, optimizacion, scan  # noqa: E402

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")

ANIOS = 20
COSTO_BPS = 1.0
RIESGO_PCT = 0.75          # el que pidió el usuario: la mitad del default del EA
TRAIN, TEST = 1512, 504    # 6 años de entrenamiento, 2 de prueba

ESPACIO = {
    "periodo": [10, 14, 20],
    "atr_drop": [0.5, 0.75, 1.0, 1.25, 1.5],
    "close_pos": [0.10, 0.15, 0.20, 0.30, 0.40],
    "stop_atr": [0.0, 1.0, 1.5, 2.0, 3.0],
    "exigir_ambas": [False, True],
}
DEFECTO = {"periodo": 14, "atr_drop": 1.0, "close_pos": 0.20, "stop_atr": 2.0,
           "exigir_ambas": False}


def bajar(symbol: str, anios: int) -> list[dict]:
    h = market.velas(symbol, "1d", anios * 365)
    return [p for p in h.get("points", [])
            if p.get("c") and all(k in p for k in ("o", "h", "l")) and p["o"] > 0]


def construir_cache(ohlc: list[dict], combos: list[dict], riesgo: float,
                    costo: float) -> dict[tuple, list[float]]:
    """Retornos diarios de CADA combinación sobre la serie completa, una sola vez.

    Se calcula sobre toda la serie y después se recorta por índice: si en cambio se
    recortara la serie antes, las primeras barras de cada ventana no tendrían historia
    para el ATR y el resultado dependería de dónde cae el corte.
    """
    atrs = {p: intradia.atr_serie(ohlc, p) for p in set(c["periodo"] for c in combos)}
    cache = {}
    for c in combos:
        a = atrs[c["periodo"]]
        mask = intradia.señal_session_markov(ohlc, periodo=c["periodo"],
                                             atr_drop=c["atr_drop"],
                                             close_pos=c["close_pos"],
                                             exigir_ambas=c["exigir_ambas"], atr=a)
        r = intradia.simular_session_markov(ohlc, mask, periodo=c["periodo"],
                                            riesgo_pct=riesgo, stop_atr=c["stop_atr"],
                                            cost_bps=costo, atr=a)
        cache[clave(c)] = r["retornos"]
    return cache


def clave(c: dict) -> tuple:
    return (c["periodo"], c["atr_drop"], c["close_pos"], c["stop_atr"], c["exigir_ambas"])


def metricas(rets: list[float], etiqueta: str = "") -> dict:
    trades = sum(1 for r in rets if r != 0.0)
    m = intradia.evaluar(rets, trades)
    t, p = scan.sharpe_pvalue(m["sharpe"] or 0.0, m["n"], 252.0)
    m["t_stat"], m["p_valor"] = round(t, 2), p
    if etiqueta:
        print(f"  {etiqueta:<38} Sharpe {(m['sharpe'] or 0):+.2f} (t={t:+.2f}) · "
              f"CAGR {m['cagr_pct']:+.2f}% · maxDD {m['max_drawdown_pct']:.1f}% · "
              f"PF {m['profit_factor']} · {m['trades']} trades")
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description="Optimización walk-forward del motor S")
    ap.add_argument("--symbol", default="^NDX")
    ap.add_argument("--riesgo", type=float, default=RIESGO_PCT)
    ap.add_argument("--costo-bps", type=float, default=COSTO_BPS)
    ap.add_argument("--repeticiones", type=int, default=200)
    ap.add_argument("--guardar", action="store_true")
    args = ap.parse_args()

    ohlc = bajar(args.symbol, ANIOS)
    n = len(ohlc)
    combos = optimizacion.grilla(ESPACIO)
    print(f"{args.symbol}: {n} sesiones ({n / 252:.1f} años) · riesgo {args.riesgo}% "
          f"· costo {args.costo_bps} bps")
    print(f"Grilla: {len(combos)} combinaciones "
          f"({' × '.join(f'{k}:{len(v)}' for k, v in ESPACIO.items())})")

    cache = construir_cache(ohlc, combos, args.riesgo, args.costo_bps)
    correr = lambda c, idx: [cache[clave(c)][i] for i in idx]   # noqa: E731

    # ---------- 1. La forma ingenua: optimizar sobre TODO ----------
    print(f"\n{'=' * 84}\n1. LA FORMA INGENUA — barrer los 20 años y quedarse con la mejor"
          f"\n{'=' * 84}")
    todos = range(n)
    puntajes = [(optimizacion.sharpe_por_periodo(cache[clave(c)]), c) for c in combos]
    puntajes.sort(key=lambda x: -x[0])
    mejor_global = puntajes[0][1]
    sharpes_probados = [s for s, _ in puntajes]
    print(f"  Mejor combinación en muestra: {mejor_global}")
    m_naive = metricas(correr(mejor_global, todos), "en muestra (los mismos 20 años)")
    m_def_full = metricas(correr(DEFECTO, todos), "parámetros por defecto del EA")

    dsr = optimizacion.sharpe_desinflado(correr(mejor_global, todos), sharpes_probados)
    print(f"\n  Sharpe desinflado (descuenta las {len(combos)} pruebas):")
    print(f"    Sharpe por período {dsr['sharpe_periodo']:.5f} · "
          f"máximo esperable por azar {dsr['sharpe_max_azar']:.5f}")
    print(f"    DSR = {dsr['dsr']:.4f}"
          + ("   <- sobrevive el descuento" if dsr["dsr"] > 0.95
             else "   <- NO sobrevive: el margen sobre el azar es chico"))

    # ---------- 2. La forma honesta: walk-forward ----------
    print(f"\n{'=' * 84}\n2. LA FORMA HONESTA — optimizar en 6 años, medir en los 2 "
          f"siguientes\n{'=' * 84}")
    wf = optimizacion.optimizar_walk_forward(n, combos, correr, TRAIN, TEST)
    idx_oos = [i for e in wf["elegidos"] for i in range(e["desde"], e["hasta"])]
    print(f"  {wf['n_ventanas']} ventanas · {len(idx_oos)} días fuera de muestra "
          f"({len(idx_oos) / 252:.1f} años)")
    m_oos = metricas(wf["retornos_oos"], "OPTIMIZADO fuera de muestra")
    m_def_oos = metricas(correr(DEFECTO, idx_oos), "defecto del EA, mismos días")

    delta = (m_oos["sharpe"] or 0) - (m_def_oos["sharpe"] or 0)
    print(f"\n  Ganancia de optimizar, fuera de muestra: {delta:+.3f} de Sharpe")
    print(f"  Caída del Sharpe entre muestra y fuera de muestra: "
          f"{(m_naive['sharpe'] or 0):.2f} -> {(m_oos['sharpe'] or 0):.2f} "
          f"({(m_oos['sharpe'] or 0) - (m_naive['sharpe'] or 0):+.2f})")

    # ---------- 3. Nulo: ¿le gana a elegir una combinación al azar? ----------
    rng = random.Random(20260830)
    sharpes_azar = []
    for _ in range(args.repeticiones):
        rets = []
        for e in wf["elegidos"]:
            c = rng.choice(combos)
            rets.extend(correr(c, range(e["desde"], e["hasta"])))
        mm = intradia.evaluar(rets, sum(1 for r in rets if r != 0))
        if mm["sharpe"] is not None:
            sharpes_azar.append(mm["sharpe"])
    sharpes_azar.sort()
    p_emp = (sum(1 for s in sharpes_azar if s >= (m_oos["sharpe"] or 0)) + 1) / \
            (len(sharpes_azar) + 1)
    print(f"\n  Nulo ({len(sharpes_azar)} corridas eligiendo una combinación AL AZAR en "
          f"cada ventana):")
    print(f"    media {sum(sharpes_azar) / len(sharpes_azar):+.2f} · "
          f"p05 {sharpes_azar[int(0.05 * len(sharpes_azar))]:+.2f} · "
          f"p95 {sharpes_azar[int(0.95 * len(sharpes_azar))]:+.2f}")
    print(f"    p EMPÍRICO del optimizado: {p_emp:.4f}"
          + ("   <- optimizar aporta" if p_emp < 0.05 else "   <- optimizar NO aporta"))

    # ---------- 4. ¿Elige siempre lo mismo? ----------
    est = optimizacion.estabilidad(wf["elegidos"])
    print("\n  Estabilidad de los parámetros elegidos ventana a ventana:")
    for k, d in est.items():
        print(f"    {k:<14} {str(d['valores']):<34} moda {d['moda']:<6} "
              f"({d['estabilidad_pct']}%)")

    # ---------- 5. Hipótesis dirigidas ----------
    # Dos parámetros salieron unánimes en las 6 ventanas de entrenamiento. Eso es una
    # hipótesis concreta y barata de testear, muy distinta de barrer 750 combinaciones:
    # se comparan seis variantes puntuales sobre el defecto, no un espacio entero.
    print(f"\n{'=' * 84}\n3. HIPÓTESIS DIRIGIDAS — cambiar UNA cosa por vez sobre el "
          f"defecto\n{'=' * 84}")
    variantes = [
        ("defecto del EA (SL 2 ATR, A o B)", dict(DEFECTO)),
        ("+ exigir AMBAS condiciones", dict(DEFECTO, exigir_ambas=True)),
        ("+ sin stop", dict(DEFECTO, stop_atr=0.0)),
        ("+ ambas Y sin stop", dict(DEFECTO, exigir_ambas=True, stop_atr=0.0)),
        ("+ ambas, stop ancho 3 ATR", dict(DEFECTO, exigir_ambas=True, stop_atr=3.0)),
    ]
    tabla = {}
    print(f"  {'variante':<38}{'Sharpe OOS':>11}{'Sharpe 20a':>11}{'maxDD':>8}"
          f"{'PF':>7}{'trades':>8}{'peor día':>10}")
    for nombre, c in variantes:
        r_oos, r_all = correr(c, idx_oos), correr(c, todos)
        m1 = intradia.evaluar(r_oos, sum(1 for x in r_oos if x != 0))
        m2 = intradia.evaluar(r_all, sum(1 for x in r_all if x != 0))
        tabla[nombre] = {"oos": m1, "completo": m2, "peor_dia_pct": round(min(r_all) * 100, 2)}
        print(f"  {nombre:<38}{(m1['sharpe'] or 0):>11.2f}{(m2['sharpe'] or 0):>11.2f}"
              f"{m2['max_drawdown_pct']:>7.1f}%{(m2['profit_factor'] or 0):>7.2f}"
              f"{m2['trades']:>8}{min(r_all) * 100:>9.2f}%")

    # ---------- 6. Recomendación ----------
    print(f"\n{'=' * 84}\n4. PARÁMETROS RECOMENDADOS\n{'=' * 84}")
    robusto = {k: (float(d["moda"]) if k != "exigir_ambas" and "." in d["moda"]
                   else int(d["moda"]) if k != "exigir_ambas"
                   else d["moda"] == "True")
               for k, d in est.items()}
    print(f"  Por moda de las ventanas: {robusto}")
    m_rob = metricas(correr(robusto, idx_oos), "moda, en los días fuera de muestra")
    m_rob_full = metricas(correr(robusto, todos), "moda, en los 20 años")

    res = {"corrido_utc": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
           "symbol": args.symbol, "riesgo_pct": args.riesgo, "costo_bps": args.costo_bps,
           "n_combos": len(combos), "train": TRAIN, "test": TEST,
           "mejor_en_muestra": {"params": mejor_global, "metricas": m_naive, "dsr": dsr},
           "defecto_en_muestra": m_def_full,
           "walk_forward": {"metricas": m_oos, "elegidos": wf["elegidos"],
                            "n_ventanas": wf["n_ventanas"],
                            "defecto_mismos_dias": m_def_oos,
                            "p_empirico_vs_azar": p_emp,
                            "nulo_azar": {"media": sum(sharpes_azar) / len(sharpes_azar),
                                          "n": len(sharpes_azar)}},
           "estabilidad": est, "variantes_dirigidas": tabla,
           "recomendado": {"params": robusto, "oos": m_rob, "completo": m_rob_full}}
    if args.guardar:
        os.makedirs(SALIDA, exist_ok=True)
        ruta = os.path.join(SALIDA, "optimizacion_motor_s.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\nGuardado en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
