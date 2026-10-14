"""Niveles derivados de la cadena de opciones: muros, max pain y gamma.

**Lo que esto NO es.** No es *option flow* en el sentido estricto: barridos, bloques y
clasificación por lado agresor necesitan el feed de ticks de CME u OPRA, que es pago. Acá
no hay nada de eso y conviene saberlo antes de mirar un número.

**Lo que sí es.** Yahoo no publica cadena para `ES=F` ni `NQ=F`, pero sí para `^SPX` y
`^NDX` — que son el MISMO subyacente que esos futuros. Las opciones de índice son además
un mercado más grande que las de futuros, así que el posicionamiento que mueve al índice
está ahí. De esa cadena salen:

  · **Muro de calls / muro de puts**: los strikes con más interés abierto por encima y por
    debajo del precio. Son los niveles donde el mercado tiene más contratos vivos.
  · **Max pain**: el strike donde vencería sin valor la mayor cantidad de contratos. No es
    una predicción; es dónde más le duele al comprador de opciones.
  · **Exposición a gamma (GEX)** por strike y **nivel de gamma cero**: dónde se da vuelta
    el signo de la cobertura de los creadores de mercado. Por encima, cubrir amortigua el
    movimiento; por debajo, lo amplifica.
  · **Concentración de volumen del día**: lo más cercano a "flujo" que se consigue gratis.
    El volumen es actividad de HOY; el interés abierto es lo que quedó de ayer.

Las griegas no vienen en el feed: la gamma se calcula con Black-Scholes a partir de la
volatilidad implícita que sí viene. Para los vencimientos del día el tiempo a vencimiento
se acota por abajo, porque con T→0 la gamma se va al infinito y el número deja de
significar algo.

Los strikes se traducen a puntos del futuro con la base (futuro/índice), que incorpora
tasa y dividendos. El `^SPX` cotiza unos puntos por debajo del `ES` y hay que corregirlo o
todos los niveles quedan desplazados.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

# Mapa futuro -> índice con cadena de opciones. MNQ y NQ comparten precio: el micro es
# 1/10 del mini, cambia el tamaño del contrato, no la cotización.
SUBYACENTE = {
    "ES=F": "^SPX", "MES=F": "^SPX",
    "NQ=F": "^NDX", "MNQ=F": "^NDX",
}

PISO_T = 1.0 / (365.0 * 12.0)   # dos horas: cota inferior del tiempo a vencimiento
TASA = 0.04                     # tasa libre de riesgo aproximada, sólo para d1


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def gamma_bs(spot: float, strike: float, iv: float, t_anios: float,
             tasa: float = TASA) -> float:
    """Gamma de Black-Scholes. `iv` en tanto por uno (0.16, no 16)."""
    if spot <= 0 or strike <= 0 or iv <= 0:
        return 0.0
    t = max(t_anios, PISO_T)
    raiz = iv * math.sqrt(t)
    if raiz <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (tasa + 0.5 * iv * iv) * t) / raiz
    return _norm_pdf(d1) / (spot * raiz)


def _anios_a_vencimiento(ts_exp: int, ahora: int | None = None) -> float:
    ahora = ahora or int(datetime.now(tz=timezone.utc).timestamp())
    return max((ts_exp - ahora) / (365.0 * 86400.0), PISO_T)


def agregar_por_strike(cadenas: list[dict], spot: float,
                       ahora: int | None = None) -> dict[float, dict]:
    """Suma interés abierto, volumen y gamma por strike, sobre varios vencimientos."""
    por_strike: dict[float, dict] = {}
    for cad in cadenas:
        if cad.get("status") != "ok":
            continue
        exp = cad.get("selected_expiration")
        t = _anios_a_vencimiento(exp, ahora) if exp else PISO_T
        for lado, filas in (("call", cad.get("calls", [])), ("put", cad.get("puts", []))):
            for r in filas:
                k = r.get("strike")
                if not k:
                    continue
                d = por_strike.setdefault(k, {"strike": k, "oi_call": 0, "oi_put": 0,
                                              "vol_call": 0, "vol_put": 0,
                                              "gamma_call": 0.0, "gamma_put": 0.0,
                                              "iv_call": None, "iv_put": None})
                oi = r.get("open_interest") or 0
                vol = r.get("volume") or 0
                iv = (r.get("iv") or 0) / 100.0
                g = gamma_bs(spot, k, iv, t)
                d[f"oi_{lado}"] += oi
                d[f"vol_{lado}"] += vol
                d[f"gamma_{lado}"] += g * oi
                if iv > 0 and d[f"iv_{lado}"] is None:
                    d[f"iv_{lado}"] = round(iv * 100, 2)
    return por_strike


def max_pain(por_strike: dict[float, dict]) -> float | None:
    """Strike que deja sin valor la mayor cantidad de contratos al vencimiento.

    Para cada strike candidato se calcula cuánto pagarían los vendedores si el subyacente
    terminara ahí; el mínimo de esa suma es el max pain.
    """
    strikes = sorted(por_strike)
    if len(strikes) < 3:
        return None
    mejor, menor = None, float("inf")
    for s in strikes:
        dolor = 0.0
        for k in strikes:
            d = por_strike[k]
            if k < s:
                dolor += (s - k) * d["oi_call"]     # calls en el dinero
            elif k > s:
                dolor += (k - s) * d["oi_put"]      # puts en el dinero
        if dolor < menor:
            mejor, menor = s, dolor
    return mejor


def gex_por_strike(por_strike: dict[float, dict], spot: float,
                   multiplicador: float = 100.0) -> list[dict]:
    """Exposición a gamma por strike, en dólares por cada 1% de movimiento.

    Convención habitual: los creadores de mercado quedan largos de gamma en los calls que
    les venden al público y cortos en los puts. GEX positivo = cubrir amortigua el
    movimiento; negativo = lo amplifica.
    """
    out = []
    for k in sorted(por_strike):
        d = por_strike[k]
        g = (d["gamma_call"] - d["gamma_put"]) * multiplicador * spot * spot * 0.01
        out.append({**d, "gex": g})
    return out


def gamma_cero(por_strike: dict[float, dict], spot: float, rango_pct: float = 8.0,
               pasos: int = 160, ahora: int | None = None,
               ivs: dict | None = None) -> float | None:
    """Nivel de precio donde la gamma total cambia de signo (el "gamma flip").

    Se recalcula la gamma de toda la cadena suponiendo distintos precios del subyacente y
    se busca el cruce por cero. Es una aproximación: usa la volatilidad implícita de hoy
    como si no cambiara al moverse el precio, cosa que no es cierta.
    """
    strikes = sorted(por_strike)
    if len(strikes) < 5:
        return None
    lo, hi = spot * (1 - rango_pct / 100.0), spot * (1 + rango_pct / 100.0)
    anterior = None
    for i in range(pasos + 1):
        s = lo + (hi - lo) * i / pasos
        total = 0.0
        for k in strikes:
            d = por_strike[k]
            iv_c = (d.get("iv_call") or 20.0) / 100.0
            iv_p = (d.get("iv_put") or 20.0) / 100.0
            t = (ivs or {}).get("t", PISO_T * 20)
            total += (gamma_bs(s, k, iv_c, t) * d["oi_call"]
                      - gamma_bs(s, k, iv_p, t) * d["oi_put"])
        if anterior is not None and (anterior[1] < 0 <= total or anterior[1] >= 0 > total):
            # interpolación lineal entre los dos precios que rodean al cruce
            s0, v0 = anterior
            return s0 + (s - s0) * (0 - v0) / (total - v0) if total != v0 else s
        anterior = (s, total)
    return None


def analizar(cadenas: list[dict], spot_indice: float, spot_futuro: float,
             top: int = 6, ahora: int | None = None, rango_pct: float = 5.0) -> dict:
    """Tablero de niveles de opciones, con los strikes traducidos a puntos del futuro.

    `rango_pct` acota los muros y la concentración de volumen a los strikes dentro de ese
    porcentaje del precio. Sin ese filtro el "muro de puts" se va a una cobertura de largo
    plazo a 1.500 puntos de distancia, que es un dato real y completamente inútil para
    operar la sesión. Los ratios put/call sí se calculan sobre la cadena entera.
    """
    por_strike = agregar_por_strike(cadenas, spot_indice, ahora)
    if not por_strike:
        return {"ok": False, "motivo": "No se pudo leer la cadena de opciones."}

    base = spot_futuro / spot_indice if spot_indice else 1.0
    gex = gex_por_strike(por_strike, spot_indice)
    mp = max_pain(por_strike)
    g0 = gamma_cero(por_strike, spot_indice, ahora=ahora)

    lo = spot_indice * (1 - rango_pct / 100.0)
    hi = spot_indice * (1 + rango_pct / 100.0)
    cerca = [d for d in gex if lo <= d["strike"] <= hi]
    arriba = [d for d in cerca if d["strike"] > spot_indice]
    abajo = [d for d in cerca if d["strike"] < spot_indice]
    muro_call = max(arriba, key=lambda d: d["oi_call"], default=None)
    muro_put = max(abajo, key=lambda d: d["oi_put"], default=None)

    def a_futuro(k):
        return round(k * base, 2) if k else None

    niveles = []
    if muro_call:
        niveles.append({"nombre": "Muro de calls", "strike": muro_call["strike"],
                        "precio": a_futuro(muro_call["strike"]), "tipo": "resistencia",
                        "dato": f"{muro_call['oi_call']:,} contratos de interés abierto",
                        "nota": "Mayor interés abierto en calls por encima del precio: "
                                "la cobertura de los vendedores frena la suba."})
    if muro_put:
        niveles.append({"nombre": "Muro de puts", "strike": muro_put["strike"],
                        "precio": a_futuro(muro_put["strike"]), "tipo": "soporte",
                        "dato": f"{muro_put['oi_put']:,} contratos de interés abierto",
                        "nota": "Mayor interés abierto en puts por debajo del precio."})
    if mp:
        niveles.append({"nombre": "Max pain", "strike": mp, "precio": a_futuro(mp),
                        "tipo": "referencia",
                        "dato": "mínimo del valor intrínseco total",
                        "nota": "Dónde vencería sin valor la mayor cantidad de contratos. "
                                "No es una predicción."})
    if g0:
        niveles.append({"nombre": "Gamma cero", "strike": round(g0, 2),
                        "precio": a_futuro(g0), "tipo": "referencia",
                        "dato": "cruce de signo de la gamma total",
                        "nota": "Por encima, la cobertura amortigua el movimiento; "
                                "por debajo lo amplifica."})

    for n in niveles:
        if n["precio"]:
            n["distancia"] = round(n["precio"] - spot_futuro, 2)
    niveles.sort(key=lambda n: -(n["precio"] or 0))

    gex_total = sum(d["gex"] for d in gex)
    oi_c = sum(d["oi_call"] for d in gex)
    oi_p = sum(d["oi_put"] for d in gex)
    vol_c = sum(d["vol_call"] for d in gex)
    vol_p = sum(d["vol_put"] for d in gex)

    def top_por(clave, lado):
        filas = sorted(cerca, key=lambda d: -d[clave])[:top]
        return [{"strike": d["strike"], "precio_futuro": a_futuro(d["strike"]),
                 "valor": d[clave], "lado": lado,
                 "distancia": round(a_futuro(d["strike"]) - spot_futuro, 2)}
                for d in filas if d[clave] > 0]

    return {
        "ok": True,
        "spot_indice": round(spot_indice, 2),
        "spot_futuro": round(spot_futuro, 2),
        "base": round(base, 5),
        "niveles": niveles,
        "gex_total": round(gex_total / 1e9, 3),          # miles de millones por 1%
        "regimen_gamma": "positiva (movimiento amortiguado)" if gex_total > 0
                         else "negativa (movimiento amplificado)",
        "oi_calls": oi_c, "oi_puts": oi_p,
        "ratio_put_call_oi": round(oi_p / oi_c, 3) if oi_c else None,
        "vol_calls": vol_c, "vol_puts": vol_p,
        "ratio_put_call_vol": round(vol_p / vol_c, 3) if vol_c else None,
        "top_volumen_calls": top_por("vol_call", "call"),
        "top_volumen_puts": top_por("vol_put", "put"),
        "top_oi_calls": top_por("oi_call", "call"),
        "top_oi_puts": top_por("oi_put", "put"),
        "n_strikes": len(por_strike),
        "n_strikes_cerca": len(cerca),
        "rango_pct": rango_pct,
        "vencimientos": sorted({c.get("selected_expiration") for c in cadenas
                                if c.get("status") == "ok" and c.get("selected_expiration")}),
    }
