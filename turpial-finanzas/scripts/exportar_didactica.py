#!/usr/bin/env python3
"""Regenera los datos que consume la app didáctica (web/didactica/).

Los datos van aparte del HTML porque son 100 KB de velas reales: la app los pide con
fetch en vez de llevarlos incrustados.
"""

from __future__ import annotations

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors import market   # noqa: E402
from quant import niveles as nv   # noqa: E402
from quant import toques   # noqa: E402

SALIDA = "web/didactica"


def sesiones() -> list[dict]:
    h = market.velas("ES=F", "5m")
    ses = nv.agrupar_sesiones(h["points"])
    out = []
    for i in range(1, len(ses)):
        rth, barras = ses[i].get("rth"), ses[i].get("barras_rth") or []
        if not rth or len(barras) < 10:
            continue
        ns = toques._niveles_de_sesion(ses, i, 14)
        atr = nv.atr_sesiones(ses[:i], 14)
        if not ns or not atr:
            continue
        out.append({
            "fecha": nv.hora_ny(barras[0]["t"]).date().isoformat(),
            "atr": round(atr, 2),
            "prev": {"h": round(ses[i - 1]["rth"]["h"], 2),
                     "l": round(ses[i - 1]["rth"]["l"], 2)},
            "niveles": {k: round(v, 2) for k, v in ns.items()},
            "barras": [[b["t"], round(b["o"], 2), round(b["h"], 2),
                        round(b["l"], 2), round(b["c"], 2)] for b in barras],
        })
    return out


def perfil() -> dict:
    out: dict = {}
    with open("data/opciones/export/perfil_strikes.csv", encoding="utf-8") as fh:
        for f in csv.DictReader(fh):
            d = out.setdefault(f["indice"], {"sesion": f["sesion"], "strikes": []})
            d["strikes"].append([float(f["strike"]), int(f["oi_calls"]), int(f["oi_puts"]),
                                 int(f["vol_calls"]), int(f["vol_puts"])])
    with open("data/opciones/export/serie_diaria.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["indice"] in out:
                out[r["indice"]]["spot"] = float(r["spot"])
                out[r["indice"]]["gamma_cero"] = float(r["gamma_cero"]) if r["gamma_cero"] else None
                out[r["indice"]]["max_pain"] = float(r["max_pain"]) if r["max_pain"] else None
    return out


def main() -> int:
    os.makedirs(SALIDA, exist_ok=True)
    s = sesiones()
    if not s:
        print("Sin sesiones utilizables.", file=sys.stderr)
        return 1
    json.dump(s, open(os.path.join(SALIDA, "sesiones.json"), "w", encoding="utf-8"),
              separators=(",", ":"))
    json.dump(perfil(), open(os.path.join(SALIDA, "perfil.json"), "w", encoding="utf-8"),
              separators=(",", ":"))
    print(f"{len(s)} sesiones · {sum(len(x['barras']) for x in s)} velas")

    # La app TIENE que reproducir esto. Si no, miente.
    h = market.velas("ES=F", "5m")
    rep = toques.estadistica(h["points"])
    g = rep["global"]
    print(f"referencia que la app debe reproducir: {g['aguanto']}/{g['resueltos']} = "
          f"{g['tasa_aguante']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
