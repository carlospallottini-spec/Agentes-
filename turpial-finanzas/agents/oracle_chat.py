"""El agente IA del oráculo — un analista conversacional con herramientas en vivo.

Es el "agente dentro de la plataforma": el inversor le pregunta cualquier cosa y el
agente busca símbolos, cotiza en vivo, trae historiales, calcula Risk Scores y maneja
la watchlist, usando los mismos conectores reales de Turpial. Tool-use multi-turno.
"""
from __future__ import annotations

import json

import anthropic

from agents.base import build_client
from config import MODEL
from connectors import market
from oracle import watchlist

SYSTEM = """Sos el **agente IA de Turpial Finanzas**, un analista financiero didáctico que
acompaña a un inversor dentro de la plataforma. Podés hablar de cualquier clase de activo:
acciones, ETFs, bonos, crypto, Forex, commodities, índices.

Cómo trabajás:
- Usá las herramientas para traer datos REALES (búsqueda, cotización, historial, Risk Score,
  watchlist) en vez de inventar. Si una herramienta no devuelve datos, decilo con honestidad.
- Sé DIDÁCTICO: explicá cada término técnico la primera vez que aparece, en paréntesis y simple.
- Cuando el inversor menciona un activo por nombre, primero buscá el símbolo con `buscar_simbolo`.
- El Risk Score (`risk_score_accion`) solo aplica a acciones de empresas con filings en la SEC
  (EE.UU.). Para crypto, Forex o commodities no hay fundamentales: ofrecé precio, contexto y
  límites honestos en vez de un score.
- Respuestas claras y accionables, en español rioplatense. Sin recomendar comprar/vender de
  forma tajante: das análisis, no órdenes. Recordá que no es asesoramiento de inversión."""

TOOLS = [
    {
        "name": "buscar_simbolo",
        "description": "Busca el símbolo (ticker) de cualquier activo por nombre o texto. "
                       "Devuelve coincidencias multi-activo (acción, ETF, crypto, FX, commodity, índice).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Nombre o texto a buscar."}},
            "required": ["query"],
        },
    },
    {
        "name": "cotizar",
        "description": "Precio actual, variación % y moneda de un símbolo (cualquier clase de activo).",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "Símbolo Yahoo, ej. AAPL, BTC-USD, EURUSD=X, GC=F."}},
            "required": ["symbol"],
        },
    },
    {
        "name": "historial",
        "description": "Serie de precios histórica para ver tendencia.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "rango": {"type": "string", "enum": ["1d", "5d", "1mo", "6mo", "1y", "5y", "max"]},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "cadena_opciones",
        "description": "Trae la cadena de opciones (calls y puts) de una acción o ETF: "
                       "vencimientos, strikes, precio, volatilidad implícita e interés abierto.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "Símbolo subyacente, ej. AAPL."}},
            "required": ["symbol"],
        },
    },
    {
        "name": "fundamentales",
        "description": "Key stats y fundamentales de un activo: market cap, P/E, márgenes, "
                       "ROE, 52 semanas, dividendo, recomendación de analistas y precio objetivo.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "noticias",
        "description": "Noticias recientes asociadas a un activo.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "screener",
        "description": "Corre una pantalla de acciones. scr_id válidos: day_gainers, day_losers, "
                       "most_actives, undervalued_large_caps, undervalued_growth_stocks, "
                       "growth_technology_stocks, aggressive_small_caps.",
        "input_schema": {
            "type": "object",
            "properties": {"scr_id": {"type": "string"}},
            "required": ["scr_id"],
        },
    },
    {
        "name": "risk_score_accion",
        "description": "Calcula el Risk Score (3 pilares: valuación, salud financiera, crecimiento) "
                       "de una ACCIÓN de empresa con filings en la SEC (EE.UU.).",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker de la acción, ej. AAPL."}},
            "required": ["ticker"],
        },
    },
    {
        "name": "ver_watchlist",
        "description": "Lista los activos en la lista de seguimiento del inversor.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "agregar_watchlist",
        "description": "Agrega un activo a la lista de seguimiento.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "quitar_watchlist",
        "description": "Quita un activo de la lista de seguimiento.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
]


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _execute(name: str, args: dict) -> str:
    if name == "buscar_simbolo":
        return _dump(market.search(args["query"]))
    if name == "cotizar":
        return _dump(market.quote(args["symbol"]) or {"error": "Sin cotización para ese símbolo."})
    if name == "historial":
        h = market.history(args["symbol"], args.get("rango", "1y"))
        pts = h["points"]
        # Resumimos para no inundar el contexto: primero, último, min, max, n.
        if pts:
            closes = [p["c"] for p in pts]
            resumen = {"symbol": h["symbol"], "rango": h["range"], "n": len(pts),
                       "primero": pts[0]["c"], "ultimo": pts[-1]["c"],
                       "min": min(closes), "max": max(closes)}
        else:
            resumen = {"symbol": h["symbol"], "rango": h["range"], "n": 0}
        return _dump(resumen)
    if name == "cadena_opciones":
        o = market.options(args["symbol"])
        if o.get("status") != "ok":
            return _dump(o)
        # Resumimos: vencimiento más cercano + strikes cerca del dinero (at-the-money).
        spot = o.get("underlying_price")
        def near(rows):
            if spot:
                rows = sorted(rows, key=lambda r: abs((r.get("strike") or 0) - spot))[:6]
            return [{k: r[k] for k in ("strike", "last", "iv", "open_interest", "itm")} for r in rows]
        return _dump({"symbol": o["symbol"], "subyacente": spot,
                      "vencimientos": [e["date"] for e in o["expirations"][:8]],
                      "calls_atm": near(o["calls"]), "puts_atm": near(o["puts"])})
    if name == "fundamentales":
        return _dump(market.quote_summary(args["symbol"]))
    if name == "noticias":
        return _dump(market.news(args["symbol"], 6))
    if name == "screener":
        return _dump(market.screen(args.get("scr_id", "day_gainers"), 15))
    if name == "risk_score_accion":
        from agents.risk_score import gather_data
        d = gather_data(args["ticker"])
        if d.get("error"):
            return _dump({"error": d["error"]})
        sc = d["score"]
        return _dump({
            "empresa": d["company"], "ticker": d["ticker"],
            "score": sc["overall_score"], "banda": sc["band"], "cobertura": sc["coverage"],
            "pilares": {k: round(v["score"], 1) if v["score"] is not None else None
                        for k, v in sc["pillars"].items()},
            "precio": d["price"], "insiders": d["insiders"].get("senal"),
        })
    if name == "ver_watchlist":
        return _dump(watchlist.list_items())
    if name == "agregar_watchlist":
        q = market.quote(args["symbol"])
        if not q:
            return _dump({"error": "No encontré ese símbolo para agregar."})
        watchlist.add(q["symbol"], q["name"], q["asset_class"])
        return _dump({"ok": True, "agregado": q["symbol"]})
    if name == "quitar_watchlist":
        watchlist.remove(args["symbol"])
        return _dump({"ok": True, "quitado": args["symbol"].upper()})
    return _dump({"error": f"Herramienta desconocida: {name}"})


def chat(messages: list[dict], max_steps: int = 6) -> dict:
    """Ejecuta un turno del agente. `messages` = historial [{role, content}].

    Devuelve {reply, tool_calls:[...]} — el texto final y qué herramientas usó (para la UI).
    """
    client = build_client()
    history = [{"role": m["role"], "content": m["content"]} for m in messages]
    used: list[str] = []

    for _ in range(max_steps):
        resp = client.messages.create(
            model=MODEL, max_tokens=1500, system=SYSTEM, tools=TOOLS, messages=history,
        )
        history.append({"role": "assistant",
                        "content": [b.model_dump(exclude_none=True) for b in resp.content]})
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"reply": text, "tool_calls": used}
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                used.append(b.name)
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": _execute(b.name, dict(b.input))})
        history.append({"role": "user", "content": results})

    return {"reply": "Hice varias consultas pero no llegué a una respuesta final; "
                     "probá reformular la pregunta.", "tool_calls": used}
