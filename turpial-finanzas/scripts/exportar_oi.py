#!/usr/bin/env python3
"""Exporta el histórico de opciones a dos CSV para el tablero.

Se separan en dos archivos porque responden preguntas distintas: el perfil por strike
muestra dónde están los muros HOY, y la serie diaria es lo que se va acumulando para poder
testear algo dentro de unos meses.
"""

from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import snapshots as sn   # noqa: E402

INDICES = ["^SPX", "^NDX"]
SALIDA = "data/opciones/export"

COLS_SERIE = ["sesion", "indice", "spot", "gex_total", "regimen_gamma", "max_pain",
              "gamma_cero", "muro_calls", "muro_puts", "oi_calls", "oi_puts",
              "ratio_put_call_oi", "ratio_put_call_vol", "volumen_total",
              "d_gex_total", "d_max_pain", "d_oi_calls", "d_oi_puts"]
COLS_PERFIL = ["indice", "sesion", "strike", "dist_pct", "oi_calls", "oi_puts",
               "oi_neto", "vol_calls", "vol_puts", "vol_total"]


def main() -> int:
    os.makedirs(SALIDA, exist_ok=True)
    filas_serie, filas_perfil = [], []
    resumen = []

    for ind in INDICES:
        nombre = ind.lstrip("^")
        s = sn.serie(ind)
        if not s.get("ok"):
            print(f"{ind}: {s.get('motivo')}", file=sys.stderr)
            continue
        for f in s["serie"]:
            filas_serie.append({**{c: "" for c in COLS_SERIE}, **f, "indice": nombre})

        # El perfil es el de la ÚLTIMA foto: es una radiografía de hoy, no una serie.
        fotos = sn.leer(ind)
        ultima = fotos[-1]
        spot = ultima["spot"]
        for st in ultima["strikes"]:
            filas_perfil.append({
                "indice": nombre, "sesion": ultima["sesion"], "strike": st["k"],
                "dist_pct": round((st["k"] / spot - 1) * 100, 2),
                "oi_calls": st["oic"], "oi_puts": st["oip"],
                "oi_neto": st["oic"] - st["oip"],
                "vol_calls": st["vc"], "vol_puts": st["vp"],
                "vol_total": st["vc"] + st["vp"],
            })
        resumen.append(f"{nombre}: {s['n']} sesión(es), {len(ultima['strikes'])} strikes")

    if not filas_serie:
        print("Nada para exportar.", file=sys.stderr)
        return 1

    for nombre, cols, filas in (("serie_diaria.csv", COLS_SERIE, filas_serie),
                                ("perfil_strikes.csv", COLS_PERFIL, filas_perfil)):
        r = os.path.join(SALIDA, nombre)
        with open(r, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(filas)
        print(f"{r}: {len(filas)} filas")

    print(" · ".join(resumen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
