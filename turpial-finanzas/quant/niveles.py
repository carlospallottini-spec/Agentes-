"""Niveles de precio clave por sesión, para futuros de índices (ES, NQ/MNQ).

Los niveles que un operador de sesión mira al abrir la pantalla, calculados desde velas
intradía. Todos salen de datos ya cerrados: ninguno usa información posterior al momento
en que se publica.

  · **Sesión RTH previa** (9:30-16:00 ET): máximo, mínimo y cierre. El cierre de ayer es
    la referencia del hueco y el imán más citado de la apertura.
  · **Globex / overnight** (18:00 ET de ayer a 9:30 de hoy): máximo y mínimo. Romper el
    extremo nocturno es la señal de continuación más limpia de la apertura.
  · **Rango de apertura** (primeros N minutos): el "initial balance" del perfil de mercado.
  · **VWAP de sesión**: precio medio ponderado por volumen desde la apertura RTH.
  · **Pivotes de piso**: PP = (H+L+C)/3 y sus soportes y resistencias. Son aritmética pura
    sobre la sesión previa; su valor es que mucha gente los mira, no que predigan.
  · **Rango esperado por ATR**: apertura ± ATR de sesión, como cota de lo "normal".

Sobre el horario: los futuros de CME cotizan casi 23 horas, así que "la sesión" hay que
definirla. Acá RTH es 9:30-16:00 hora de Nueva York, con horario de verano resuelto por
las reglas de Estados Unidos (segundo domingo de marzo, primer domingo de noviembre).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

RTH_INICIO = time(9, 30)
RTH_FIN = time(16, 0)
GLOBEX_INICIO = time(18, 0)


def _nth_sunday(anio: int, mes: int, n: int) -> int:
    """Día del mes del n-ésimo domingo (para las reglas de horario de verano)."""
    d = datetime(anio, mes, 1)
    return 1 + ((6 - d.weekday()) % 7) + 7 * (n - 1)


def offset_ny(ts: int) -> int:
    """Horas de diferencia de Nueva York respecto de UTC: -4 en verano, -5 en invierno."""
    u = datetime.fromtimestamp(ts, tz=timezone.utc)
    if u.month < 3 or u.month > 11:
        return -5
    if 3 < u.month < 11:
        return -4
    if u.month == 3:
        inicio = _nth_sunday(u.year, 3, 2)
        return -4 if (u.day > inicio or (u.day == inicio and u.hour >= 7)) else -5
    fin = _nth_sunday(u.year, 11, 1)
    return -4 if (u.day < fin or (u.day == fin and u.hour < 6)) else -5


def hora_ny(ts: int) -> datetime:
    """Convierte un timestamp a hora de Nueva York."""
    return datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=offset_ny(ts))


def _ohlcv(barras: list[dict]) -> dict | None:
    """Agrega una lista de velas en un solo OHLCV."""
    barras = [b for b in barras if b.get("c")]
    if not barras:
        return None
    altos = [b.get("h", b["c"]) for b in barras]
    bajos = [b.get("l", b["c"]) for b in barras]
    return {"o": barras[0].get("o", barras[0]["c"]), "h": max(altos), "l": min(bajos),
            "c": barras[-1]["c"], "v": sum(b.get("v", 0) or 0 for b in barras),
            "n": len(barras),
            "desde": barras[0]["t"], "hasta": barras[-1]["t"]}


def agrupar_sesiones(barras: list[dict]) -> list[dict]:
    """Parte las velas en sesiones de mercado, separando RTH de la rueda nocturna.

    Cada sesión es un día de negociación de NY: la rueda de Globex que arranca a las 18:00
    del día anterior y el RTH de 9:30 a 16:00. Lo que pasa entre 16:00 y 18:00 (la pausa
    de mantenimiento) se descarta.
    """
    por_dia: dict[str, dict[str, list[dict]]] = {}
    for b in barras:
        if not b.get("c"):
            continue
        ny = hora_ny(b["t"])
        t = ny.time()
        if RTH_INICIO <= t < RTH_FIN:
            dia, tramo = ny.date().isoformat(), "rth"
        elif t >= GLOBEX_INICIO:
            # La rueda nocturna pertenece al día de negociación SIGUIENTE.
            dia, tramo = (ny.date() + timedelta(days=1)).isoformat(), "globex"
        elif t < RTH_INICIO:
            dia, tramo = ny.date().isoformat(), "globex"
        else:
            continue   # 16:00-18:00: pausa
        por_dia.setdefault(dia, {"rth": [], "globex": []})[tramo].append(b)

    out = []
    for dia in sorted(por_dia):
        d = por_dia[dia]
        rth, glx = _ohlcv(d["rth"]), _ohlcv(d["globex"])
        if rth is None and glx is None:
            continue
        out.append({"dia": dia, "rth": rth, "globex": glx, "barras_rth": d["rth"]})
    return out


def vwap(barras: list[dict]) -> float | None:
    """VWAP: suma(precio típico × volumen) / suma(volumen).

    Si el feed no trae volumen devuelve None en vez de inventar un promedio simple: un
    VWAP sin volumen no es un VWAP y confundirlo es peor que no tenerlo.
    """
    num = den = 0.0
    for b in barras:
        v = b.get("v") or 0
        if v <= 0:
            continue
        tipico = (b.get("h", b["c"]) + b.get("l", b["c"]) + b["c"]) / 3.0
        num += tipico * v
        den += v
    return num / den if den > 0 else None


def rango_apertura(barras_rth: list[dict], minutos: int = 30) -> dict | None:
    """Initial balance: máximo y mínimo de los primeros `minutos` del RTH."""
    if not barras_rth:
        return None
    inicio = barras_rth[0]["t"]
    tramo = [b for b in barras_rth if b["t"] < inicio + minutos * 60]
    ag = _ohlcv(tramo)
    if ag is None:
        return None
    return {"minutos": minutos, "alto": ag["h"], "bajo": ag["l"],
            "rango": round(ag["h"] - ag["l"], 2), "barras": ag["n"]}


def pivotes(alto: float, bajo: float, cierre: float) -> dict:
    """Pivotes de piso clásicos sobre la sesión previa.

    Es aritmética, no predicción: valen porque mucha gente los mira, no porque el mercado
    los respete por alguna razón estructural.
    """
    pp = (alto + bajo + cierre) / 3.0
    rango = alto - bajo
    return {"PP": pp,
            "R1": 2 * pp - bajo, "S1": 2 * pp - alto,
            "R2": pp + rango, "S2": pp - rango,
            "R3": alto + 2 * (pp - bajo), "S3": bajo - 2 * (alto - pp)}


def atr_sesiones(sesiones: list[dict], periodo: int = 14) -> float | None:
    """ATR sobre los RTH de las sesiones previas (true range contra el cierre anterior)."""
    rth = [s["rth"] for s in sesiones if s.get("rth")]
    if len(rth) < periodo + 1:
        return None
    suma = 0.0
    for k in range(1, periodo + 1):
        s, prev = rth[-k], rth[-k - 1]
        suma += max(s["h"] - s["l"], abs(s["h"] - prev["c"]), abs(s["l"] - prev["c"]))
    return suma / periodo


def niveles_sesion(barras: list[dict], minutos_apertura: int = 30,
                   periodo_atr: int = 14) -> dict:
    """Arma el tablero de niveles de la sesión en curso (o la última disponible)."""
    sesiones = agrupar_sesiones(barras)
    if len(sesiones) < 2:
        return {"ok": False, "motivo": "No hay suficientes sesiones para calcular niveles."}

    hoy, ayer = sesiones[-1], sesiones[-2]
    prev = ayer["rth"]
    if prev is None:
        return {"ok": False, "motivo": "La sesión previa no tiene datos de RTH."}

    ultimo = barras[-1]["c"]
    atr = atr_sesiones(sesiones[:-1], periodo_atr)
    piv = pivotes(prev["h"], prev["l"], prev["c"])
    rth_hoy = hoy.get("rth")
    glx_hoy = hoy.get("globex")
    apertura = rth_hoy["o"] if rth_hoy else None

    niveles = [
        {"nombre": "Cierre RTH previo", "precio": prev["c"], "tipo": "referencia",
         "nota": "La referencia del hueco. Cerrarlo es el objetivo más citado de la apertura."},
        {"nombre": "Máximo RTH previo", "precio": prev["h"], "tipo": "resistencia",
         "nota": "Techo de la sesión anterior."},
        {"nombre": "Mínimo RTH previo", "precio": prev["l"], "tipo": "soporte",
         "nota": "Piso de la sesión anterior."},
    ]
    if glx_hoy:
        niveles += [
            {"nombre": "Máximo Globex", "precio": glx_hoy["h"], "tipo": "resistencia",
             "nota": "Techo de la rueda nocturna; romperlo es continuación."},
            {"nombre": "Mínimo Globex", "precio": glx_hoy["l"], "tipo": "soporte",
             "nota": "Piso de la rueda nocturna."},
        ]
    v = vwap(hoy.get("barras_rth") or [])
    if v:
        niveles.append({"nombre": "VWAP de sesión", "precio": v, "tipo": "referencia",
                        "nota": "Precio medio ponderado por volumen desde la apertura."})
    ib = rango_apertura(hoy.get("barras_rth") or [], minutos_apertura)
    if ib:
        niveles += [
            {"nombre": f"Alto rango apertura ({ib['minutos']}m)", "precio": ib["alto"],
             "tipo": "resistencia", "nota": "Techo del initial balance."},
            {"nombre": f"Bajo rango apertura ({ib['minutos']}m)", "precio": ib["bajo"],
             "tipo": "soporte", "nota": "Piso del initial balance."},
        ]
    for k, p in piv.items():
        niveles.append({"nombre": f"Pivote {k}", "precio": p,
                        "tipo": "referencia" if k == "PP" else
                                ("resistencia" if k.startswith("R") else "soporte"),
                        "nota": "Pivote de piso sobre la sesión previa."})
    if atr and apertura:
        niveles += [
            {"nombre": "Techo esperado (apertura + ATR)", "precio": apertura + atr,
             "tipo": "resistencia", "nota": f"ATR de sesión = {atr:.1f} puntos."},
            {"nombre": "Piso esperado (apertura − ATR)", "precio": apertura - atr,
             "tipo": "soporte", "nota": f"ATR de sesión = {atr:.1f} puntos."},
        ]

    for n in niveles:
        n["precio"] = round(n["precio"], 2)
        n["distancia"] = round(n["precio"] - ultimo, 2)
        n["distancia_pct"] = round((n["precio"] - ultimo) / ultimo * 100, 3)
    niveles.sort(key=lambda n: -n["precio"])

    return {
        "ok": True,
        "ultimo": round(ultimo, 2),
        "actualizado": hora_ny(barras[-1]["t"]).isoformat(timespec="minutes"),
        "sesion": hoy["dia"],
        "sesion_previa": ayer["dia"],
        "rth_previo": {k: round(prev[k], 2) for k in ("o", "h", "l", "c")},
        "globex": ({k: round(glx_hoy[k], 2) for k in ("o", "h", "l", "c")}
                   if glx_hoy else None),
        "rth_hoy": ({k: round(rth_hoy[k], 2) for k in ("o", "h", "l", "c")}
                    if rth_hoy else None),
        "hueco_puntos": (round(apertura - prev["c"], 2) if apertura else None),
        "hueco_pct": (round((apertura - prev["c"]) / prev["c"] * 100, 3)
                      if apertura else None),
        "atr_sesion": round(atr, 2) if atr else None,
        "rango_apertura": ib,
        "vwap": round(v, 2) if v else None,
        "niveles": niveles,
        "n_sesiones": len(sesiones),
    }
