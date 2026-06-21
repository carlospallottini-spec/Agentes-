"""Turpial Finanzas — el oráculo (servicio web FastAPI).

Sirve dashboards, expone el score por API y deja que un cron externo dispare cadencias.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from agents.risk_score import analyze
from dashboard.render import render_html
from oracle import scheduler, store
from oracle.earnings import estimate_next_earnings
from connectors import sec_edgar as sec

app = FastAPI(title="Turpial Finanzas", description="Oráculo de riesgo de Wall Street")


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    rows = store.list_reports(limit=50)
    items = "".join(
        f'<li><a href="/report/{r["ticker"]}">{r["ticker"]}</a> · '
        f'{r.get("company") or ""} · score {r.get("score")} ({r.get("band")}) · '
        f'{r.get("generated_at") or ""}</li>'
        for r in rows
    ) or "<li>Todavía no hay reportes. Probá <code>/analyze/AAPL</code>.</li>"
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turpial Finanzas</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b0f1a;
color:#e8edf7;max-width:760px;margin:0 auto;padding:24px}}a{{color:#39d98a}}
h1{{color:#39d98a}}li{{margin:8px 0;line-height:1.5}}code{{background:#121a2b;padding:2px 6px;border-radius:6px}}</style>
</head><body><h1>Turpial Finanzas</h1>
<p>Oráculo de riesgo. Análisis bajo demanda: <code>/analyze/&lt;TICKER&gt;</code> ·
score JSON: <code>/api/score/&lt;TICKER&gt;</code> ·
próximos earnings: <code>/api/earnings/&lt;TICKER&gt;</code></p>
<h2>Reportes recientes</h2><ul>{items}</ul></body></html>"""


@app.get("/analyze/{ticker}", response_class=HTMLResponse)
def analyze_ticker(ticker: str, narrative: bool = Query(True),
                   save: bool = Query(True)) -> HTMLResponse:
    report = analyze(ticker, with_narrative=narrative)
    if report.get("error"):
        raise HTTPException(status_code=404, detail=report["error"])
    if save:
        from dashboard.render import write_dashboard
        html_path = write_dashboard(report)
        store.save_report(report, html_path)
    return HTMLResponse(render_html(report))


@app.get("/api/score/{ticker}")
def api_score(ticker: str) -> JSONResponse:
    from agents.risk_score import gather_data
    data = gather_data(ticker)
    if data.get("error"):
        raise HTTPException(status_code=404, detail=data["error"])
    return JSONResponse(content={
        "ticker": data["ticker"], "company": data["company"],
        "score": data["score"]["overall_score"], "band": data["score"]["band"],
        "coverage": data["score"]["coverage"],
        "pillars": {k: v["score"] for k, v in data["score"]["pillars"].items()},
        "price": data["price"], "insiders": data["insiders"]["senal"]
        if data["insiders"].get("status") == "ok" else None,
    })


@app.get("/api/earnings/{ticker}")
def api_earnings(ticker: str) -> JSONResponse:
    cik = sec.ticker_to_cik(ticker)
    if not cik:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} no encontrado.")
    return JSONResponse(content=estimate_next_earnings(cik))


@app.get("/report/{ticker}", response_class=HTMLResponse)
def latest_report(ticker: str) -> HTMLResponse:
    from config import REPORTS_DIR
    entry = store.latest_for(ticker)
    if not entry:
        raise HTTPException(status_code=404, detail="Sin reporte guardado; usá /analyze.")
    return HTMLResponse((REPORTS_DIR / entry["html"]).read_text(encoding="utf-8"))


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
