"""Turpial Finanzas — plataforma todo-en-uno (servicio web FastAPI).

Sirve la SPA interactiva (buscador universal, watchlist, gráficos, agente IA) y expone
las APIs multi-activo. Un cron externo dispara las cadencias del oráculo.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from agents.risk_score import analyze, gather_data
from connectors import market
from dashboard.render import render_html, write_dashboard
from oracle import scheduler, store, watchlist
from oracle.earnings import estimate_next_earnings
from connectors import sec_edgar as sec

app = FastAPI(title="Turpial Finanzas", description="Plataforma de inversión todo-en-uno")

WEB_DIR = Path(__file__).parent / "web"


# --------------------------------------------------------------------------- SPA
@app.get("/", response_class=HTMLResponse)
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# ---------------------------------------------------------------- Mercado / datos
@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1)) -> JSONResponse:
    return JSONResponse(content=market.search(q))


@app.get("/api/quote/{symbol}")
def api_quote(symbol: str) -> JSONResponse:
    q = market.quote(symbol)
    if not q:
        raise HTTPException(status_code=404, detail=f"Sin cotización para {symbol}.")
    return JSONResponse(content=q)


@app.get("/api/history/{symbol}")
def api_history(symbol: str, range: str = Query("1y")) -> JSONResponse:
    return JSONResponse(content=market.history(symbol, range))


@app.get("/api/options/{symbol}")
def api_options(symbol: str, expiration: int | None = Query(None)) -> JSONResponse:
    return JSONResponse(content=market.options(symbol, expiration))


@app.get("/api/fundamentals/{symbol}")
def api_fundamentals(symbol: str) -> JSONResponse:
    return JSONResponse(content=market.quote_summary(symbol))


@app.get("/api/news/{symbol}")
def api_news(symbol: str) -> JSONResponse:
    return JSONResponse(content=market.news(symbol))


@app.get("/api/screens")
def api_screens() -> JSONResponse:
    return JSONResponse(content=market.SCREENS)


@app.get("/api/screen/{scr_id}")
def api_screen(scr_id: str) -> JSONResponse:
    return JSONResponse(content=market.screen(scr_id))


@app.get("/api/overview")
def api_overview() -> JSONResponse:
    """Snapshot de mercado: índices y benchmarks clave + top movers."""
    bench = ["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX", "GC=F", "CL=F", "BTC-USD", "EURUSD=X", "^TNX"]
    return JSONResponse(content={
        "benchmarks": market.batch_quotes(bench),
        "gainers": market.screen("day_gainers", 8)["results"],
        "losers": market.screen("day_losers", 8)["results"],
        "actives": market.screen("most_actives", 8)["results"],
    })


@app.post("/api/quotes")
def api_quotes(payload: dict = Body(...)) -> JSONResponse:
    return JSONResponse(content=market.batch_quotes((payload or {}).get("symbols", [])))


# ------------------------------------------------------------------- Watchlist
@app.get("/api/watchlist")
def api_watchlist() -> JSONResponse:
    return JSONResponse(content=watchlist.list_items())


@app.post("/api/watchlist")
def api_watchlist_add(payload: dict = Body(...)) -> JSONResponse:
    symbol = (payload or {}).get("symbol")
    if not symbol:
        raise HTTPException(status_code=400, detail="Falta 'symbol'.")
    q = market.quote(symbol)
    items = watchlist.add(symbol, q["name"] if q else None, q["asset_class"] if q else None)
    return JSONResponse(content=items)


@app.delete("/api/watchlist/{symbol}")
def api_watchlist_remove(symbol: str) -> JSONResponse:
    return JSONResponse(content=watchlist.remove(symbol))


# ----------------------------------------------------------------- Agente IA
@app.post("/api/chat")
def api_chat(payload: dict = Body(...)) -> JSONResponse:
    messages = (payload or {}).get("messages")
    if not messages:
        raise HTTPException(status_code=400, detail="Falta 'messages'.")
    from agents.oracle_chat import chat
    try:
        return JSONResponse(content=chat(messages))
    except RuntimeError as e:  # típicamente falta ANTHROPIC_API_KEY
        raise HTTPException(status_code=503, detail=str(e))


# --------------------------------------------------------------- Risk Score
@app.get("/api/score/{ticker}")
def api_score(ticker: str) -> JSONResponse:
    data = gather_data(ticker)
    if data.get("error"):
        raise HTTPException(status_code=404, detail=data["error"])
    sc = data["score"]
    return JSONResponse(content={
        "ticker": data["ticker"], "company": data["company"],
        "score": sc["overall_score"], "band": sc["band"], "coverage": sc["coverage"],
        "pillars": {k: v["score"] for k, v in sc["pillars"].items()},
        "price": data["price"],
        "insiders": data["insiders"].get("senal") if data["insiders"].get("status") == "ok" else None,
    })


@app.get("/api/earnings/{ticker}")
def api_earnings(ticker: str) -> JSONResponse:
    cik = sec.ticker_to_cik(ticker)
    if not cik:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} no encontrado.")
    return JSONResponse(content=estimate_next_earnings(cik))


@app.get("/analyze/{ticker}", response_class=HTMLResponse)
def analyze_ticker(ticker: str, narrative: bool = Query(True), save: bool = Query(True)) -> HTMLResponse:
    report = analyze(ticker, with_narrative=narrative)
    if report.get("error"):
        raise HTTPException(status_code=404, detail=report["error"])
    if save:
        store.save_report(report, write_dashboard(report))
    return HTMLResponse(render_html(report))


# -------------------------------------------------------------------- Oráculo
@app.post("/cron/{cadence}")
def trigger_cron(cadence: str, x_cron_token: str | None = Header(default=None)) -> JSONResponse:
    expected = os.environ.get("CRON_TOKEN")
    if expected and x_cron_token != expected:
        raise HTTPException(status_code=401, detail="Token de cron inválido.")
    if cadence == "pre-earnings":
        results = scheduler.run_pre_earnings_scan()
    elif cadence in ("diario", "semanal", "mensual"):
        results = scheduler.run_cadence(cadence)
    else:
        raise HTTPException(status_code=400, detail="Cadencia inválida.")
    return JSONResponse(content={"cadence": cadence, "results": results})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "turpial-finanzas"}
