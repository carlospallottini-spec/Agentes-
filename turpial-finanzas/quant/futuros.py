"""Tablero de sesión para futuros de índices: junta niveles de precio y de opciones.

Es la capa que alimenta la app. Trae las velas intradía del futuro, la cadena de opciones
del índice equivalente, y devuelve un solo tablero con todo traducido a puntos del futuro.

Cachea en memoria por unos minutos: la página se refresca sola y no tiene sentido volver a
bajar media cadena de opciones en cada recarga. El interés abierto, además, se actualiza
una vez por día — pedirlo cada minuto no agrega nada.
"""
from __future__ import annotations

import time

from connectors import market
from quant import niveles as nv
from quant import opciones as op

CONTRATOS = {
    "ES=F":  {"nombre": "E-mini S&P 500", "indice": "^SPX", "tick": 0.25,
              "valor_tick": 12.50, "punto": 50.0},
    "MES=F": {"nombre": "Micro E-mini S&P 500", "indice": "^SPX", "tick": 0.25,
              "valor_tick": 1.25, "punto": 5.0},
    "NQ=F":  {"nombre": "E-mini Nasdaq 100", "indice": "^NDX", "tick": 0.25,
              "valor_tick": 5.00, "punto": 20.0},
    "MNQ=F": {"nombre": "Micro E-mini Nasdaq 100", "indice": "^NDX", "tick": 0.25,
              "valor_tick": 0.50, "punto": 2.0},
}

_CACHE: dict[str, tuple[float, dict]] = {}
TTL_NIVELES = 120      # 2 minutos: el precio se mueve, los niveles de sesión poco
TTL_OPCIONES = 900     # 15 minutos: el interés abierto cambia una vez por día


def _cacheado(clave: str, ttl: int, fn):
    ahora = time.time()
    if clave in _CACHE:
        cuando, valor = _CACHE[clave]
        if ahora - cuando < ttl:
            return valor
    valor = fn()
    _CACHE[clave] = (ahora, valor)
    return valor


def _cadenas(indice: str, n_vencimientos: int = 4) -> tuple[list[dict], float | None]:
    """Primeras `n_vencimientos` cadenas del índice. El primero suele ser el del día."""
    base = market.options(indice)
    if base.get("status") != "ok":
        return [], None
    spot = base.get("underlying_price")
    cadenas = [base]
    for e in base.get("expirations", [])[1:n_vencimientos]:
        c = market.options(indice, expiration=e["ts"])
        if c.get("status") == "ok":
            cadenas.append(c)
    return cadenas, spot


def tablero(symbol: str, minutos_apertura: int = 30, rango_pct: float = 5.0,
            n_vencimientos: int = 4) -> dict:
    """Tablero completo de un contrato: precio, niveles de sesión y niveles de opciones."""
    symbol = symbol.upper()
    meta = CONTRATOS.get(symbol)
    if not meta:
        return {"ok": False, "motivo": f"Contrato no soportado: {symbol}. "
                                       f"Disponibles: {', '.join(CONTRATOS)}."}

    cot = _cacheado(f"q:{symbol}", 60, lambda: market.quote(symbol))
    if not cot:
        return {"ok": False, "symbol": symbol, "motivo": "Sin cotización del futuro."}

    velas = _cacheado(f"v:{symbol}", TTL_NIVELES, lambda: market.velas(symbol, "5m"))
    pts = velas.get("points", [])
    sesion = nv.niveles_sesion(pts, minutos_apertura) if pts else {
        "ok": False, "motivo": "Sin velas intradía."}

    cadenas, spot_idx = _cacheado(
        f"o:{meta['indice']}", TTL_OPCIONES, lambda: _cadenas(meta["indice"], n_vencimientos))
    opc = (op.analizar(cadenas, spot_idx, cot["price"], rango_pct=rango_pct)
           if cadenas and spot_idx else
           {"ok": False, "motivo": f"Sin cadena de opciones para {meta['indice']}."})

    # Un solo listado ordenado por precio, con el origen de cada nivel.
    todos = []
    for n in (sesion.get("niveles") or []):
        todos.append({**n, "origen": "sesion"})
    for n in (opc.get("niveles") or []):
        todos.append({"nombre": n["nombre"], "precio": n["precio"], "tipo": n["tipo"],
                      "nota": n["nota"], "dato": n.get("dato"),
                      "distancia": n.get("distancia"),
                      "distancia_pct": (round(n["distancia"] / cot["price"] * 100, 3)
                                        if n.get("distancia") else None),
                      "origen": "opciones"})
    todos.sort(key=lambda n: -(n["precio"] or 0))

    return {
        "ok": True,
        "symbol": symbol,
        "nombre": meta["nombre"],
        "indice_opciones": meta["indice"],
        "valor_punto": meta["punto"],
        "valor_tick": meta["valor_tick"],
        "precio": cot["price"],
        "cambio_pct": cot.get("change_pct"),
        "as_of": cot.get("as_of"),
        "sesion": sesion,
        "opciones": opc,
        "niveles": todos,
        "aviso": ("Los niveles de opciones salen de la cadena del índice "
                  f"({meta['indice']}), que comparte subyacente con el futuro. NO es "
                  "option flow en tiempo real: barridos y bloques necesitan el feed de "
                  "ticks de CME, que es pago. El volumen por strike es actividad de hoy; "
                  "el interés abierto es lo que quedó de ayer."),
    }


def contratos() -> list[dict]:
    """Lista de contratos soportados, para armar el selector de la interfaz."""
    return [{"symbol": k, **v} for k, v in CONTRATOS.items()]
