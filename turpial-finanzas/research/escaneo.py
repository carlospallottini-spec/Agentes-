"""Escaneos sistemáticos: ¿hay reversión operable en algún lado?

Dos experimentos, con la misma disciplina estadística:

  --modo pares         20 pares candidatos en velas diarias (5 años)
  --modo intradiario   12 instrumentos × 4 timeframes (5m/15m/30m en 59 días, 1h en 2 años)

Los parámetros de la estrategia están FIJOS y son los mismos para todos los casos. No se
optimiza nada: el objetivo es medir la distribución de resultados, no encontrar el mejor.
Buscar el mejor de una tabla grande siempre encuentra algo, y ese algo casi nunca existe.

Cada corrida reporta el Sharpe con su t-stat (error estándar de Lo, 2002) y el escaneo
completo aplica Bonferroni y Benjamini-Hochberg sobre los p-valores.

  python research/escaneo.py --modo intradiario
  python research/escaneo.py --modo pares --guardar
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors import market  # noqa: E402
from quant import engine, scan  # noqa: E402

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")

# Parámetros FIJOS de la estrategia (los defaults del EA). No se tocan entre corridas.
PARAMS = dict(ventana=250, entrada=1.5, salida=0.5, stop=3.0, max_hold_hl=3.0,
              usar_regimen=True, refit=5)

INSTRUMENTOS = [
    ("EURUSD=X", "FX"), ("GBPUSD=X", "FX"), ("USDJPY=X", "FX"),
    ("BTC-USD", "Crypto"), ("ETH-USD", "Crypto"),
    ("ES=F", "Futuro"), ("NQ=F", "Futuro"), ("CL=F", "Futuro"), ("GC=F", "Futuro"),
    ("SPY", "ETF"), ("QQQ", "ETF"), ("IWM", "ETF"),
]

# Costo por cambio de posición, en puntos básicos. Es lo que decide si algo sobrevive:
# a 5 minutos se opera cientos de veces y el costo se multiplica por la frecuencia.
COSTO_BASE = 1.0
COSTOS_SENSIBILIDAD = [0.0, 1.0, 2.0, 5.0]

PARES = [("EWA", "EWC"), ("KO", "PEP"), ("GLD", "SLV"), ("XOM", "CVX"), ("HD", "LOW"),
         ("MA", "V"), ("JPM", "BAC"), ("UPS", "FDX"), ("CAT", "DE"), ("COST", "WMT"),
         ("QQQ", "SPY"), ("IWM", "SPY"), ("GS", "MS"), ("AAPL", "MSFT"), ("PG", "CL"),
         ("T", "VZ"), ("MCD", "YUM"), ("USO", "XLE"), ("TGT", "WMT"), ("LIN", "APD")]


_CACHE: dict[tuple[str, str], tuple[list[float], list[int]]] = {}


def serie(symbol: str, tf: str) -> tuple[list[float], list[int]]:
    """Cierres y timestamps de un instrumento en el timeframe pedido.

    Cachea en memoria: el barrido de costos recorre el mismo universo varias veces y
    no tiene sentido volver a bajar (ni castigar al feed gratuito) cada vez.
    """
    clave = (symbol, tf)
    if clave in _CACHE:
        return _CACHE[clave]
    if tf == "1h":
        h = market.history(symbol, "2y", interval="1h")
    else:
        h = market.intraday(symbol, tf)
    pts = [p for p in h.get("points", []) if p["c"] and p["c"] > 0]
    res = ([p["c"] for p in pts], [p["t"] for p in pts])
    _CACHE[clave] = res
    time.sleep(0.3)   # sólo al bajar de verdad
    return res


def modo_intradiario(costo: float, sensibilidad: bool, gate: bool = False) -> dict:
    filas: list[dict] = []
    print(f"Gate de Dickey-Fuller: {'ACTIVADO' if gate else 'desactivado'} · "
          f"costo {costo} bps · parámetros fijos {PARAMS}\n")
    print(f"{'instrumento':<14}{'tf':>5}{'barras':>8}{'años':>7}{'Sharpe':>9}{'t':>7}"
          f"{'p':>8}{'trades':>8}{'expo%':>7}{'gate%':>7}{'B&H':>8}")
    print("-" * 88)
    for tf in ("5m", "15m", "30m", "1h"):
        for symbol, clase in INSTRUMENTOS:
            px, ts = serie(symbol, tf)
            if len(px) < PARAMS["ventana"] + 60:
                print(f"{symbol:<14}{tf:>5}{len(px):>8}   sin barras suficientes")
                continue
            r = scan.evaluar(px, ts, f"{symbol} {tf}", cost_bps=costo,
                             exigir_estacionaria=gate, **PARAMS)
            if r is None:
                continue
            r["symbol"], r["clase"], r["timeframe"] = symbol, clase, tf
            filas.append(r)
            print(f"{symbol:<14}{tf:>5}{r['n_barras']:>8}{r['anios']:>7.2f}"
                  f"{r['sharpe']:>9.2f}{r['t_stat']:>7.2f}{r['p_valor']:>8.3f}"
                  f"{r['trades']:>8}{r['exposicion_pct']:>7.1f}{r['gate_pasa_pct']:>7.1f}"
                  f"{(r['bh_sharpe'] or 0):>8.2f}")

    resumen = scan.resumir(filas)
    _imprimir_resumen(resumen, costo)

    sens = {}
    if sensibilidad:
        print("\nSensibilidad al costo (mismo universo, sólo cambia el costo):")
        print(f"  {'costo':>7}{'Sharpe medio':>15}{'positivos':>12}{'trades tot':>12}")
        for c in COSTOS_SENSIBILIDAD:
            sub = []
            for f in filas:
                px, ts = serie(f["symbol"], f["timeframe"])
                rr = scan.evaluar(px, ts, f["etiqueta"], cost_bps=c,
                                  exigir_estacionaria=gate, **PARAMS)
                if rr:
                    sub.append(rr)
            rs = scan.resumir(sub)
            tot = sum(x["trades"] for x in sub)
            sens[str(c)] = {"resumen": rs, "trades": tot}
            print(f"  {c:>7.1f}{rs['sharpe_medio']:>15.3f}"
                  f"{rs['positivos']:>8}/{rs['n']:<4}{tot:>12}")

    return {"modo": "intradiario", "costo_bps": costo, "gate_estacionariedad": gate,
            "params": PARAMS, "filas": filas, "resumen": resumen,
            "sensibilidad_costo": sens}


def modo_pares() -> dict:
    filas: list[dict] = []
    print(f"{'par':<12}{'coint':>7}{'EG':>8}{'half-life':>11}{'Sharpe':>9}{'t':>7}"
          f"{'p':>8}{'retorno':>10}{'trades':>8}")
    print("-" * 82)
    for a, b in PARES:
        r = engine.analyze_pair(a, b, rng="5y")
        time.sleep(0.3)
        if not r.get("ok"):
            print(f"{a + '/' + b:<12} {r.get('motivo', '')[:50]}")
            continue
        bt = r.get("backtest", {})
        if not bt.get("ok"):
            continue
        m = bt["metricas"]
        sh = m.get("sharpe") or 0.0
        t, p = scan.sharpe_pvalue(sh, m["n"], 252.0)
        fila = {"etiqueta": f"{a}/{b}", "cointegrado": r["engle_granger"]["cointegrado_5pct"],
                "eg_stat": r["engle_granger"]["estadistico"],
                "half_life": r["ou"].get("half_life_dias"), "beta": r["hedge_ratio_beta"],
                "sharpe": sh, "t_stat": round(t, 2), "p_valor": p,
                "retorno_pct": m["retorno_total_pct"], "trades": m["trades"],
                "n_barras": m["n"], "anios": round(m["n"] / 252.0, 2)}
        filas.append(fila)
        print(f"{fila['etiqueta']:<12}{'SI' if fila['cointegrado'] else 'no':>7}"
              f"{fila['eg_stat']:>8.2f}{(fila['half_life'] or 0):>11.1f}{sh:>9.2f}"
              f"{t:>7.2f}{p:>8.3f}{fila['retorno_pct']:>9.1f}%{fila['trades']:>8}")

    resumen = scan.resumir(filas)
    resumen["cointegrados"] = sum(1 for f in filas if f["cointegrado"])
    resumen["cointegrados_esperados_por_azar"] = round(0.05 * len(filas), 1)
    _imprimir_resumen(resumen, None)
    if filas:
        print(f"  Cointegrados al 5%: {resumen['cointegrados']} de {len(filas)} "
              f"(esperados sólo por azar: {resumen['cointegrados_esperados_por_azar']})")
    return {"modo": "pares", "params": PARAMS, "filas": filas, "resumen": resumen}


def _imprimir_resumen(r: dict, costo: float | None) -> None:
    if not r.get("n"):
        print("\nSin resultados.")
        return
    print(f"\nResumen de {r['n']} pruebas"
          + (f" (costo {costo} bps):" if costo is not None else ":"))
    print(f"  Sharpe medio {r['sharpe_medio']:+.3f} · desvío {r['sharpe_desvio']:.3f} "
          f"· t de la media {r['t_de_la_media']:+.2f}  (|t|>2 para significar)")
    print(f"  Positivos: {r['positivos']}/{r['n']}")
    print(f"  p<0.05 nominal: {r['nominales_5pct']} · esperados sólo por azar: "
          f"{r['esperados_por_azar']}")
    print(f"  Sobreviven Bonferroni (p<{r['umbral_bonferroni']:.4f}): "
          f"{r['sobreviven_bonferroni']}")
    print(f"  Sobreviven Benjamini-Hochberg (FDR 5%): {r['sobreviven_bh']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Escaneos sistemáticos de reversión a la media")
    ap.add_argument("--modo", choices=["pares", "intradiario"], required=True)
    ap.add_argument("--costo-bps", type=float, default=COSTO_BASE)
    ap.add_argument("--gate", action="store_true",
                    help="Operar sólo donde Dickey-Fuller rechaza al 5% (como los EAs)")
    ap.add_argument("--sensibilidad", action="store_true",
                    help="Repetir el escaneo intradiario a 0/1/2/5 bps")
    ap.add_argument("--guardar", action="store_true", help="Volcar el resultado a JSON")
    args = ap.parse_args()

    inicio = datetime.now(tz=timezone.utc)
    if args.modo == "pares":
        res = modo_pares()
    else:
        res = modo_intradiario(args.costo_bps, args.sensibilidad, args.gate)
    res["corrido_utc"] = inicio.isoformat(timespec="seconds")

    if args.guardar:
        os.makedirs(SALIDA, exist_ok=True)
        sufijo = "_gate" if (args.modo == "intradiario" and args.gate) else ""
        ruta = os.path.join(SALIDA, f"escaneo_{args.modo}{sufijo}.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"\nGuardado en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
