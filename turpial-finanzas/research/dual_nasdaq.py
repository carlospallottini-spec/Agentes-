"""Análisis de las dos estrategias del EA DualNasdaq, con el marco del repo.

Replica los motores S (SessionMarkov) y G (Gap-Fade), y los pasa por los mismos filtros
que el resto: Sharpe con error estándar de Lo, nulo por permutación, sensibilidad al
costo, desglose anual y régimen de VIX. Lo importante es el nulo: comprar en la apertura
y vender en el cierre del Nasdaq gana plata en días elegidos al azar, así que la pregunta
no es si el backtest da positivo sino si la señal le gana a tirar una moneda.

  python research/dual_nasdaq.py --guardar
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors import market  # noqa: E402
from quant import intradia, regimen_vol, scan  # noqa: E402

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
ANIOS = 20
COSTOS = [0.0, 1.0, 2.0, 5.0]
COSTO_BASE = 1.0
REPETICIONES = 500


def bajar(symbol: str, anios: int) -> list[dict]:
    h = market.velas(symbol, "1d", anios * 365)
    return [p for p in h.get("points", [])
            if p.get("c") and all(k in p for k in ("o", "h", "l")) and p["o"] > 0]


def _anual(rets, ohlc):
    grupos = {}
    for r, b in zip(rets, ohlc):
        grupos.setdefault(datetime.fromtimestamp(b["t"], tz=timezone.utc).year, []).append(r)
    out = {}
    for a, serie in grupos.items():
        if len(serie) < 60:
            continue
        m = intradia.evaluar(serie, sum(1 for x in serie if x != 0))
        out[a] = {"retorno_pct": m["retorno_total_pct"], "sharpe": m["sharpe"] or 0.0,
                  "trades": m["trades"]}
    return out


def analizar(nombre: str, ohlc: list[dict], mask: list[bool], simular, kw: dict,
             vix: tuple, repeticiones: int, universo: list[int] | None = None,
             mask_referencia: list[bool] | None = None,
             etiqueta_referencia: str = "comprar la apertura y vender el cierre TODOS los días") -> dict:
    print(f"\n{'=' * 82}\n{nombre}\n{'=' * 82}")

    base = simular(ohlc, mask, cost_bps=COSTO_BASE, **kw)
    m = intradia.evaluar(base["retornos"], base["trades"])
    anios = m["n"] / 252
    t, p = scan.sharpe_pvalue(m["sharpe"] or 0.0, m["n"], 252.0)

    print(f"  {m['trades']} operaciones en {anios:.1f} años "
          f"({m['trades'] / anios:.0f}/año, {m['dias_operados_pct']}% de los días)")
    print(f"  Retorno total {m['retorno_total_pct']:+.1f}% · CAGR {m['cagr_pct']:+.2f}% "
          f"· maxDD {m['max_drawdown_pct']:.1f}% · vol {m['vol_anual_pct']:.1f}%")
    print(f"  Sharpe {m['sharpe']:+.2f} · t={t:+.2f} · p={p:.4f} "
          f"· PF {m['profit_factor']} · aciertos {m['ganadores_pct']}% "
          f"· media/trade {m['retorno_medio_por_trade_bps']} bps")

    # --- El test que importa: ¿le gana a operar los mismos días al azar? ---
    nulo = intradia.nulo_por_permutacion(simular, ohlc, mask, repeticiones=repeticiones,
                                         universo=universo, cost_bps=COSTO_BASE, **kw)
    pe = intradia.p_empirico(m["sharpe"] or 0.0, nulo)
    donde = ("en días al azar CON hueco que califica" if universo is not None
             else "en días al azar")
    print(f"\n  Nulo por permutación ({nulo['n']} corridas, mismos {m['trades']} trades "
          f"{donde}):")
    print(f"    media {nulo['media']:+.2f} · p05 {nulo['p05']:+.2f} · p50 {nulo['p50']:+.2f} "
          f"· p95 {nulo['p95']:+.2f} · máx {nulo['max']:+.2f}")
    print(f"    p EMPÍRICO {pe:.4f}"
          + ("   <- la señal aporta" if pe < 0.05 else "   <- la señal NO aporta"))

    # --- Referencia: operar TODOS los días con el mismo dimensionamiento ---
    ref_mask = mask_referencia if mask_referencia is not None else [True] * len(ohlc)
    todos = simular(ohlc, ref_mask, cost_bps=COSTO_BASE, **kw)
    mt = intradia.evaluar(todos["retornos"], todos["trades"])
    print(f"\n  Referencia ({etiqueta_referencia}): "
          f"Sharpe {mt['sharpe']:+.2f} · {mt['trades']} trades "
          f"· media/trade {mt['retorno_medio_por_trade_bps']} bps")

    # --- Sensibilidad al costo ---
    print(f"\n  {'costo':>7}{'Sharpe':>9}{'CAGR':>9}{'maxDD':>8}{'PF':>7}{'media/trade':>13}")
    sens = {}
    for c in COSTOS:
        r = simular(ohlc, mask, cost_bps=c, **kw)
        mm = intradia.evaluar(r["retornos"], r["trades"])
        sens[str(c)] = {k: mm[k] for k in ("sharpe", "cagr_pct", "max_drawdown_pct",
                                           "profit_factor", "retorno_medio_por_trade_bps")}
        print(f"  {c:>6.1f}b{(mm['sharpe'] or 0):>9.2f}{mm['cagr_pct']:>8.2f}%"
              f"{mm['max_drawdown_pct']:>7.1f}%{(mm['profit_factor'] or 0):>7.2f}"
              f"{(mm['retorno_medio_por_trade_bps'] or 0):>10.2f} bps")

    # --- Régimen de VIX ---
    v = regimen_vol.alinear([b["t"] for b in ohlc], vix[0], vix[1])
    reg = regimen_vol.por_regimen([math.log(max(1 + r, 1e-9)) for r in base["retornos"]], v)
    dif = regimen_vol.diferencia_de_medias(
        [math.log(max(1 + r, 1e-9)) for r in base["retornos"]], v, "medio")
    print("\n  Por régimen de VIX:")
    for nom in regimen_vol.REGIMENES:
        rr = reg[nom]
        if not rr.get("suficiente"):
            continue
        print(f"    {nom + ' (' + reg['_bandas'][nom] + ')':<24}"
              f"{rr['pct_del_tiempo']:>7.1f}%{(rr['sharpe'] or 0):>8.2f}"
              f"{rr['media_diaria_bps']:>9.2f} bps/día")
    if dif.get("ok"):
        print(f"    VIX 17-21 vs resto: {dif['diferencia_bps']:+.3f} bps/día · "
              f"t={dif['t']:+.2f} · p={dif['p_valor']:.3f}")

    anual = _anual(base["retornos"], ohlc)
    peores = sorted(anual.items(), key=lambda kv: kv[1]["retorno_pct"])[:3]
    print("\n  Peores años: " + " · ".join(
        f"{a} {d['retorno_pct']:+.1f}%" for a, d in peores))

    return {"nombre": nombre, "metricas": m, "t_stat": round(t, 3), "p_parametrico": p,
            "nulo": {k: v2 for k, v2 in nulo.items() if k != "sharpes"},
            "p_empirico": pe, "referencia_todos_los_dias": mt,
            "sensibilidad_costo": sens, "regimen_vix": reg, "diferencia_medio": dif,
            "por_anio": anual}


def por_ventanas(ohlc, mS, mG) -> dict:
    """Las mismas estrategias sobre distintas ventanas de tiempo.

    El EA declara "validado MT5 8.5 años" y la nota del tester sugiere 2018-2026. Si un
    resultado aparece sólo dentro de la ventana en la que se ajustó, y desaparece antes,
    la validación era dentro de muestra. Es el chequeo más barato contra el sobreajuste.
    """
    anios = [datetime.fromtimestamp(b["t"], tz=timezone.utc).year for b in ohlc]
    ventanas = [("2006-2026 (todo)", 2006, 2026),
                ("2018-2026 (la del EA)", 2018, 2026),
                ("2006-2017 (fuera de esa muestra)", 2006, 2017)]
    print(f"\n{'=' * 82}\nPOR VENTANA DE TIEMPO\n{'=' * 82}")
    print(f"  {'ventana':<34}{'motor':>8}{'años':>7}{'trades':>8}{'Sharpe':>9}"
          f"{'CAGR':>9}{'maxDD':>8}{'PF':>7}")
    out = {}
    for etiqueta, a0, a1 in ventanas:
        idx = [i for i, a in enumerate(anios) if a0 <= a <= a1]
        if len(idx) < 300:
            continue
        sub = [ohlc[i] for i in idx]
        fila = {}
        for nombre, mask, sim, kw in (
                ("S", mS, intradia.simular_session_markov, {"riesgo_pct": 1.5, "stop_atr": 2.0}),
                ("G", mG, intradia.simular_gap_fade, {"riesgo_pct": 1.0})):
            r = sim(sub, [mask[i] for i in idx], cost_bps=COSTO_BASE, **kw)
            m = intradia.evaluar(r["retornos"], r["trades"])
            fila[nombre] = m
            print(f"  {etiqueta if nombre == 'S' else '':<34}{nombre:>8}"
                  f"{m['n'] / 252:>7.1f}{m['trades']:>8}{(m['sharpe'] or 0):>9.2f}"
                  f"{m['cagr_pct']:>8.2f}%{m['max_drawdown_pct']:>7.1f}%"
                  f"{(m['profit_factor'] or 0):>7.2f}")
        out[etiqueta] = fila
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Analiza las estrategias del EA DualNasdaq")
    ap.add_argument("--symbol", default="^NDX", help="^NDX (índice) o QQQ (ETF)")
    ap.add_argument("--anios", type=int, default=ANIOS)
    ap.add_argument("--repeticiones", type=int, default=REPETICIONES)
    ap.add_argument("--guardar", action="store_true")
    args = ap.parse_args()

    ohlc = bajar(args.symbol, args.anios)
    hv = market.velas("^VIX", "1d", args.anios * 365)
    pv = [p for p in hv["points"] if p.get("c") and p["c"] > 0]
    vix = ([p["t"] for p in pv], [p["c"] for p in pv])
    d0 = datetime.fromtimestamp(ohlc[0]["t"], tz=timezone.utc).date()
    d1 = datetime.fromtimestamp(ohlc[-1]["t"], tz=timezone.utc).date()
    print(f"{args.symbol}: {len(ohlc)} sesiones diarias, {d0} .. {d1} "
          f"({len(ohlc) / 252:.1f} años)")
    print(f"Listón de significancia: con {len(ohlc) / 252:.0f} años hace falta "
          f"Sharpe >= {2 / (len(ohlc) / 252 - 2) ** 0.5:.2f} para t=2.")

    mS = intradia.señal_session_markov(ohlc)
    mG = intradia.señal_gap_fade(ohlc)
    bloques = [
        analizar("MOTOR S — SessionMarkov (compra si ayer cayó >1 ATR o cerró en el 20% bajo)",
                 ohlc, mS, intradia.simular_session_markov,
                 {"riesgo_pct": 1.5, "stop_atr": 2.0}, vix, args.repeticiones),
        analizar("MOTOR G — Gap-Fade (hueco bajista 0.3-2% en tendencia alcista)",
                 ohlc, mG, intradia.simular_gap_fade, {"riesgo_pct": 1.0},
                 vix, args.repeticiones,
                 universo=intradia.universo_gaps(ohlc),
                 mask_referencia=[i in set(intradia.universo_gaps(ohlc))
                                  for i in range(len(ohlc))],
                 etiqueta_referencia="operar TODOS los huecos que califican, sin filtro de tendencia"),
    ]

    # --- Cartera: los dos motores juntos ---
    rS = intradia.simular_session_markov(ohlc, mS, cost_bps=COSTO_BASE,
                                         riesgo_pct=1.5, stop_atr=2.0)["retornos"]
    rG = intradia.simular_gap_fade(ohlc, mG, cost_bps=COSTO_BASE, riesgo_pct=1.0)["retornos"]
    comb = [a + b for a, b in zip(rS, rG)]
    ops = sum(1 for a, b in zip(rS, rG) if a != 0 or b != 0)
    mc = intradia.evaluar(comb, ops)
    tc, pc = scan.sharpe_pvalue(mc["sharpe"] or 0.0, mc["n"], 252.0)
    coincide = sum(1 for a, b in zip(rS, rG) if a != 0 and b != 0)
    solo_s = sum(1 for a, b in zip(rS, rG) if a != 0 and b == 0)
    solo_g = sum(1 for a, b in zip(rS, rG) if a == 0 and b != 0)
    print(f"\n{'=' * 82}\nCARTERA — los dos motores juntos\n{'=' * 82}")
    print(f"  {ops} días con operación · sólo S {solo_s} · sólo G {solo_g} · "
          f"coinciden {coincide} ({100 * coincide / max(ops, 1):.0f}%)")
    print(f"  Sharpe {mc['sharpe']:+.2f} (t={tc:+.2f}, p={pc:.4f}) · "
          f"CAGR {mc['cagr_pct']:+.2f}% · maxDD {mc['max_drawdown_pct']:.1f}% "
          f"· PF {mc['profit_factor']}")

    ventanas = por_ventanas(ohlc, mS, mG)

    # --- La incertidumbre que la barra diaria no puede cerrar ---
    amb = intradia.dias_ambiguos(ohlc, mG)
    print(f"\n{'=' * 82}\nCUÁNTO DEPENDE EL MOTOR G DE UN SUPUESTO QUE NO PUEDO RESOLVER"
          f"\n{'=' * 82}")
    print(f"  Días de señal que tocan el stop Y el objetivo: {amb['ambiguos']}/{amb['total']} "
          f"({amb['pct']}%). Con barras diarias no se sabe cuál ocurrió primero.")
    ambig = {}
    for sup in ("stop", "objetivo"):
        r = intradia.simular_gap_fade(ohlc, mG, cost_bps=COSTO_BASE, ambiguo=sup)
        m = intradia.evaluar(r["retornos"], r["trades"])
        ambig[sup] = m
        etiqueta = ("conservador: se asume el stop" if sup == "stop"
                    else "optimista: se asume el objetivo")
        print(f"  {etiqueta:<36} Sharpe {(m['sharpe'] or 0):+.2f} · PF {m['profit_factor']} "
              f"· CAGR {m['cagr_pct']:+.2f}% · aciertos {m['ganadores_pct']}%")
    print(f"  Ese {amb['pct']}% de días decide el signo del resultado. Mi réplica con velas"
          f" diarias NO puede zanjarlo;\n  un backtest con ticks reales sí, y es la"
          f" herramienta correcta para esta estrategia.")

    res = {"corrido_utc": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
           "ventanas": ventanas, "ambiguedad": {"conteo": amb, "resultados": ambig},
           "symbol": args.symbol, "sesiones": len(ohlc), "costo_base_bps": COSTO_BASE,
           "bloques": bloques,
           "cartera": {"metricas": mc, "t_stat": round(tc, 3), "p_parametrico": pc,
                       "solo_s": solo_s, "solo_g": solo_g, "coinciden": coincide}}
    if args.guardar:
        os.makedirs(SALIDA, exist_ok=True)
        ruta = os.path.join(SALIDA, f"dual_nasdaq_{args.symbol.replace('^', '')}.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\nGuardado en {ruta}")
    return 0


import math  # noqa: E402  (lo usa `analizar` para pasar a log-retornos)

if __name__ == "__main__":
    raise SystemExit(main())
