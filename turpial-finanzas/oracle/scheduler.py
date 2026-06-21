"""El oráculo: corre los agentes en cadencia diaria/semanal/mensual y pre-earnings.

No usa un loop infinito propio: expone funciones que dispara un cron externo
(Railway Cron, GitHub Actions o `python -m oracle.scheduler <cadencia>`). Así el
servicio web queda liviano y la cadencia es responsabilidad del orquestador.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from agents.risk_score import analyze
from config import WATCHLIST_PATH
from connectors import sec_edgar as sec
from dashboard.render import write_dashboard
from oracle import store
from oracle.earnings import estimate_next_earnings, is_pre_earnings_window


def load_watchlist() -> dict:
    if WATCHLIST_PATH.exists():
        return json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    return {"diario": [], "semanal": [], "mensual": []}


def _run_one(ticker: str, reason: str, with_narrative: bool) -> dict:
    report = analyze(ticker, with_narrative=with_narrative)
    if report.get("error"):
        return {"ticker": ticker, "ok": False, "error": report["error"]}
    report["run_reason"] = reason
    html_path = write_dashboard(report)
    entry = store.save_report(report, html_path)
    return {"ticker": ticker, "ok": True, "reason": reason, **entry}


def run_cadence(cadence: str, with_narrative: bool = True) -> list[dict]:
    """Corre todos los tickers de una cadencia ('diario'|'semanal'|'mensual')."""
    wl = load_watchlist()
    tickers = wl.get(cadence, [])
    results = []
    for t in tickers:
        try:
            results.append(_run_one(t, f"cadencia:{cadence}", with_narrative))
        except Exception as e:
            results.append({"ticker": t, "ok": False, "error": str(e)})
    return results


def run_pre_earnings_scan(lead_days: int = 7, with_narrative: bool = True) -> list[dict]:
    """Escanea toda la watchlist y genera reportes para los que reportan pronto."""
    wl = load_watchlist()
    universe = sorted({t for lst in wl.values() for t in lst})
    results = []
    for t in universe:
        cik = sec.ticker_to_cik(t)
        if not cik:
            continue
        try:
            if is_pre_earnings_window(cik, lead_days):
                est = estimate_next_earnings(cik)
                res = _run_one(t, f"pre-earnings:~{est.get('next_earnings_est')}", with_narrative)
                res["earnings"] = est
                results.append(res)
        except Exception as e:
            results.append({"ticker": t, "ok": False, "error": str(e)})
    return results


def _main(argv: list[str]) -> int:
    cadence = argv[1] if len(argv) > 1 else "diario"
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if cadence == "pre-earnings":
        out = run_pre_earnings_scan()
    else:
        out = run_cadence(cadence)
    print(json.dumps({"started": started, "cadence": cadence, "results": out},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv))
