"""Compara el CSV de diagnóstico que exporta el EA contra el motor de Python.

Es el cierre del círculo: `verify_ports.py` prueba que la matemática de MQL5 y C#
es la misma que la de `quant/` sobre series sintéticas; esta herramienta lo prueba
sobre los datos REALES que usó el tester, con el historial del bróker, sus huecos de
sesión y sus precios.

Cómo usarla:

  1. En el EA poné `InpDiagnosticoCSV = true` y corré el tester.
  2. El archivo queda en la carpeta `Files` del agente de testeo (botón derecho sobre
     el resultado > Abrir carpeta, o MQL5\\Files del terminal).
  3. python trading/tests/compare_ea_csv.py OU_diag_EURUSD_PERIOD_H1.csv --ventana 250

Las primeras `ventana-1` filas se saltean: para recalcularlas haría falta historial
anterior al que el propio CSV contiene.

Sobre la tolerancia: el CSV guarda el precio ya redondeado a los dígitos del símbolo,
así que Python recalcula sobre un precio levemente distinto del que usó el EA. Ese error
se amplifica al pasar de theta a half_life = ln(2)/theta, porque una diferencia relativa
en theta es la misma diferencia relativa en el half-life. Por eso la comparación es
RELATIVA más un piso absoluto, no puramente relativa: el z-score cruza el cero, y ahí
una diferencia relativa se dispara aunque la absoluta sea despreciable. El piso de 1e-6
en unidades de z está seis órdenes por debajo de cualquier umbral de decisión (la entrada
está en 1.5), así que jamás puede dar vuelta una señal.

La igualdad exacta entre los motores ya está probada aparte, con precisión completa,
en trading/tests/verify_ports.py.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from quant import ou  # noqa: E402

COLUMNAS = ["theta", "mu", "sigma_eq", "half_life", "z", "df_stat"]


def leer(ruta: str, sep: str) -> list[dict]:
    with open(ruta, newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh, delimiter=sep))


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida el CSV del EA contra quant/")
    ap.add_argument("csv", help="CSV exportado por el EA")
    ap.add_argument("--ventana", type=int, default=250, help="InpVentana usado en el test")
    ap.add_argument("--sep", default=";", help="Separador del CSV (default ';')")
    ap.add_argument("--tol-rel", type=float, default=1e-5,
                    help="Tolerancia relativa (default 1e-5)")
    ap.add_argument("--tol-abs", type=float, default=1e-6,
                    help="Piso absoluto de la tolerancia (default 1e-6)")
    ap.add_argument("--max-errores", type=int, default=5, help="Discrepancias a listar")
    args = ap.parse_args()

    filas = leer(args.csv, args.sep)
    if not filas:
        print("El CSV está vacío o no tiene cabecera.")
        return 1
    faltan = [c for c in ["close", "ok"] + COLUMNAS if c not in filas[0]]
    if faltan:
        print("Al CSV le faltan columnas:", ", ".join(faltan))
        return 1

    closes = []
    for f in filas:
        try:
            closes.append(float(f["close"]))
        except (TypeError, ValueError):
            print("Fila con 'close' no numérico; ¿el separador es el correcto?")
            return 1

    V = args.ventana
    if len(filas) <= V:
        print(f"Hacen falta más de {V} filas para poder recalcular alguna ventana; "
              f"hay {len(filas)}. Corré un período más largo en el tester.")
        return 1

    def dentro(v_ea: float, v_py: float) -> bool:
        return abs(v_ea - v_py) <= args.tol_abs + args.tol_rel * abs(v_py)

    peor = {c: 0.0 for c in COLUMNAS}          # diferencia relativa (informativa)
    peor_abs = {c: 0.0 for c in COLUMNAS}      # diferencia absoluta (informativa)
    col_ok = {c: True for c in COLUMNAS}       # veredicto real, valor por valor
    errores: list[str] = []
    comparadas = 0
    desacuerdos_ok = 0

    for j in range(V - 1, len(filas)):
        ventana = closes[j - V + 1: j + 1]
        if any(c <= 0 for c in ventana):
            continue
        p = ou.calibrate([math.log(c) for c in ventana])
        f = filas[j]
        ea_ok = f["ok"].strip() == "1"
        comparadas += 1

        if ea_ok != bool(p.get("ok")):
            desacuerdos_ok += 1
            if len(errores) < args.max_errores:
                errores.append(f"  fila {j} ({f.get('time','')}): el EA dice ok={f['ok']} "
                               f"y Python dice ok={p.get('ok')}")
            continue
        if not ea_ok:
            continue

        py = {"theta": p["theta"], "mu": p["mu"], "sigma_eq": p["sigma_eq"],
              "half_life": p["half_life"], "z": p["z"], "df_stat": p["df_stat"]}
        for c in COLUMNAS:
            try:
                v_ea = float(f[c])
            except (TypeError, ValueError):
                continue
            dif = abs(v_ea - py[c])
            rel = dif / max(abs(py[c]), 1e-12)
            peor[c] = max(peor[c], rel)
            peor_abs[c] = max(peor_abs[c], dif)
            if dentro(v_ea, py[c]):
                continue
            col_ok[c] = False
            if len(errores) < args.max_errores:
                errores.append(f"  fila {j} ({f.get('time','')}) {c}: EA={v_ea:.10f} "
                               f"Python={py[c]:.10f} (dif {dif:.2e} · rel {rel:.2e})")

    print(f"Filas en el CSV: {len(filas)} · ventanas recalculadas: {comparadas} "
          f"· ventana = {V}")
    print(f"Diferencia máxima por columna (tolerancia: {args.tol_abs:.0e} + "
          f"{args.tol_rel:.0e}·|valor|)")
    print(f"  {'':4}{'columna':<12}{'absoluta':>12}{'relativa':>12}")
    for c in COLUMNAS:
        print(f"  {'ok  ' if col_ok[c] else 'MAL '}{c:<12}"
              f"{peor_abs[c]:>12.3e}{peor[c]:>12.3e}")
    if desacuerdos_ok:
        print(f"\n{desacuerdos_ok} filas donde EA y Python discrepan sobre si el modelo calibra.")
    if errores:
        print("\nPrimeras discrepancias:")
        print("\n".join(errores))
        return 1

    print("\nEl EA y el motor de Python calculan lo mismo sobre los datos del tester.")
    print("Nota: esto valida la MATEMÁTICA, no la ejecución (llenado, spread, comisiones,")
    print("deslizamiento). Eso sólo lo dice el reporte del tester.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
