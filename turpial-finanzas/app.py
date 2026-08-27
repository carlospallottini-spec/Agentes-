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
from quant import engine as quant_engine
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


# ------------------------------------------------------------ Cuantitativo
@app.get("/api/quant/par/{sym_a}/{sym_b}")
def api_quant_par(sym_a: str, sym_b: str, rango: str = Query("5y"),
                  ventana: int = Query(250, ge=60, le=1000),
                  entrada: float = Query(2.0, ge=0.1, le=6.0),
                  salida: float = Query(0.5, ge=0.0, le=3.0),
                  stop: float = Query(3.5, ge=0.5, le=10.0),
                  costo_bps: float = Query(5.0, ge=0.0, le=200.0),
                  backtest: bool = Query(True)) -> JSONResponse:
    """Cointegración de dos activos + OU sobre el spread (arbitraje estadístico)."""
    rep = quant_engine.analyze_pair(sym_a, sym_b, rng=rango, ventana=ventana,
                                    entrada=entrada, salida=salida, stop=stop,
                                    cost_bps=costo_bps, con_backtest=backtest)
    if not rep.get("ok"):
        raise HTTPException(status_code=404, detail=rep.get("motivo", "Par no analizable."))
    return JSONResponse(content=rep)


@app.get("/api/quant/{symbol}")
def api_quant(symbol: str, rango: str = Query("5y"),
              ventana: int = Query(250, ge=60, le=1000),
              entrada: float = Query(1.5, ge=0.1, le=6.0),
              salida: float = Query(0.5, ge=0.0, le=3.0),
              stop: float = Query(3.0, ge=0.5, le=10.0),
              costo_bps: float = Query(5.0, ge=0.0, le=200.0),
              regimen: bool = Query(True),
              backtest: bool = Query(True)) -> JSONResponse:
    """Ornstein-Uhlenbeck + régimen de Markov + backtest walk-forward de un activo."""
    rep = quant_engine.analyze(symbol, rng=rango, ventana=ventana, entrada=entrada,
                               salida=salida, stop=stop, cost_bps=costo_bps,
                               usar_regimen=regimen, con_backtest=backtest)
    if not rep.get("ok"):
        raise HTTPException(status_code=404, detail=rep.get("motivo", "Activo no analizable."))
    return JSONResponse(content=rep)


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
