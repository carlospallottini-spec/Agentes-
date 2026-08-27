"""CLI de Turpial Finanzas.

Uso:
  python turpial.py AAPL                 # genera dashboard (con narrativa si hay API key)
  python turpial.py AAPL --no-narrative  # solo score determinístico (sin Claude)
  python turpial.py --cadence diario     # corre una cadencia de la watchlist
  python turpial.py --pre-earnings       # escanea earnings próximos en la watchlist
  python turpial.py --quant KO           # Ornstein-Uhlenbeck + Markov + backtest
  python turpial.py --par EWA EWC        # cointegración y OU sobre el spread
"""
from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Turpial Finanzas — oráculo de riesgo")
    parser.add_argument("ticker", nargs="?", help="Ticker a analizar (ej. AAPL)")
    parser.add_argument("--no-narrative", action="store_true",
                        help="No usar Claude; solo el score determinístico")
    parser.add_argument("--cadence", choices=["diario", "semanal", "mensual"],
                        help="Correr una cadencia de la watchlist")
    parser.add_argument("--pre-earnings", action="store_true",
                        help="Escanear earnings próximos de la watchlist")
    parser.add_argument("--quant", action="store_true",
                        help="Análisis cuantitativo del ticker: OU, half-life, Markov y backtest")
    parser.add_argument("--par", nargs=2, metavar=("A", "B"),
                        help="Cointegración + OU sobre el spread de dos activos")
    parser.add_argument("--rango", default="5y",
                        choices=["6mo", "1y", "5y", "max"], help="Historial a usar (default 5y)")
    parser.add_argument("--ventana", type=int, default=250,
                        help="Ventana móvil de calibración del backtest (default 250)")
    parser.add_argument("--json", action="store_true", help="Salida cruda en JSON")
    args = parser.parse_args()

    from oracle import scheduler

    if args.par:
        return _print_par(args, args.json)
    if args.quant:
        if not args.ticker:
            print("Falta el ticker: python turpial.py --quant KO")
            return 1
        return _print_quant(args, args.json)
    if args.cadence:
        print(json.dumps(scheduler.run_cadence(args.cadence, not args.no_narrative),
                         ensure_ascii=False, indent=2, default=str))
        return 0
    if args.pre_earnings:
        print(json.dumps(scheduler.run_pre_earnings_scan(with_narrative=not args.no_narrative),
                         ensure_ascii=False, indent=2, default=str))
        return 0
    if not args.ticker:
        parser.print_help()
        return 1

    from agents.risk_score import analyze
    from dashboard.render import write_dashboard
    from oracle import store

    report = analyze(args.ticker, with_narrative=not args.no_narrative)
    if report.get("error"):
        print("Error:", report["error"])
        return 1
    path = write_dashboard(report)
    store.save_report(report, path)
    sc = report["score"]
    print(f"{report['company']} ({report['ticker']})")
    print(f"  Risk Score: {sc['overall_score']} · Banda: {sc['band']} · Cobertura: {sc['coverage']}%")
    print(f"  Dashboard: {path}")
    return 0


def _pct(v, signed: bool = True) -> str:
    if v is None:
        return "n/d"
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def _print_quant(args, as_json: bool) -> int:
    """Imprime el análisis Ornstein-Uhlenbeck + Markov + backtest de un activo."""
    from quant import engine

    rep = engine.analyze(args.ticker, rng=args.rango, ventana=args.ventana)
    if not rep.get("ok"):
        print("Error:", rep.get("motivo"))
        return 1
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 0

    ou_, mk = rep["ou"], rep["markov"]
    print(f"{rep['symbol']} · {rep['n_cierres']} cierres ({rep['rango']}) · "
          f"último {rep['precio_actual']}")
    print("\n── Ornstein-Uhlenbeck sobre el log-precio ──")
    if ou_["ok"]:
        print(f"  θ (reversión)   {ou_['theta']:.5f} por día")
        print(f"  μ (equilibrio)  {ou_['mu_precio']}  (log {ou_['mu_log']})")
        print(f"  σ / σ_eq        {ou_['sigma']:.5f} / {ou_['sigma_eq']:.5f}")
        print(f"  HALF-LIFE       {ou_['half_life_dias']:.1f} días   (τ = {ou_['tau_dias']:.1f})")
        print(f"  z-score actual  {ou_['z']:+.2f}")
        print(f"  Dickey-Fuller   {ou_['df_stat']:.2f} vs {ou_['df_criticos']['5%']} (5%) → "
              f"{'estacionaria' if ou_['estacionaria_5pct'] else 'NO estacionaria'}")
        cur = rep.get("curva_decaimiento", {})
        if cur.get("hitos"):
            print("  Curva de decaimiento (desviación restante):")
            for h in cur["hitos"]:
                print(f"    {h['half_lives']}× half-life → t={h['t']:>6.1f} d · "
                      f"{h['desvio_restante_pct']:>5.1f}% · precio esperado {h['precio_esperado']}")
    else:
        print("  sin calibración:", ou_.get("motivo"))

    if mk.get("ok"):
        print("\n── Régimen de Markov ──")
        print(f"  Estado actual: {mk['regimen_actual']} "
              f"(persistencia {mk['persistencia_actual']:.0%}, "
              f"duración media {mk['duracion_media'][mk['regimen_actual']]:.1f} barras)")
        print("  Matriz de transición P (filas = estado hoy):")
        print(f"    {'':>9}" + "".join(f"{e:>10}" for e in mk["estados"]))
        for e, fila in zip(mk["estados"], mk["matriz"]):
            print(f"    {e:>9}" + "".join(f"{v:>10.3f}" for v in fila))
        print("  Estacionaria π: " + ", ".join(f"{k} {v:.1%}" for k, v in mk["estacionaria"].items()))
        t = mk["test_memoria"]
        print(f"  χ² de memoria: {t['chi2']:.1f} (gl={t['df']}, p={t['p_valor']:.4f}) → "
              f"{'HAY memoria' if t['hay_memoria_5pct'] else 'sin memoria detectable'}")

    bt = rep.get("backtest", {})
    if bt.get("ok"):
        m, bh = bt["metricas"], bt["buy_and_hold"]
        print(f"\n── Backtest walk-forward ({bt['estrategia']}) ──")
        print(f"  {'':<18}{'estrategia':>12}{'buy & hold':>12}")
        for etiqueta, clave, signo in [("Retorno total", "retorno_total_pct", True),
                                       ("CAGR", "cagr_pct", True),
                                       ("Vol anual", "vol_anual_pct", False),
                                       ("Max drawdown", "max_drawdown_pct", False)]:
            print(f"  {etiqueta:<18}{_pct(m[clave], signo):>12}{_pct(bh[clave], signo):>12}")
        print(f"  {'Sharpe':<18}{str(m['sharpe']):>12}{str(bh['sharpe']):>12}")
        print(f"  Trades {m['trades']} · exposición {m['exposicion_pct']}% · "
              f"hit rate {m['hit_rate_pct']}% · bloqueos por régimen "
              f"{bt['señales_bloqueadas_por_regimen']}")
    elif bt:
        print("\n── Backtest ──\n  no corrió:", bt.get("motivo"))

    print("\n── Diagnóstico ──")
    print(" ", rep["diagnostico"])
    print("\nEsto es análisis cuantitativo, no asesoramiento de inversión.")
    return 0


def _print_par(args, as_json: bool) -> int:
    """Imprime la cointegración y el OU del spread de un par."""
    from quant import engine

    a, b = args.par
    rep = engine.analyze_pair(a, b, rng=args.rango, ventana=args.ventana)
    if not rep.get("ok"):
        print("Error:", rep.get("motivo"))
        return 1
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"{rep['par']} · {rep['n_fechas_comunes']} fechas en común ({rep['rango']})")
    print(f"  Hedge ratio β   {rep['hedge_ratio_beta']}  (spread = log A − β·log B − α)")
    print(f"  R² cointegr.    {rep['r2_cointegracion']} · correlación de logs "
          f"{rep['correlacion_logs']}")
    eg = rep["engle_granger"]
    print(f"  Engle-Granger   {eg['estadistico']} vs {eg['criticos']['5%']} (5%) → "
          f"{'COINTEGRADO' if eg['cointegrado_5pct'] else 'no cointegrado'}")
    o = rep["ou"]
    if o.get("ok"):
        print(f"  OU del spread   θ={o['theta']:.5f} · HALF-LIFE {o['half_life_dias']:.1f} días "
              f"· z={o['z']:+.2f}")
    bt = rep.get("backtest", {})
    if bt.get("ok"):
        m = bt["metricas"]
        print(f"  Backtest        retorno {_pct(m['retorno_total_pct'])} · Sharpe {m['sharpe']} "
              f"· maxDD {_pct(m['max_drawdown_pct'], False)} · {m['trades']} trades "
              f"· exposición {m['exposicion_pct']}%")
    print("\n  " + rep["veredicto"])
    print("\nEsto es análisis cuantitativo, no asesoramiento de inversión.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
