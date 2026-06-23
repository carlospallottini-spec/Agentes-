"""CLI de Turpial Finanzas.

Uso:
  python turpial.py AAPL                 # genera dashboard (con narrativa si hay API key)
  python turpial.py AAPL --no-narrative  # solo score determinístico (sin Claude)
  python turpial.py --cadence diario     # corre una cadencia de la watchlist
  python turpial.py --pre-earnings       # escanea earnings próximos en la watchlist
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
    args = parser.parse_args()

    from oracle import scheduler

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


if __name__ == "__main__":
    raise SystemExit(main())
