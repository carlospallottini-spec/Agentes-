"""Insiders reales vía SEC Form 4 (compras/ventas de directivos y >10% holders).

Esta es la fuente PRIMARIA y legal para actividad de insiders — el reemplazo honesto
de "insider screeners" de terceros. Form 3/4/5 se publican en EDGAR como XML.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from config import SEC_USER_AGENT
from connectors.sec_edgar import get_submissions

_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
_FORMS = ("3", "4", "5")


def recent_insider_filings(cik: str, limit: int = 15) -> list[dict]:
    """Lista los filings Form 3/4/5 recientes con metadata y URL al XML."""
    sub = get_submissions(cik)
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    out: list[dict] = []
    for i, form in enumerate(forms):
        if form not in _FORMS:
            continue
        acc = recent["accessionNumber"][i].replace("-", "")
        out.append({
            "form": form,
            "filed": recent["filingDate"][i],
            "accession": recent["accessionNumber"][i],
            "index_url": (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/"
            ),
        })
        if len(out) >= limit:
            break
    return out


def _parse_form4_xml(xml_text: str) -> dict | None:
    """Extrae nombre del insider y transacciones no derivadas (compra/venta)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    def text(path: str) -> str | None:
        el = root.find(path)
        return el.text.strip() if el is not None and el.text else None

    owner = text(".//reportingOwner/reportingOwnerId/rptOwnerName")
    txns = []
    for t in root.findall(".//nonDerivativeTransaction"):
        code = t.findtext(".//transactionCoding/transactionCode")
        shares = t.findtext(".//transactionAmounts/transactionShares/value")
        price = t.findtext(".//transactionAmounts/transactionPricePerShare/value")
        acq_disp = t.findtext(".//transactionAmounts/transactionAcquiredDisposedCode/value")
        txns.append({
            "code": code,            # P=compra abierta, S=venta, A=otorgamiento, etc.
            "shares": float(shares) if shares else None,
            "price": float(price) if price else None,
            "acquired_disposed": acq_disp,  # A=adquirido, D=dispuesto
        })
    if not owner and not txns:
        return None
    return {"owner": owner, "transactions": txns}


def insider_summary(cik: str, max_parse: int = 6) -> dict:
    """Resumen de actividad insider reciente. Parsea los primeros Form 4 disponibles.

    Devuelve buys/sells agregados (en USD aprox.) y el detalle parseado.
    """
    filings = recent_insider_filings(cik)
    parsed: list[dict] = []
    buys_usd = 0.0
    sells_usd = 0.0

    with httpx.Client(headers=_HEADERS, timeout=30.0, follow_redirects=True) as c:
        for f in [x for x in filings if x["form"] == "4"][:max_parse]:
            # El index lista los archivos; buscamos un .xml de form4.
            try:
                idx = c.get(f["index_url"]).text
            except httpx.HTTPError:
                continue
            xml_url = None
            for token in idx.split('"'):
                low = token.lower()
                if low.endswith(".xml") and "form4" in low:
                    # El index puede dar una ruta absoluta (/Archives/...) o un nombre suelto.
                    if token.startswith("http"):
                        xml_url = token
                    elif token.startswith("/"):
                        xml_url = "https://www.sec.gov" + token
                    else:
                        xml_url = f["index_url"] + token
                    break
            if not xml_url:
                continue
            try:
                xml_text = c.get(xml_url).text
            except httpx.HTTPError:
                continue
            doc = _parse_form4_xml(xml_text)
            if not doc:
                continue
            doc["filed"] = f["filed"]
            parsed.append(doc)
            for t in doc["transactions"]:
                if not (t["shares"] and t["price"]):
                    continue
                value = t["shares"] * t["price"]
                # Solo transacciones de mercado abierto: P=compra, S=venta. Se ignoran
                # M (ejercicio de opciones), F (retención por impuestos), A/G (otorgamiento/regalo),
                # que no reflejan convicción del insider.
                if t["code"] == "P":
                    buys_usd += value
                elif t["code"] == "S":
                    sells_usd += value

    net = buys_usd - sells_usd
    signal = "neutral"
    if net > 0 and buys_usd > sells_usd * 1.2:
        signal = "compra_neta"
    elif net < 0 and sells_usd > buys_usd * 1.2:
        signal = "venta_neta"

    return {
        "source": "sec_form4",
        "status": "ok" if parsed else "no_data",
        "filings_recientes": len(filings),
        "buys_usd_aprox": round(buys_usd, 2),
        "sells_usd_aprox": round(sells_usd, 2),
        "neto_usd_aprox": round(net, 2),
        "senal": signal,
        "detalle": parsed,
    }
