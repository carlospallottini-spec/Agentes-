"""Agente de Risk Score — orquesta datos primarios, score y narrativa de Claude."""
from __future__ import annotations

from datetime import datetime, timezone

from agents.base import build_client, run_single_tool, to_json
from agents.prompts import EMITIR_ANALISIS_TOOL, RISK_ANALYST_SYSTEM
from agents.scoring import compute_risk_score
from connectors import insiders, prices
from connectors import sec_edgar as sec


def gather_data(ticker: str) -> dict:
    """Reúne todos los datos primarios para un ticker. Falla con claridad si no hay CIK."""
    cik = sec.ticker_to_cik(ticker)
    if not cik:
        return {"ticker": ticker.upper(), "error": f"No se encontró el ticker {ticker} en EDGAR."}

    facts = sec.get_company_facts(cik)
    sub = sec.get_submissions(cik)
    price = prices.current_price(ticker)
    filings = sec.recent_filings(cik)
    score = compute_risk_score(facts, price["price"] if price else None)
    try:
        insider = insiders.insider_summary(cik)
    except Exception as e:  # la actividad insider es best-effort
        insider = {"source": "sec_form4", "status": "error", "reason": str(e)}

    return {
        "ticker": ticker.upper(),
        "cik": cik,
        "company": sub.get("name"),
        "sic_description": sub.get("sicDescription"),
        "exchange": (sub.get("exchanges") or [None])[0],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "price": price,
        "filings": filings,
        "insiders": insider,
        "score": score,
    }


def analyze(ticker: str, with_narrative: bool = True) -> dict:
    """Genera el reporte de riesgo completo. Si with_narrative, usa Claude para la historia."""
    data = gather_data(ticker)
    if data.get("error"):
        return data
    if not with_narrative:
        data["narrative"] = None
        return data

    client = build_client()
    user_content = (
        f"Analizá el riesgo de {data['company']} ({data['ticker']}). "
        "Acá están los datos primarios y el score determinístico ya calculado. "
        "Interpretá, ajustá badges si corresponde y completá la narrativa:\n\n"
        + to_json({
            "empresa": data["company"],
            "sector": data["sic_description"],
            "precio": data["price"],
            "filings_recientes": data["filings"][:5],
            "insiders_form4": data["insiders"],
            "score": data["score"],
        })
    )
    data["narrative"] = run_single_tool(
        client, RISK_ANALYST_SYSTEM, user_content, EMITIR_ANALISIS_TOOL
    )
    return data
