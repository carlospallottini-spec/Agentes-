"""Conector a SEC EDGAR — la fuente PRIMARIA y real del oráculo.

EDGAR es 100% público y gratuito (sin API key). Cubre:
  - Mapeo ticker -> CIK
  - Filings recientes (10-Q, 10-K, 8-K) con links al documento
  - Fundamentales XBRL (companyfacts): ingresos, utilidad, balance, EPS, etc.
  - Insiders vía Form 4 (compras/ventas de directivos) — el reemplazo honesto y
    primario de "insider screeners" de terceros.

La SEC exige un header User-Agent con un contacto real (ver config.SEC_USER_AGENT).
"""
from __future__ import annotations

import httpx

from config import SEC_USER_AGENT

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}

_ticker_cache: dict[str, str] | None = None


def _client() -> httpx.Client:
    return httpx.Client(headers=_HEADERS, timeout=30.0, follow_redirects=True)


def ticker_to_cik(ticker: str) -> str | None:
    """Devuelve el CIK de 10 dígitos (zero-padded) para un ticker, o None."""
    global _ticker_cache
    if _ticker_cache is None:
        with _client() as c:
            data = c.get(_TICKERS_URL).json()
        _ticker_cache = {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10)
            for row in data.values()
        }
    return _ticker_cache.get(ticker.upper())


def get_submissions(cik: str) -> dict:
    """Metadata de la entidad + lista de filings recientes."""
    with _client() as c:
        return c.get(_SUBMISSIONS_URL.format(cik=cik)).json()


def recent_filings(cik: str, forms: tuple[str, ...] = ("10-Q", "10-K", "8-K"),
                   limit: int = 8) -> list[dict]:
    """Lista filings recientes filtrados por tipo, con URL al índice del filing."""
    sub = get_submissions(cik)
    recent = sub.get("filings", {}).get("recent", {})
    out: list[dict] = []
    accession = recent.get("accessionNumber", [])
    for i in range(len(accession)):
        form = recent["form"][i]
        if form not in forms:
            continue
        acc = accession[i].replace("-", "")
        out.append({
            "form": form,
            "filed": recent["filingDate"][i],
            "report_date": recent.get("reportDate", [None] * len(accession))[i],
            "primary_doc": recent.get("primaryDocument", [""] * len(accession))[i],
            "url": (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/"
                f"{recent.get('primaryDocument', [''] * len(accession))[i]}"
            ),
        })
        if len(out) >= limit:
            break
    return out


def get_company_facts(cik: str) -> dict:
    """Descarga los fundamentales XBRL completos de la empresa."""
    with _client() as c:
        return c.get(_FACTS_URL.format(cik=cik)).json()


def _concept_series(facts: dict, concept: str, unit: str = "USD") -> list[dict]:
    """Extrae la serie temporal de un concepto US-GAAP, ordenada por fecha de fin."""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"][unit]
    except KeyError:
        return []
    # Preferimos datos anuales con frame definido; ordenamos por 'end'.
    rows = [r for r in units if r.get("end")]
    rows.sort(key=lambda r: r["end"])
    return rows


def latest_annual(facts: dict, concept: str, unit: str = "USD") -> float | None:
    """Último valor anual (form 10-K, fp=FY) de un concepto, o el más reciente."""
    rows = _concept_series(facts, concept, unit)
    annual = [r for r in rows if r.get("form") == "10-K" and r.get("fp") == "FY"]
    pick = annual or rows
    return float(pick[-1]["val"]) if pick else None


def annual_series(facts: dict, concept: str, unit: str = "USD", years: int = 5) -> list[float]:
    """Serie de valores anuales (FY) más recientes para calcular crecimiento."""
    rows = _concept_series(facts, concept, unit)
    annual = [r for r in rows if r.get("form") == "10-K" and r.get("fp") == "FY"]
    # Deduplicar por año fiscal manteniendo el último reportado.
    by_year: dict[int, float] = {}
    for r in annual:
        if r.get("fy"):
            by_year[r["fy"]] = float(r["val"])
    ordered = [by_year[y] for y in sorted(by_year)]
    return ordered[-years:]


def first_available(facts: dict, concepts: list[str], unit: str = "USD") -> float | None:
    """Devuelve el primer concepto con dato (los nombres XBRL varían por empresa)."""
    for c in concepts:
        v = latest_annual(facts, c, unit)
        if v is not None:
            return v
    return None
