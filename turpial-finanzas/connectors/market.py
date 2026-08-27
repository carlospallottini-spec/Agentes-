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

# Intervalos de velas aceptados por Yahoo (los que usamos).
_INTERVALS = {"5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}

# Rangos válidos -> intervalo de velas por defecto.
_RANGE_INTERVAL = {
    "1d": "5m", "5d": "30m", "1mo": "1d", "3mo": "1d", "6mo": "1d",
    "1y": "1d", "2y": "1d", "5y": "1wk", "10y": "1wk", "ytd": "1d", "max": "1mo",
}

# Profundidad máxima que Yahoo sirve por intervalo, en días. Los topes reales son
# 7 / 60 / 730, pero el límite es estricto ("must be within the last 60 days"): pedir
# el tope exacto cae afuera por el redondeo del reloj y devuelve "Unprocessable
# Entity". Se deja un día de margen.
_MAX_DIAS = {
    "1m": 6, "2m": 59, "5m": 59, "15m": 59, "30m": 59, "90m": 59,
    "1h": 720, "1d": 36500, "1wk": 36500, "1mo": 36500,
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


def history(symbol: str, rng: str = "1y", interval: str | None = None) -> dict:
    """Serie temporal para graficar. Devuelve {symbol, range, points:[{t, c}]}.

    `interval` fuerza la granularidad de las velas (ej. "1d" sobre un rango de 5y, que
    por defecto vendría semanal). Lo usa el motor cuantitativo, que necesita muchos
    puntos diarios para calibrar el proceso de Ornstein-Uhlenbeck.
    """
    if rng not in _RANGE_INTERVAL:
        # Antes esto caía a "1y" en silencio y devolvía un histórico más corto que el
        # pedido, sin que el que llama se enterara. Ahora el rango efectivo viaja en
        # la respuesta y queda un aviso en el dict.
        aviso = f"Rango '{rng}' no soportado por Yahoo; se usó '1y'."
        rng = "1y"
    else:
        aviso = None
    interval = interval if interval in _INTERVALS else _RANGE_INTERVAL[rng]
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
    out = {"symbol": symbol.upper(), "range": rng, "interval": interval, "points": points}
    if aviso:
        out["aviso"] = aviso
    return out


def intraday(symbol: str, interval: str = "5m", dias: int | None = None) -> dict:
    """Velas intradiarias con la máxima profundidad que Yahoo permite para `interval`.

    El endpoint de rangos con nombre ("1mo", "3mo") rechaza los intervalos cortos más
    allá de su tope; pidiendo por timestamps se llega al límite real (60 días en 5m/15m,
    7 en 1m). Devuelve el mismo formato que `history`, más `dias_pedidos`.
    """
    interval = interval if interval in _INTERVALS else "5m"
    tope = _MAX_DIAS.get(interval, 60)
    dias = min(dias or tope, tope)
    fin = int(datetime.now(tz=timezone.utc).timestamp())
    ini = fin - dias * 86400
    try:
        with _client() as c:
            data = c.get(_CHART.format(sym=symbol),
                         params={"period1": ini, "period2": fin, "interval": interval}).json()
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return {"symbol": symbol.upper(), "interval": interval, "dias_pedidos": dias,
                "points": []}
    points = [{"t": t, "c": round(c, 6)} for t, c in zip(ts, closes) if c is not None]
    return {"symbol": symbol.upper(), "interval": interval, "dias_pedidos": dias,
            "range": f"{dias}d", "points": points}


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
