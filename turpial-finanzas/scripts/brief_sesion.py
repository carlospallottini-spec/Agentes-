#!/usr/bin/env python3
"""Parte previo a la sesión de Nueva York: puntos y muros de ES y NQ.

Pensado para correr antes de la apertura (9:30 ET). A esa hora el rango de apertura y el
VWAP de hoy todavía no existen, así que el parte usa lo que SÍ está: el RTH previo, el
Globex de la noche, los pivotes, el ATR de sesión y los muros de opciones.

Salida compacta a propósito: se lee en un teléfono, no en una pantalla.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import futuros   # noqa: E402
from quant import niveles as nv   # noqa: E402

CONTRATOS = ["ES=F", "NQ=F"]
# Lo que sirve para planear antes de abrir. El rango de apertura y el VWAP quedan afuera
# porque a esta hora no existen todavía.
UTILES = ("Muro de calls", "Muro de puts", "Gamma cero", "Max pain",
          "Máximo RTH previo", "Mínimo RTH previo", "Cierre RTH previo",
          "Máximo Globex", "Mínimo Globex",
          "Pivote R2", "Pivote R1", "Pivote PP", "Pivote S1", "Pivote S2")


def parte(symbol: str) -> str:
    r = futuros.tablero(symbol)
    if not r.get("ok"):
        return f"*{symbol}* — sin datos: {r.get('motivo')}"

    px = r["precio"]
    s = r.get("sesion") or {}
    o = r.get("opciones") or {}
    lineas = [f"*{symbol.replace('=F', '')}*  {px:,.2f}"]

    prev = s.get("rth_previo") or {}
    if prev.get("c"):
        hueco = px - prev["c"]
        lineas.append(f"Hueco vs cierre previo: {hueco:+,.2f} ({hueco / prev['c'] * 100:+.2f}%)")
    if s.get("atr_sesion"):
        atr = s["atr_sesion"]
        lineas.append(f"ATR de sesión: {atr:,.0f} pts "
                      f"(US$ {atr * r['valor_punto']:,.0f} por contrato)")
    if o.get("regimen_gamma"):
        lineas.append(f"Gamma: {o['regimen_gamma']}")

    # Un solo listado ordenado por precio, con la distancia, marcando dónde está el precio.
    filas = [n for n in (r.get("niveles") or [])
             if n.get("precio") and n["nombre"] in UTILES]
    filas.sort(key=lambda n: -n["precio"])
    lineas.append("")
    puesto = False
    for n in filas:
        if not puesto and n["precio"] < px:
            lineas.append(f"      ── precio {px:,.2f} ──")
            puesto = True
        d = n["precio"] - px
        marca = "◆" if n.get("origen") == "opciones" else "·"
        lineas.append(f"{marca} {n['nombre']:<22} {n['precio']:>10,.2f}  {d:>+8,.1f}")
    if not puesto:
        lineas.append(f"      ── precio {px:,.2f} ──")

    return "\n".join(lineas)


def main() -> int:
    hoy = nv.hora_ny(int(time.time()))
    partes = [f"Parte de sesión NY · {hoy.strftime('%Y-%m-%d %H:%M')} hora de Nueva York",
              "◆ = nivel de opciones · · = nivel de precio"]
    fallos = 0
    for c in CONTRATOS:
        try:
            partes.append("\n" + parte(c))
        except Exception as e:                      # noqa: BLE001
            partes.append(f"\n*{c}* — error al armar el parte: {e}")
            fallos += 1

    partes.append(
        "\n⚠ Esto es un MAPA, no probabilidades. Los niveles sirven para saber dónde "
        "mirar y dónde poner el stop. La tasa de aguante medida sobre ES y NQ (71% y 72%) "
        "NO se distingue de niveles puestos al azar (73%), así que ningún nivel de acá "
        "predice un rebote. Los niveles de opciones salen de la cadena del índice y el "
        "interés abierto es del cierre anterior: no es order flow en tiempo real.")
    print("\n".join(partes))
    return 1 if fallos == len(CONTRATOS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
