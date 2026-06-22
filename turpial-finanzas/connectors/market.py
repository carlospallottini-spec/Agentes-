"""Conector de mercado universal — un solo feed gratuito (Yahoo) para TODO activo.

Cubre, con la misma interfaz, todas las clases de activo que pide la plataforma:
acciones, ETFs, bonos (yields), crypto, Forex, commodities/futuros e índices.

  search(q)              -> autocompletado universal multi-activo
  quote(symbol)          -> precio actual + variación + moneda + clase de activo
  history(symbol, range) -> serie para graficar
  asset_class(quoteType) -> etiqueta didáctica en español
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

_UA = {"User-Agent": "Mozilla/5.0 (Turpial Finanzas)"}
_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"

# quoteType de Yahoo -> etiqueta didáctica.
_CLASS = {
    "EQUITY": "Acción",
    "ETF": "ETF",
    "MUTUALFUND": "Fondo",
    "CRYPTOCURRENCY": "Crypto",
    "CURRENCY": "Forex",
    "FUTURE": "Commodity / Futuro",
    "INDEX": "Índice",
    "BOND": "Bono",
    "OPTION": "Opción",
}

# Rangos válidos -> intervalo de velas adecuado.
_RANGE_INTERVAL = {
    "1d": "5m", "5d": "30m", "1mo": "1d", "6mo": "1d",
    "1y": "1d", "5y": "1wk", "max": "1mo",
}


def asset_class(quote_type: str | None) -> str:
    return _CLASS.get((quote_type or "").upper(), "Otro")


def _client() -> httpx.Client:
    return httpx.Client(headers=_UA, timeout=20.0)


def search(query: str, limit: int = 10) -> list[dict]:
    """Autocompletado universal: devuelve activos de cualquier clase que matcheen `query`."""
    if not query or not query.strip():
        return []
    params = {"q": query.strip(), "quotesCount": limit, "newsCount": 0,
              "enableFuzzyQuery": "false"}
    try:
        with _client() as c:
            data = c.get(_SEARCH, params=params).json()
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for q in data.get("quotes", []):
        sym = q.get("symbol")
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "name": q.get("shortname") or q.get("longname") or sym,
            "type": q.get("quoteType"),
            "asset_class": asset_class(q.get("quoteType")),
            "exchange": q.get("exchDisp") or q.get("exchange"),
        })
    return out


def quote(symbol: str) -> dict | None:
    """Cotización actual de cualquier activo: precio, variación %, moneda y clase."""
    try:
        with _client() as c:
            data = c.get(_CHART.format(sym=symbol), params={"range": "1d", "interval": "1d"}).json()
        meta = data["chart"]["result"][0]["meta"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change_pct = ((price - prev) / prev * 100) if prev else None
    ts = meta.get("regularMarketTime")
    when = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="minutes") if ts else None
    return {
        "symbol": meta.get("symbol", symbol).upper(),
        "name": meta.get("shortName") or meta.get("longName") or symbol.upper(),
        "price": float(price),
        "prev_close": float(prev) if prev else None,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "currency": meta.get("currency", "USD"),
        "asset_class": asset_class(meta.get("instrumentType")),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "as_of": when,
    }


def history(symbol: str, rng: str = "1y") -> dict:
    """Serie temporal para graficar. Devuelve {symbol, range, points:[{t, c}]}."""
    rng = rng if rng in _RANGE_INTERVAL else "1y"
    interval = _RANGE_INTERVAL[rng]
    try:
        with _client() as c:
            data = c.get(_CHART.format(sym=symbol),
                         params={"range": rng, "interval": interval}).json()
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return {"symbol": symbol.upper(), "range": rng, "points": []}
    points = [{"t": t, "c": round(c, 4)} for t, c in zip(ts, closes) if c is not None]
    return {"symbol": symbol.upper(), "range": rng, "points": points}
