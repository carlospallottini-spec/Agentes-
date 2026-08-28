"""Control positivo: ¿la maquinaria encontraría un edge si existiera?

Todo el repo dice "no hay reversión a la media operable". Esa afirmación sólo vale si el
motor sería capaz de detectar un efecto real cuando está presente. Este experimento lo
pone a prueba, en cuatro etapas y con la misma disciplina del resto (parámetros fijos,
nulo empírico, corrección por multiplicidad):

  0. META-CONTROL — momentum inyectado en datos sintéticos. Si acá no lo detecta, el
     motor está roto y ningún resultado negativo significa nada.
  1. CONTROL POSITIVO — los dos momentums mejor documentados de la literatura sobre datos
     reales: cross-sectional 12-1 (Jegadeesh & Titman, 1993) y time-series 12m
     (Moskowitz, Ooi & Pedersen, 2012).
  2. CONTROL NEGATIVO — la estrategia de Ornstein-Uhlenbeck sobre los mismos datos.
  3. RÉGIMEN — todo condicionado por VIX, con la banda 17-21 como foco.

El nulo es por permutación: la misma mecánica con la señal barajada, cientos de veces.
Preserva fechas, costos y covarianzas, y no asume normalidad.

  python research/control_positivo.py --guardar
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors import market  # noqa: E402
from quant import backtest, momentum, regimen_vol, scan  # noqa: E402
from quant.backtest import metrics  # noqa: E402

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")

ANIOS = 20
COSTO_BPS = 5.0
REPETICIONES = 200
VIX_BAJO, VIX_ALTO = 17.0, 21.0

# Universo amplio para el momentum cross-sectional. Sesgo de supervivencia declarado:
# son 40 empresas que existían hace 20 años y siguen cotizando. El sesgo empuja los
# resultados HACIA ARRIBA, así que un resultado negativo acá es más fuerte, no más débil.
ACCIONES = ["AAPL", "MSFT", "JNJ", "XOM", "JPM", "PG", "KO", "PFE", "WMT", "HD",
            "INTC", "CSCO", "VZ", "T", "MRK", "PEP", "ORCL", "IBM", "MCD", "NKE",
            "CAT", "BA", "MMM", "DIS", "C", "BAC", "WFC", "CVX", "UNH", "AXP",
            "GS", "LOW", "TGT", "COST", "SBUX", "QCOM", "TXN", "AMGN", "GILD", "ADBE"]
SECTORES = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB"]
CLASES = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ", "IWM"]


def bajar(simbolos: list[str], minimo: int = 4500) -> dict[str, list[dict]]:
    out = {}
    for s in simbolos:
        h = market.velas(s, "1d", ANIOS * 365)
        pts = [p for p in h.get("points", []) if p.get("c") and p["c"] > 0]
        if len(pts) >= minimo:
            out[s] = pts
        else:
            print(f"    aviso: {s} sólo trajo {len(pts)} barras; se excluye")
        time.sleep(0.2)
    return out


# ------------------------------------------------------------------ meta-control
def meta_control(repeticiones: int) -> dict:
    print("\n" + "=" * 78)
    print("0. META-CONTROL — momentum inyectado en datos sintéticos")
    print("   Si el motor no ve un efecto puesto a mano, nada de lo demás significa nada.")
    filas = []
    for n_act in (9, 20, 40):
        f, p = momentum.simular_universo(n_activos=n_act, persistencia=2000, semilla=5)
        xs = momentum.cross_sectional(f, p, cost_bps=0.0)
        nulo = momentum.nulo_por_permutacion(momentum.cross_sectional, f, p,
                                             repeticiones=min(repeticiones, 100),
                                             cost_bps=0.0)
        pe = momentum.p_empirico(xs["metricas"]["sharpe"], nulo)
        filas.append({"n_activos": n_act, "sharpe": xs["metricas"]["sharpe"],
                      "nulo_p95": nulo["p95"], "p_empirico": pe})
        print(f"   {n_act:>2} activos sintéticos -> Sharpe {xs['metricas']['sharpe']:+.2f} "
              f"· nulo p95 {nulo['p95']:+.2f} · p empírico {pe:.3f}"
              + ("   DETECTA" if pe < 0.05 else "   no detecta"))
    return {"filas": filas, "detecta": all(f["p_empirico"] < 0.05 for f in filas)}


# --------------------------------------------------------------------- evaluación
def evaluar(nombre: str, res: dict, nulo: dict | None, vix_fechas, vix_vals,
            anual: bool = False) -> dict:
    m = res["metricas"]
    sh = m["sharpe"] or 0.0
    t, p_param = scan.sharpe_pvalue(sh, m["n"], 252.0)
    p_emp = momentum.p_empirico(sh, nulo) if nulo else None

    print(f"\n--- {nombre} ---")
    print(f"  {res['estrategia']} · {res['parametros']['n_activos']} activos · "
          f"{m['n']} días ({m['n'] / 252:.1f} años) · {res['rebalanceos']} rebalanceos "
          f"· turnover medio {res['turnover_medio']}")
    print(f"  Sharpe {sh:+.2f} · retorno {m['retorno_total_pct']:+.1f}% · "
          f"maxDD {m['max_drawdown_pct']:.1f}% · vol {m['vol_anual_pct']:.1f}%")
    print(f"  t paramétrico (Lo 2002): {t:+.2f} (p={p_param:.4f})")
    if nulo:
        print(f"  Nulo barajado ({nulo['n']} corridas): media {nulo['media']:+.2f} · "
              f"p95 {nulo['p95']:+.2f} · máx {nulo['max']:+.2f}")
        print(f"  p EMPÍRICO: {p_emp:.4f}"
              + ("   <- se distingue del ruido" if p_emp < 0.05
                 else "   <- NO se distingue del ruido"))

    por_anio = _anual(res["retornos"], res["fechas_senal"]) if anual else None
    if por_anio:
        print("  Por año:")
        for a, d in sorted(por_anio.items()):
            marca = "   <-- crash de momentum documentado" if a == 2009 else ""
            print(f"    {a}  {d['retorno_pct']:>7.1f}%  Sharpe {d['sharpe']:>6.2f}{marca}")

    vix = regimen_vol.alinear(res["fechas_senal"], vix_fechas, vix_vals)
    reg = regimen_vol.por_regimen(res["retornos"], vix, VIX_BAJO, VIX_ALTO)
    dif = regimen_vol.diferencia_de_medias(res["retornos"], vix, "medio", VIX_BAJO, VIX_ALTO)
    _imprimir_regimen(reg, dif)

    return {"nombre": nombre, "estrategia": res["estrategia"],
            "parametros": res.get("parametros"), "metricas": m,
            "t_parametrico": round(t, 3), "p_parametrico": p_param,
            "nulo": {k: v for k, v in nulo.items() if k != "sharpes"} if nulo else None,
            "p_empirico": p_emp, "por_anio": por_anio,
            "regimen_vix": reg, "diferencia_medio": dif}


def _anual(rets: list[float], fechas: list[int]) -> dict:
    grupos: dict[int, list[float]] = {}
    for r, t in zip(rets, fechas):
        grupos.setdefault(datetime.fromtimestamp(t, tz=timezone.utc).year, []).append(r)
    out = {}
    for a, serie in grupos.items():
        if len(serie) < 60:
            continue
        m = metrics(serie, None, 0, 252)
        out[a] = {"dias": len(serie), "retorno_pct": m["retorno_total_pct"],
                  "sharpe": m["sharpe"] or 0.0}
    return out


def _imprimir_regimen(reg: dict, dif: dict) -> None:
    print("  Por régimen de VIX:")
    print(f"    {'régimen':<24}{'% tiempo':>10}{'días':>8}{'Sharpe':>9}{'bps/día':>10}")
    for nombre in regimen_vol.REGIMENES:
        r = reg[nombre]
        etiqueta = f"{nombre} ({reg['_bandas'][nombre]})"
        if not r.get("suficiente"):
            print(f"    {etiqueta:<24}{r['pct_del_tiempo']:>9.1f}%{r['n']:>8}   sin datos")
            continue
        print(f"    {etiqueta:<24}{r['pct_del_tiempo']:>9.1f}%{r['n']:>8}"
              f"{(r['sharpe'] or 0):>9.2f}{r['media_diaria_bps']:>10.2f}")
    if dif.get("ok"):
        print(f"    VIX {VIX_BAJO:.0f}-{VIX_ALTO:.0f} vs resto: {dif['diferencia_bps']:+.3f} "
              f"bps/día · t={dif['t']:+.2f} · p={dif['p_valor']:.3f}"
              + ("  <- significativa" if dif["significativa_5pct"] else "  <- no significativa"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Control positivo con momentum y régimen de VIX")
    ap.add_argument("--guardar", action="store_true")
    ap.add_argument("--repeticiones", type=int, default=REPETICIONES)
    ap.add_argument("--costo-bps", type=float, default=COSTO_BPS)
    args = ap.parse_args()

    meta = meta_control(args.repeticiones)

    print("\n" + "=" * 78)
    print(f"Bajando {ANIOS} años de datos diarios…")
    h_vix = market.velas("^VIX", "1d", ANIOS * 365)
    vix_pts = [p for p in h_vix["points"] if p.get("c") and p["c"] > 0]
    vix_fechas = [p["t"] for p in vix_pts]
    vix_vals = [p["c"] for p in vix_pts]
    en_banda = sum(1 for v in vix_vals if VIX_BAJO <= v <= VIX_ALTO)
    pct_banda = round(100 * en_banda / len(vix_vals), 1)
    print(f"  VIX: {len(vix_pts)} días · mediana {sorted(vix_vals)[len(vix_vals) // 2]:.1f}")
    print(f"  La banda {VIX_BAJO:.0f}-{VIX_ALTO:.0f} ocupa el {pct_banda}% del período")

    print("  Bajando acciones…")
    acc = bajar(ACCIONES)
    print("  Bajando sectores y clases de activo…")
    sec = bajar(SECTORES)
    cla = bajar(CLASES)

    f_acc, p_acc = momentum.alinear(acc)
    f_sec, p_sec = momentum.alinear(sec)
    f_cla, p_cla = momentum.alinear(cla)
    print(f"  Acciones: {len(p_acc)} · {len(f_acc)} fechas comunes ({len(f_acc)/252:.1f} años)")
    print(f"  Sectores: {len(p_sec)} · Clases: {len(p_cla)}")

    print("\n" + "=" * 78)
    print("1. CONTROL POSITIVO — momentum documentado, sobre datos reales")
    bloques = []

    for etiqueta, fechas, precios, fn, anual in [
        ("Cross-sectional 12-1 · 40 acciones", f_acc, p_acc, momentum.cross_sectional, True),
        ("Cross-sectional 12-1 · 9 sectores", f_sec, p_sec, momentum.cross_sectional, False),
        ("Time-series 12m · 9 clases de activo", f_cla, p_cla, momentum.time_series, False),
    ]:
        if len(precios) < 3:
            continue
        res = fn(fechas, precios, cost_bps=args.costo_bps)
        nulo = momentum.nulo_por_permutacion(fn, fechas, precios,
                                             repeticiones=args.repeticiones,
                                             cost_bps=args.costo_bps)
        bloques.append(evaluar(etiqueta, res, nulo, vix_fechas, vix_vals, anual=anual))

    print("\n" + "=" * 78)
    print("2. CONTROL NEGATIVO — reversión a la media (Ornstein-Uhlenbeck)")
    spy = p_cla.get("SPY")
    if spy:
        for gate in (False, True):
            bt = backtest.walk_forward(spy, ventana=250, cost_bps=args.costo_bps,
                                       exigir_estacionaria=gate, periodos_por_anio=252)
            if not bt.get("ok"):
                continue
            m = bt["metricas"]
            sh = m["sharpe"] or 0.0
            t, p = scan.sharpe_pvalue(sh, m["n"], 252.0)
            print(f"\n--- OU sobre SPY diario · gate {'ON' if gate else 'off'} ---")
            print(f"  Sharpe {sh:+.2f} (t={t:+.2f}, p={p:.3f}) · "
                  f"retorno {m['retorno_total_pct']:+.1f}% · {m['trades']} trades · "
                  f"exposición {m['exposicion_pct']}%")
            fr = f_cla[bt["primera_barra"]: bt["primera_barra"] + len(bt["retornos"])]
            vix = regimen_vol.alinear(fr, vix_fechas, vix_vals)
            reg = regimen_vol.por_regimen(bt["retornos"], vix, VIX_BAJO, VIX_ALTO)
            dif = regimen_vol.diferencia_de_medias(bt["retornos"], vix, "medio",
                                                   VIX_BAJO, VIX_ALTO)
            _imprimir_regimen(reg, dif)
            bloques.append({"nombre": f"OU SPY (gate {'ON' if gate else 'off'})",
                            "estrategia": bt["estrategia"], "metricas": m,
                            "t_parametrico": round(t, 3), "p_parametrico": p,
                            "p_empirico": None, "regimen_vix": reg,
                            "diferencia_medio": dif})

    print("\n" + "=" * 78)
    print("VEREDICTO")
    print(f"  Meta-control (efecto inyectado): "
          f"{'EL MOTOR LO DETECTA' if meta['detecta'] else 'EL MOTOR NO LO DETECTA'}")
    for b in bloques:
        pe = b.get("p_empirico")
        if pe is None:
            marca = "—"
            extra = f"p paramétrico {b['p_parametrico']:.3f}"
        else:
            marca = "DETECTA" if pe < 0.05 else "no detecta"
            extra = f"p empírico {pe:.4f}"
        print(f"  {marca:<12} {b['nombre']:<40} Sharpe "
              f"{(b['metricas']['sharpe'] or 0):+.2f} · {extra}")

    res = {"corrido_utc": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
           "anios": ANIOS, "costo_bps": args.costo_bps,
           "repeticiones_nulo": args.repeticiones,
           "bandas_vix": {"bajo": VIX_BAJO, "alto": VIX_ALTO},
           "pct_tiempo_en_banda": pct_banda,
           "meta_control": meta, "bloques": bloques}
    if args.guardar:
        os.makedirs(SALIDA, exist_ok=True)
        ruta = os.path.join(SALIDA, "control_positivo.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\nGuardado en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
