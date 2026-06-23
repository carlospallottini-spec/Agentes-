"""Precio actual de mercado — feeds gratuitos y sin API key.

Primario: Yahoo Finance (chart API, JSON). Fallback: Stooq (CSV).
Para intradía en tiempo real institucional haría falta un proveedor pago (upgrade).
"""
from __future__ import annotations

import csv
import io

import httpx

_YF_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"
_STOOQ_URL = "https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv"
_UA = {"User-Agent": "Mozilla/5.0 (Turpial Finanzas)"}


def _from_yahoo(ticker: str) -> dict | None:
    try:
        with httpx.Client(timeout=20.0, headers=_UA) as c:
            data = c.get(_YF_URL.format(sym=ticker.upper())).json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        ts = meta.get("regularMarketTime")
        from datetime import datetime, timezone
        date = (datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                if ts else None)
        return {"price": float(price), "date": date,
                "currency": meta.get("currency", "USD"), "source": "yahoo"}
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None


def _from_stooq(ticker: str) -> dict | None:
    try:
        with httpx.Client(timeout=20.0) as c:
            text = c.get(_STOOQ_URL.format(sym=f"{ticker.lower()}.us")).text
    except httpx.HTTPError:
        return None
    row = next(csv.DictReader(io.StringIO(text)), None)
    if not row or row.get("Close") in (None, "N/D", ""):
        return None
    try:
        return {"price": float(row["Close"]), "date": row.get("Date"),
                "currency": "USD", "source": "stooq"}
    except (ValueError, KeyError):
        return None


def current_price(ticker: str) -> dict | None:
    """Devuelve {'price','date','currency','source'} o None si ningún feed responde."""
    return _from_yahoo(ticker) or _from_stooq(ticker)
