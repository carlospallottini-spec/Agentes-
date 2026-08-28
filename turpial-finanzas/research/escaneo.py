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
COSTO_PARES = 2.0   # dos patas: el costo se paga dos veces por trade
COSTOS_SENSIBILIDAD = [0.0, 1.0, 2.0, 5.0]

# Pares por clase de activo. Cada uno tiene una RAZÓN económica: no se prueban todas
# las combinaciones posibles, que sería minería de datos disfrazada de escaneo.
# Los marcados MECÁNICO comparten subyacente y sólo cambia el envoltorio — funcionan como
# control interno del test de cointegración: si ahí no aparece, el test está roto.
PARES_POR_CLASE = {
    "divisas": [
        ("AUDUSD=X", "NZDUSD=X", "commodity currencies de economías vecinas"),
        ("EURUSD=X", "GBPUSD=X", "majors europeas contra el dólar"),
        ("EURUSD=X", "USDCHF=X", "euro y franco, misma región, cotización inversa"),
        ("USDNOK=X", "USDSEK=X", "escandinavas"),
        ("EURJPY=X", "GBPJPY=X", "europeas contra el yen"),
        ("AUDJPY=X", "NZDJPY=X", "commodity currencies contra el yen"),
        ("CADJPY=X", "AUDJPY=X", "commodity currencies contra el yen"),
        ("EURCHF=X", "EURUSD=X", "el franco pegado al euro"),
        ("USDCAD=X", "AUDUSD=X", "ambas ligadas a materias primas"),
        ("EURGBP=X", "EURUSD=X", "descomposición del cruce"),
        ("EURAUD=X", "AUDUSD=X", "descomposición del cruce"),
        ("GBPJPY=X", "USDJPY=X", "misma pata en yenes"),
    ],
    "indices": [
        ("EWJ", "^N225", "MECÁNICO: Japón, ETF contra índice"),
        ("^FTSE", "EWU", "MECÁNICO: Reino Unido, índice contra ETF"),
        ("SPY", "^GSPC", "MECÁNICO: S&P 500, ETF contra índice"),
        ("QQQ", "^NDX", "MECÁNICO: Nasdaq 100, ETF contra índice"),
        ("SPY", "QQQ", "large caps contra tecnología"),
        ("SPY", "IWM", "large caps contra small caps"),
        ("SPY", "DIA", "S&P contra Dow"),
        ("^GDAXI", "^FCHI", "DAX y CAC: misma moneda y ciclo"),
        ("EWG", "EWU", "Alemania contra Reino Unido"),
        ("EWA", "EWC", "Australia contra Canadá"),
        ("SPY", "EFA", "EE.UU. contra desarrollados internacionales"),
        ("EEM", "EWZ", "emergentes contra Brasil"),
    ],
    "materias_primas": [
        ("CL=F", "BZ=F", "WTI y Brent: el mismo crudo en dos puntos de entrega"),
        ("GC=F", "GLD", "MECÁNICO: oro, futuro contra ETF"),
        ("SI=F", "SLV", "MECÁNICO: plata, futuro contra ETF"),
        ("CL=F", "USO", "MECÁNICO-ish: crudo, futuro contra ETF (el ETF sufre el roll)"),
        ("GC=F", "SI=F", "oro y plata"),
        ("GC=F", "PL=F", "oro y platino"),
        ("HO=F", "CL=F", "crack spread: destilado contra crudo"),
        ("RB=F", "CL=F", "crack spread: nafta contra crudo"),
        ("ZC=F", "ZS=F", "maíz y soja: compiten por hectáreas"),
        ("ZW=F", "ZC=F", "trigo y maíz: sustitutos forrajeros"),
        ("HG=F", "GC=F", "cobre e industria contra oro y refugio"),
        ("PA=F", "PL=F", "paladio y platino: sustitutos en catalizadores"),
        ("CL=F", "XLE", "crudo contra acciones energéticas"),
    ],
}

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


def modo_clases(costo: float, anios_primario: int, anios_control: int,
                vix: tuple | None) -> dict:
    """Cointegración por clase de activo: divisas, luego índices, luego materias primas.

    El análisis PRIMARIO es a `anios_primario` años (más potencia); el otro horizonte
    queda como chequeo de robustez. La corrección por multiplicidad se aplica dentro del
    primario, que es donde se saca la conclusión — corregir sobre los dos horizontes
    juntos sería tratar como independientes dos muestras que se solapan.
    """
    from quant import regimen_vol

    print(f"Costo {costo} bps por cambio de posición (se cobra en las dos patas).")
    print(f"Análisis primario: {anios_primario} años · robustez: {anios_control} años\n")

    todo: dict[str, dict] = {}
    for anios in (anios_primario, anios_control):
        rng = f"{anios}y"
        primario = anios == anios_primario
        print("=" * 96)
        print(f"HORIZONTE {anios} AÑOS" + ("   (PRIMARIO)" if primario else "   (robustez)"))
        S_min = 2 / (anios - 2) ** 0.5
        print(f"Listón: con {anios} años hace falta Sharpe >= {S_min:.2f} para t=2.\n")
        por_clase: dict[str, list[dict]] = {}

        for clase, pares in PARES_POR_CLASE.items():
            print(f"--- {clase.upper().replace('_', ' ')} ---")
            print(f"{'par':<20}{'coint':>7}{'EG':>8}{'half-life':>10}{'Sharpe':>8}"
                  f"{'t':>7}{'p':>7}{'trades':>7}{'VIX17-21':>9}  razón")
            filas = []
            for a, b, razon in pares:
                r = engine.analyze_pair(a, b, rng=rng, cost_bps=costo)
                time.sleep(0.2)
                if not r.get("ok") or not r.get("backtest", {}).get("ok"):
                    print(f"{a + '/' + b:<20} {str(r.get('motivo', 'sin backtest'))[:55]}")
                    continue
                bt = r["backtest"]
                m = bt["metricas"]
                sh = m.get("sharpe") or 0.0
                t, p = scan.sharpe_pvalue(sh, m["n"], 252.0)

                sh_banda = None
                if vix and bt.get("fechas_senal"):
                    v = regimen_vol.alinear(bt["fechas_senal"], vix[0], vix[1])
                    reg = regimen_vol.por_regimen(bt["retornos"], v)
                    if reg["medio"].get("suficiente"):
                        sh_banda = reg["medio"]["sharpe"]

                fila = {"par": f"{a}/{b}", "clase": clase, "razon": razon,
                        "mecanico": razon.startswith("MECÁNICO"),
                        "sincronia": r.get("sincronia"),
                        "sospecha_artefacto": r.get("sospecha_artefacto"),
                        "pata_no_operable": r.get("pata_no_operable"),
                        "cointegrado": r["engle_granger"]["cointegrado_5pct"],
                        "eg_stat": r["engle_granger"]["estadistico"],
                        "half_life": r["ou"].get("half_life_dias"),
                        "beta": r["hedge_ratio_beta"], "r2": r["r2_cointegracion"],
                        "sharpe": sh, "t_stat": round(t, 2), "p_valor": p,
                        "retorno_pct": m["retorno_total_pct"],
                        "max_dd_pct": m["max_drawdown_pct"], "trades": m["trades"],
                        "exposicion_pct": m["exposicion_pct"],
                        "n_barras": m["n"], "anios": round(m["n"] / 252, 2),
                        "sharpe_vix_17_21": sh_banda}
                filas.append(fila)
                marca = ("  ÍNDICE-no-operable" if fila["pata_no_operable"]
                         else ("  ARTEFACTO" if fila["sospecha_artefacto"] else ""))
                print(f"{fila['par']:<20}{'SI' if fila['cointegrado'] else 'no':>7}"
                      f"{fila['eg_stat']:>8.2f}{(fila['half_life'] or 0):>10.1f}"
                      f"{sh:>8.2f}{t:>7.2f}{p:>7.3f}{m['trades']:>7}"
                      f"{(sh_banda if sh_banda is not None else float('nan')):>9.2f}"
                      f"{marca}  {razon}")
            por_clase[clase] = filas
            if filas:
                r = scan.resumir(filas)
                print(f"   {clase}: Sharpe medio {r['sharpe_medio']:+.3f} (t={r['t_de_la_media']:+.2f}) "
                      f"· cointegrados {sum(1 for f in filas if f['cointegrado'])}/{len(filas)} "
                      f"· p<0.05 {r['nominales_5pct']} (azar {r['esperados_por_azar']})\n")

        planas = [f for fs in por_clase.values() for f in fs]
        resumen = scan.resumir(planas)
        print(f"TOTAL {anios} años — {resumen['n']} pares (TODOS, artefactos incluidos)")
        _imprimir_resumen(resumen, costo)
        mec = [f for f in planas if f["mecanico"]]
        if mec:
            print(f"  Control interno (pares MECÁNICOS): "
                  f"{sum(1 for f in mec if f['cointegrado'])}/{len(mec)} cointegrados")
        for f in planas:
            if f.get("sobrevive_bh"):
                print(f"    sobrevive: {f['par']:<20} Sharpe {f['sharpe']:+.2f} "
                      f"· p={f['p_valor']:.4f}"
                      + ("  <- ARTEFACTO, no operable" if f["sospecha_artefacto"] else "")
                      + f" · {f['razon']}")

        # El análisis que vale: sólo pares sincrónicos y con half-life de más de una barra.
        limpios = [f for f in planas if not f["sospecha_artefacto"]]
        resumen_limpio = scan.resumir(limpios)
        artefactos = len(planas) - len(limpios)
        print(f"\n  Descartados: {artefactos} (pata de índice no comprable, cierres no "
              f"sincrónicos, o half-life < 3 barras)")
        print(f"  TOTAL LIMPIO {anios} años — {resumen_limpio['n']} pares operables")
        _imprimir_resumen(resumen_limpio, costo)
        ganan_limpio = [f for f in limpios if f.get("sobrevive_bh")]
        if ganan_limpio:
            print("  Sobreviven la corrección (sólo operables):")
            for f in ganan_limpio:
                print(f"    {f['par']:<20} Sharpe {f['sharpe']:+.2f} · p={f['p_valor']:.4f} "
                      f"· {f['razon']}")
        else:
            print("  Ningún par operable sobrevive la corrección por multiplicidad.")
        print()
        todo[f"{anios}y"] = {"por_clase": por_clase, "resumen": resumen,
                             "resumen_limpio": resumen_limpio, "artefactos": artefactos,
                             "primario": primario}

    return {"modo": "clases", "costo_bps": costo, "params": PARAMS,
            "anios_primario": anios_primario, "anios_control": anios_control,
            "horizontes": todo}


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
    ap.add_argument("--modo", choices=["pares", "intradiario", "clases"], required=True)
    ap.add_argument("--anios", type=int, default=10, help="Horizonte primario del modo clases")
    ap.add_argument("--anios-control", type=int, default=5, help="Horizonte de robustez")
    ap.add_argument("--sin-vix", action="store_true", help="No condicionar por régimen de VIX")
    ap.add_argument("--costo-bps", type=float, default=COSTO_BASE)
    ap.add_argument("--gate", action="store_true",
                    help="Operar sólo donde Dickey-Fuller rechaza al 5% (como los EAs)")
    ap.add_argument("--sensibilidad", action="store_true",
                    help="Repetir el escaneo intradiario a 0/1/2/5 bps")
    ap.add_argument("--guardar", action="store_true", help="Volcar el resultado a JSON")
    args = ap.parse_args()

    inicio = datetime.now(tz=timezone.utc)
    if args.modo == "clases":
        vix = None
        if not args.sin_vix:
            h = market.velas("^VIX", "1d", max(args.anios, args.anios_control) * 365 + 60)
            pts = [p for p in h["points"] if p.get("c") and p["c"] > 0]
            vix = ([p["t"] for p in pts], [p["c"] for p in pts])
            print(f"VIX: {len(pts)} días para condicionar la banda 17-21.")
        res = modo_clases(args.costo_bps, args.anios, args.anios_control, vix)
    elif args.modo == "pares":
        res = modo_pares()
    else:
        res = modo_intradiario(args.costo_bps, args.sensibilidad, args.gate)
    res["corrido_utc"] = inicio.isoformat(timespec="seconds")

    if args.guardar:
        os.makedirs(SALIDA, exist_ok=True)
        sufijo = "_gate" if (args.modo == "intradiario" and args.gate) else ""
        if args.modo == "clases":
            sufijo = f"_{args.anios}y"
        ruta = os.path.join(SALIDA, f"escaneo_{args.modo}{sufijo}.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"\nGuardado en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
