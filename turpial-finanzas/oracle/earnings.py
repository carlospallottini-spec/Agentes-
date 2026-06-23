"""Estimación honesta de la próxima fecha de earnings desde patrones de EDGAR.

No hay API pública gratuita y confiable de calendarios de earnings. En vez de inventar
una fecha, la ESTIMAMOS a partir del historial real de filings 10-Q/10-K: las empresas
reportan en una cadencia trimestral estable (~91 días). Marcamos la estimación como tal.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from connectors import sec_edgar as sec


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def estimate_next_earnings(cik: str) -> dict:
    """Estima la próxima fecha de reporte a partir de los últimos filings periódicos."""
    filings = sec.recent_filings(cik, forms=("10-Q", "10-K"), limit=6)
    if len(filings) < 2:
        return {"status": "no_data", "reason": "Pocos filings periódicos para estimar."}

    dates = sorted({_parse(f["filed"]) for f in filings})
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    # Filtramos gaps absurdos (mezcla 10-K/10-Q) quedándonos con la mediana cercana a 91d.
    quarterly = [g for g in gaps if 60 <= g <= 130] or gaps
    quarterly.sort()
    median_gap = quarterly[len(quarterly) // 2]
    last = dates[-1]
    estimate = last + timedelta(days=median_gap)
    days_out = (estimate - date.today()).days
    # Si ya pasó, proyectamos al siguiente trimestre.
    while days_out < -7:
        estimate += timedelta(days=median_gap)
        days_out = (estimate - date.today()).days

    return {
        "status": "estimate",
        "next_earnings_est": estimate.isoformat(),
        "days_out": days_out,
        "cadence_days": median_gap,
        "last_filing": last.isoformat(),
        "nota": "Estimación basada en la cadencia histórica de filings, no en una fecha confirmada.",
    }


def is_pre_earnings_window(cik: str, lead_days: int = 7) -> bool:
    """True si la próxima earnings estimada cae dentro de la ventana de anticipación."""
    est = estimate_next_earnings(cik)
    if est.get("status") != "estimate":
        return False
    return 0 <= est["days_out"] <= lead_days
