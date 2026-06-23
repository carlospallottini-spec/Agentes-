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

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Turpial Finanzas"}
_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_OPTIONS = "https://query1.finance.yahoo.com/v7/finance/options/{sym}"
_CRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
_QSUMMARY = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
_QUOTE = "https://query1.finance.yahoo.com/v7/finance/quote"
_SCREENER = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"

# Sesión con cookie + crumb, necesaria para el endpoint de opciones de Yahoo.
_session: httpx.Client | None = None
_crumb: str | None = None

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
        q = res["indicators"]["quote"][0]
        o, h, l, cl, v = q["open"], q["high"], q["low"], q["close"], q["volume"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return {"symbol": symbol.upper(), "range": rng, "points": [], "candles": []}
    points, candles = [], []
    for i, t in enumerate(ts):
        if cl[i] is None:
            continue
        points.append({"t": t, "c": round(cl[i], 4)})
        candles.append({
            "t": t,
            "o": round(o[i], 4) if o[i] is not None else cl[i],
            "h": round(h[i], 4) if h[i] is not None else cl[i],
            "l": round(l[i], 4) if l[i] is not None else cl[i],
            "c": round(cl[i], 4),
            "v": int(v[i]) if v[i] is not None else 0,
        })
    return {"symbol": symbol.upper(), "range": rng, "points": points, "candles": candles}


def _raw(node, *path):
    """Desempaqueta valores de Yahoo (que vienen como {raw, fmt}); navega por `path`."""
    cur = node
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    if isinstance(cur, dict):
        return cur.get("raw")
    return cur


def quote_summary(symbol: str) -> dict:
    """Fundamentales y key stats de un activo (estilo terminal): valuación, márgenes,
    52 semanas, dividendo, recomendación de analistas, etc."""
    s, crumb = _ensure_crumb()
    params = {"modules": "summaryDetail,defaultKeyStatistics,financialData,price"}
    if crumb:
        params["crumb"] = crumb
    try:
        cli = s or httpx.Client(headers=_UA, timeout=20.0)
        data = cli.get(_QSUMMARY.format(sym=symbol), params=params).json()
        r = data["quoteSummary"]["result"][0]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return {"symbol": symbol.upper(), "status": "no_data"}
    sd, ks, fd, pr = r.get("summaryDetail", {}), r.get("defaultKeyStatistics", {}), \
        r.get("financialData", {}), r.get("price", {})
    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "name": _raw(pr, "longName") or _raw(pr, "shortName"),
        "market_cap": _raw(pr, "marketCap") or _raw(sd, "marketCap"),
        "currency": _raw(pr, "currency"),
        "pe_trailing": _raw(sd, "trailingPE"),
        "pe_forward": _raw(sd, "forwardPE"),
        "eps_trailing": _raw(ks, "trailingEps"),
        "price_to_book": _raw(ks, "priceToBook"),
        "beta": _raw(sd, "beta") or _raw(ks, "beta"),
        "dividend_yield": _raw(sd, "dividendYield"),
        "wk52_high": _raw(sd, "fiftyTwoWeekHigh"),
        "wk52_low": _raw(sd, "fiftyTwoWeekLow"),
        "day_high": _raw(sd, "dayHigh"),
        "day_low": _raw(sd, "dayLow"),
        "volume": _raw(sd, "volume"),
        "avg_volume": _raw(sd, "averageVolume"),
        "profit_margin": _raw(fd, "profitMargins") or _raw(ks, "profitMargins"),
        "gross_margin": _raw(fd, "grossMargins"),
        "roe": _raw(fd, "returnOnEquity"),
        "revenue_growth": _raw(fd, "revenueGrowth"),
        "debt_to_equity": _raw(fd, "debtToEquity"),
        "free_cashflow": _raw(fd, "freeCashflow"),
        "ebitda": _raw(fd, "ebitda"),
        "target_mean": _raw(fd, "targetMeanPrice"),
        "recommendation": _raw(fd, "recommendationKey"),
        "num_analysts": _raw(fd, "numberOfAnalystOpinions"),
    }


def batch_quotes(symbols: list[str]) -> list[dict]:
    """Cotización de varios símbolos en una sola llamada (watchlist, movers)."""
    if not symbols:
        return []
    s, crumb = _ensure_crumb()
    params = {"symbols": ",".join(symbols)}
    if crumb:
        params["crumb"] = crumb
    try:
        cli = s or httpx.Client(headers=_UA, timeout=20.0)
        data = cli.get(_QUOTE, params=params).json()
        rows = data["quoteResponse"]["result"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return []
    out = []
    for q in rows:
        out.append({
            "symbol": q.get("symbol"),
            "name": q.get("shortName") or q.get("longName") or q.get("symbol"),
            "price": q.get("regularMarketPrice"),
            "change_pct": round(q["regularMarketChangePercent"], 2)
            if q.get("regularMarketChangePercent") is not None else None,
            "currency": q.get("currency", "USD"),
            "asset_class": asset_class(q.get("quoteType")),
            "market_cap": q.get("marketCap"),
            "volume": q.get("regularMarketVolume"),
        })
    return out


# Pantallas predefinidas de Yahoo (scrId -> etiqueta didáctica).
SCREENS = {
    "day_gainers": "Mayores subas del día",
    "day_losers": "Mayores bajas del día",
    "most_actives": "Más operadas",
    "undervalued_large_caps": "Grandes infravaloradas",
    "undervalued_growth_stocks": "Crecimiento a buen precio",
    "growth_technology_stocks": "Tecnológicas en crecimiento",
    "aggressive_small_caps": "Small caps agresivas",
}


def screen(scr_id: str = "day_gainers", count: int = 25) -> dict:
    """Corre una pantalla predefinida y devuelve las acciones que la cumplen."""
    if scr_id not in SCREENS:
        scr_id = "day_gainers"
    s, crumb = _ensure_crumb()
    params = {"scrIds": scr_id, "count": count}
    if crumb:
        params["crumb"] = crumb
    try:
        cli = s or httpx.Client(headers=_UA, timeout=20.0)
        data = cli.get(_SCREENER, params=params).json()
        quotes = data["finance"]["result"][0]["quotes"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return {"scr_id": scr_id, "label": SCREENS[scr_id], "results": []}
    results = [{
        "symbol": q.get("symbol"),
        "name": q.get("shortName") or q.get("symbol"),
        "price": q.get("regularMarketPrice"),
        "change_pct": round(q["regularMarketChangePercent"], 2)
        if q.get("regularMarketChangePercent") is not None else None,
        "market_cap": q.get("marketCap"),
        "pe": q.get("trailingPE"),
        "volume": q.get("regularMarketVolume"),
        "asset_class": asset_class(q.get("quoteType")),
    } for q in quotes]
    return {"scr_id": scr_id, "label": SCREENS[scr_id], "results": results}


def news(symbol: str, count: int = 8) -> list[dict]:
    """Noticias recientes asociadas a un símbolo."""
    try:
        with _client() as c:
            data = c.get(_SEARCH, params={"q": symbol, "newsCount": count, "quotesCount": 0}).json()
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for n in data.get("news", []):
        out.append({
            "title": n.get("title"),
            "publisher": n.get("publisher"),
            "link": n.get("link"),
            "published": n.get("providerPublishTime"),
        })
    return out


def _ensure_crumb() -> tuple[httpx.Client, str] | tuple[None, None]:
    """Inicializa (perezosamente) una sesión con cookie + crumb de Yahoo para opciones."""
    global _session, _crumb
    if _session is not None and _crumb:
        return _session, _crumb
    try:
        s = httpx.Client(headers=_UA, timeout=20.0, follow_redirects=True)
        s.get("https://fc.yahoo.com")  # siembra la cookie (devuelve 404, no importa)
        crumb = s.get(_CRUMB).text.strip()
        if not crumb or "<" in crumb:  # a veces devuelve HTML de error
            return None, None
        _session, _crumb = s, crumb
        return _session, _crumb
    except httpx.HTTPError:
        return None, None


def _opt_row(o: dict) -> dict:
    return {
        "strike": o.get("strike"),
        "last": o.get("lastPrice"),
        "bid": o.get("bid"),
        "ask": o.get("ask"),
        "iv": round(o["impliedVolatility"] * 100, 1) if o.get("impliedVolatility") else None,
        "volume": o.get("volume"),
        "open_interest": o.get("openInterest"),
        "itm": o.get("inTheMoney"),
        "expiration": o.get("expiration"),
    }


def options(symbol: str, expiration: int | None = None) -> dict:
    """Cadena de opciones de un activo (requiere crumb de Yahoo).

    Devuelve vencimientos disponibles, el precio subyacente y calls/puts del vencimiento
    elegido (por defecto el más cercano).
    """
    s, crumb = _ensure_crumb()
    if not s:
        return {"symbol": symbol.upper(), "status": "no_data",
                "reason": "No se pudo obtener el crumb de Yahoo para opciones."}
    params = {"crumb": crumb}
    if expiration:
        params["date"] = expiration
    try:
        data = s.get(_OPTIONS.format(sym=symbol), params=params).json()
        res = data["optionChain"]["result"][0]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return {"symbol": symbol.upper(), "status": "no_data",
                "reason": "Sin cadena de opciones para ese símbolo."}

    exp_ts = res.get("expirationDates", [])
    quote_meta = (res.get("quote") or {})
    chain = (res.get("options") or [{}])[0]
    if not exp_ts and not chain.get("calls") and not chain.get("puts"):
        return {"symbol": symbol.upper(), "status": "no_data",
                "reason": "Este activo no tiene cadena de opciones (típico de crypto, Forex o commodities)."}
    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "underlying_price": quote_meta.get("regularMarketPrice"),
        "currency": quote_meta.get("currency", "USD"),
        "expirations": [{"ts": t, "date": datetime.fromtimestamp(t, tz=timezone.utc)
                         .date().isoformat()} for t in exp_ts],
        "selected_expiration": chain.get("expirationDate"),
        "calls": [_opt_row(o) for o in chain.get("calls", [])],
        "puts": [_opt_row(o) for o in chain.get("puts", [])],
    }
