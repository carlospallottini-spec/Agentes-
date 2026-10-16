"""Diario de operaciones, para medir si el mapa sirve de verdad.

Todo lo medido hasta acá dice que los niveles no predicen rebotes. Lo que queda sin medir
es si el mapa igual ayuda a operar mejor: tamaño de posición, dónde va el stop, cómo
comportarse según el régimen de gamma. Decir "me ayuda" sin medirlo es una sensación, y en
este proyecto las sensaciones ya mintieron dos veces.

Dos reglas de diseño que hacen la diferencia entre un diario y un relato:

1. **El plan se registra antes que el resultado.** `abrir()` guarda entrada, stop y nivel
   de referencia; `cerrar()` guarda la salida. Si las dos cosas llegan juntas, el registro
   queda marcado `post_hoc` y el análisis lo separa: un stop "elegido" después de ver cómo
   terminó el día no mide nada.

2. **Se guardan las velas de la sesión.** El feed entrega solo 8 semanas de velas de 5
   minutos. Sin guardarlas, dentro de tres meses no se puede correr el control al azar
   sobre los trades viejos. Es el mismo error que casi arruina el histórico de interés
   abierto, y acá se evita de entrada.

El resultado se normaliza en R: R = riesgo inicial = |entrada − stop|. Así un trade de 1
MNQ y uno de 3 ES son comparables.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from quant import futuros as fu
from quant import niveles as nv
from quant.stats import wilson

DIR_DATOS = "data/diario"
ARCHIVO = "operaciones.jsonl"
# Fuera de esta banda el stop está fuera del ruido de la medición. Es el mismo margen de
# resolución que usa quant/toques.py, y por eso el diario puede testear el consejo.
MARGEN_RUIDO_ATR = 0.25


def _ruta(dir_datos: str = DIR_DATOS) -> str:
    return os.path.join(dir_datos, ARCHIVO)


def leer(dir_datos: str = DIR_DATOS) -> list[dict]:
    """Todas las operaciones registradas, en orden de apertura."""
    r = _ruta(dir_datos)
    if not os.path.exists(r):
        return []
    out = []
    with open(r, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                out.append(json.loads(linea))
            except json.JSONDecodeError:
                continue          # una línea rota no tira abajo el diario entero
    out.sort(key=lambda o: o.get("abierta_en") or "")
    return out


def _escribir(ops: list[dict], dir_datos: str = DIR_DATOS) -> None:
    r = _ruta(dir_datos)
    os.makedirs(os.path.dirname(r), exist_ok=True)
    with open(r, "w", encoding="utf-8") as f:
        for o in ops:
            f.write(json.dumps(o, separators=(",", ":"), ensure_ascii=False) + "\n")


def contexto(symbol: str) -> dict:
    """El contexto del día que el operador NO tiene que tipear: ATR, gamma, niveles."""
    t = fu.tablero(symbol)
    if not t.get("ok"):
        return {"ok": False, "motivo": t.get("motivo", "Sin tablero.")}
    s = t.get("sesion") or {}
    o = t.get("opciones") or {}
    return {
        "ok": True,
        "precio_al_abrir": t.get("precio"),
        "valor_punto": t.get("valor_punto"),
        "atr_sesion": s.get("atr_sesion"),
        "regimen_gamma": o.get("regimen_gamma"),
        "gamma_cero": next((n["precio"] for n in (o.get("niveles") or [])
                            if n["nombre"] == "Gamma cero"), None),
        "niveles": {n["nombre"]: n["precio"] for n in (t.get("niveles") or [])
                    if n.get("precio")},
    }


def abrir(symbol: str, direccion: str, contratos: int, entrada: float, stop: float,
          nivel: str | None = None, nivel_precio: float | None = None,
          nota: str = "", dir_datos: str = DIR_DATOS, ctx: dict | None = None) -> dict:
    """Registra el PLAN: entrada, stop y el nivel que se usó de referencia."""
    direccion = direccion.lower()
    if direccion not in ("largo", "corto"):
        return {"ok": False, "motivo": "La dirección es 'largo' o 'corto'."}
    if contratos <= 0:
        return {"ok": False, "motivo": "Los contratos tienen que ser positivos."}
    riesgo = abs(entrada - stop)
    if riesgo <= 0:
        return {"ok": False, "motivo": "El stop no puede estar en el precio de entrada: "
                                        "sin riesgo definido no hay R con qué medir."}
    # Un stop del lado equivocado es casi siempre un error de tipeo, y guardarlo
    # silenciosamente contamina la muestra.
    if direccion == "largo" and stop > entrada:
        return {"ok": False, "motivo": "En un largo el stop va POR DEBAJO de la entrada."}
    if direccion == "corto" and stop < entrada:
        return {"ok": False, "motivo": "En un corto el stop va POR ENCIMA de la entrada."}

    c = ctx if ctx is not None else contexto(symbol)
    ahora = datetime.now(tz=timezone.utc)
    atr = c.get("atr_sesion")

    op = {
        "id": uuid.uuid4().hex[:8],
        "symbol": symbol.upper(),
        "direccion": direccion,
        "contratos": contratos,
        "entrada": entrada,
        "stop": stop,
        "riesgo_puntos": round(riesgo, 4),
        "nivel": nivel,
        "nivel_precio": nivel_precio,
        "nota": nota,
        "abierta_en": ahora.isoformat(timespec="seconds"),
        "sesion": nv.hora_ny(int(ahora.timestamp())).date().isoformat(),
        "atr_sesion": atr,
        "regimen_gamma": c.get("regimen_gamma"),
        "gamma_cero": c.get("gamma_cero"),
        "valor_punto": c.get("valor_punto"),
        "precio_al_abrir": c.get("precio_al_abrir"),
        "cerrada": False,
    }

    # ¿El stop quedó dentro del ruido de la medición? Esto testea el consejo que di.
    if nivel_precio and atr:
        op["dist_stop_nivel_atr"] = round(abs(stop - nivel_precio) / atr, 3)
        op["stop_dentro_del_ruido"] = op["dist_stop_nivel_atr"] < MARGEN_RUIDO_ATR
        op["dist_entrada_nivel_atr"] = round(abs(entrada - nivel_precio) / atr, 3)
    if atr:
        op["riesgo_atr"] = round(riesgo / atr, 3)

    ops = leer(dir_datos)
    ops.append(op)
    _escribir(ops, dir_datos)
    return {"ok": True, "operacion": op}


def cerrar(id_op: str, salida: float, motivo: str = "manual", nota: str = "",
           dir_datos: str = DIR_DATOS, barras: list | None = None) -> dict:
    """Registra el RESULTADO. Se calcula en R y en dólares."""
    ops = leer(dir_datos)
    op = next((o for o in ops if o["id"] == id_op), None)
    if not op:
        return {"ok": False, "motivo": f"No existe la operación {id_op}."}
    if op.get("cerrada"):
        return {"ok": False, "motivo": f"La operación {id_op} ya estaba cerrada."}

    signo = 1 if op["direccion"] == "largo" else -1
    puntos = (salida - op["entrada"]) * signo
    ahora = datetime.now(tz=timezone.utc)

    op.update({
        "cerrada": True,
        "salida": salida,
        "motivo_salida": motivo,
        "cerrada_en": ahora.isoformat(timespec="seconds"),
        "puntos": round(puntos, 4),
        "resultado_r": round(puntos / op["riesgo_puntos"], 3),
        "dolares": (round(puntos * op["contratos"] * op["valor_punto"], 2)
                    if op.get("valor_punto") else None),
        "nota_salida": nota,
    })
    # Abierta y cerrada en la misma corrida: el "plan" pudo escribirse sabiendo el final.
    op["post_hoc"] = op["abierta_en"] == op["cerrada_en"]
    if nota:
        op["nota"] = (op.get("nota") or "") + (" | " if op.get("nota") else "") + nota

    _escribir(ops, dir_datos)
    guardado = _guardar_barras(op, dir_datos, barras)
    return {"ok": True, "operacion": op, "barras_guardadas": guardado}


def _guardar_barras(op: dict, dir_datos: str, barras: list | None) -> bool:
    """Guarda las velas de la sesión, para poder correr el control al azar más adelante.

    Sin esto, dentro de tres meses el feed ya no entrega esas velas (da 8 semanas) y el
    nulo sobre los trades viejos queda imposible de calcular.
    """
    destino = os.path.join(dir_datos, "barras",
                           f"{op['sesion']}_{op['symbol'].replace('=', '')}.json")
    if os.path.exists(destino):
        return True
    try:
        if barras is None:
            from connectors import market
            h = market.velas(op["symbol"], "5m")
            ses = nv.agrupar_sesiones(h.get("points") or [])
            barras = []
            for s in ses:
                bs = s.get("barras_rth") or []
                if bs and nv.hora_ny(bs[0]["t"]).date().isoformat() == op["sesion"]:
                    barras = [[b["t"], b["o"], b["h"], b["l"], b["c"]] for b in bs]
                    break
        if not barras:
            return False
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        json.dump({"sesion": op["sesion"], "symbol": op["symbol"], "barras": barras},
                  open(destino, "w", encoding="utf-8"), separators=(",", ":"))
        return True
    except Exception:                                    # noqa: BLE001
        # Perder las velas no debe hacer fallar el cierre de la operación.
        return False


def barras_faltantes(dir_datos: str = DIR_DATOS) -> list[tuple[str, str]]:
    """Sesiones de operaciones cerradas que todavía no tienen las velas guardadas."""
    falta = []
    for o in leer(dir_datos):
        if not o.get("cerrada"):
            continue
        destino = os.path.join(dir_datos, "barras",
                               f"{o['sesion']}_{o['symbol'].replace('=', '')}.json")
        if not os.path.exists(destino):
            par = (o["sesion"], o["symbol"])
            if par not in falta:
                falta.append(par)
    return falta


def recuperar_barras(dir_datos: str = DIR_DATOS) -> dict:
    """Vuelve a intentar guardar las velas que faltan.

    Hace falta porque el guardado puede fallar en el momento del cierre: una operación
    cerrada antes de que abra el RTH no tiene velas todavía, y el feed puede fallar. Como
    solo entrega 8 semanas, lo que no se recupere en ese plazo se pierde para siempre.
    """
    falta = barras_faltantes(dir_datos)
    if not falta:
        return {"ok": True, "faltaban": 0, "recuperadas": 0, "sin_recuperar": []}
    ops = leer(dir_datos)
    recuperadas, fallidas = 0, []
    for sesion, symbol in falta:
        op = next(o for o in ops if o["sesion"] == sesion and o["symbol"] == symbol)
        if _guardar_barras(op, dir_datos, None):
            recuperadas += 1
        else:
            fallidas.append(f"{sesion} {symbol}")
    return {"ok": True, "faltaban": len(falta), "recuperadas": recuperadas,
            "sin_recuperar": fallidas,
            "aviso": ("El feed entrega 8 semanas de velas de 5 minutos: lo que no se "
                      "recupere antes de ese plazo no se puede reconstruir."
                      if fallidas else "")}


def _t_stat(valores: list[float]) -> tuple[float | None, float | None, float | None]:
    """Media, error estándar y t. Sin esto, una racha de cinco parece una estrategia."""
    n = len(valores)
    if n < 2:
        return (valores[0] if n else None), None, None
    media = sum(valores) / n
    var = sum((v - media) ** 2 for v in valores) / (n - 1)
    ee = (var / n) ** 0.5
    return media, ee, (media / ee if ee > 0 else None)


def _resumen(ops: list[dict]) -> dict:
    rs = [o["resultado_r"] for o in ops if o.get("resultado_r") is not None]
    if not rs:
        return {"n": 0}
    ganadas = sum(1 for r in rs if r > 0)
    lo, hi = wilson(ganadas, len(rs))
    media, ee, t = _t_stat(rs)
    return {
        "n": len(rs),
        "ganadas": ganadas,
        "tasa_acierto": round(100.0 * ganadas / len(rs), 1),
        "ic95_acierto": [round(100 * lo, 1), round(100 * hi, 1)],
        "r_medio": round(media, 3) if media is not None else None,
        "r_ee": round(ee, 3) if ee else None,
        "t": round(t, 2) if t else None,
        "r_total": round(sum(rs), 2),
        "dolares": round(sum(o.get("dolares") or 0 for o in ops), 2),
        "mejor": round(max(rs), 2),
        "peor": round(min(rs), 2),
    }


def analizar(dir_datos: str = DIR_DATOS, minimo: int = 30) -> dict:
    """Qué dice el diario, con los errores puestos y sin adornar la muestra chica."""
    todas = leer(dir_datos)
    cerradas = [o for o in todas if o.get("cerrada")]
    limpias = [o for o in cerradas if not o.get("post_hoc")]

    g = _resumen(limpias)
    if g["n"] == 0:
        return {"ok": True, "n_total": len(todas), "n_cerradas": len(cerradas),
                "n_limpias": 0, "abiertas": len([o for o in todas if not o.get("cerrada")]),
                "global": g, "medible": False,
                "veredicto": "Todavía no hay operaciones cerradas con el plan registrado "
                             "antes del resultado. Hasta que las haya, no hay nada que medir."}

    cortes: dict[str, dict] = {}
    # Por régimen de gamma: ¿el consejo de comportarse distinto tiene algún respaldo?
    for reg in {str(o.get("regimen_gamma")).split(" ")[0] for o in limpias}:
        sub = [o for o in limpias if str(o.get("regimen_gamma")).startswith(reg)]
        cortes[f"gamma {reg}"] = _resumen(sub)
    # El corte que testea directamente lo que recomendé sobre el stop.
    for etiqueta, cond in (("stop dentro del ruido", True), ("stop fuera del ruido", False)):
        sub = [o for o in limpias if o.get("stop_dentro_del_ruido") is cond]
        if sub:
            cortes[etiqueta] = _resumen(sub)
    # Por nivel de referencia, para ver si alguno se destaca (y corregir por multiplicidad).
    por_nivel = {}
    for o in limpias:
        if o.get("nivel"):
            por_nivel.setdefault(o["nivel"], []).append(o)
    niveles = {k: _resumen(v) for k, v in sorted(por_nivel.items(),
                                                key=lambda kv: -len(kv[1]))}

    medible = g["n"] >= minimo
    if not medible:
        veredicto = (f"{g['n']} operaciones con plan previo. Hacen falta al menos {minimo} "
                     f"para que el error estándar signifique algo; con menos, una racha "
                     f"de cinco parece una estrategia. Lo que hay ahora es contabilidad, "
                     f"no evidencia.")
    elif g["t"] is not None and g["t"] > 2:
        veredicto = (f"R medio {g['r_medio']} con t={g['t']} sobre {g['n']} operaciones. "
                     f"Se distingue de cero, pero falta el control: comparar contra los "
                     f"mismos trades anclados a un precio al azar antes de creerle.")
    else:
        veredicto = (f"R medio {g['r_medio']} ± {g['r_ee']} (t={g['t']}) sobre {g['n']} "
                     f"operaciones. No se distingue de cero. Con esta muestra, el mapa no "
                     f"muestra haber mejorado el resultado.")

    return {
        "ok": True,
        "n_total": len(todas),
        "n_cerradas": len(cerradas),
        "n_limpias": g["n"],
        "n_post_hoc": len(cerradas) - len(limpias),
        "abiertas": len([o for o in todas if not o.get("cerrada")]),
        "global": g,
        "cortes": cortes,
        "por_nivel": niveles,
        "medible": medible,
        "minimo": minimo,
        "veredicto": veredicto,
        "pendiente": ("Falta el control al azar: repetir cada operación anclada a un precio "
                      "sorteado en vez del nivel usado, con el mismo stop y el mismo "
                      "objetivo. Las velas quedan guardadas en data/diario/barras/ "
                      "justamente para poder hacerlo cuando haya muestra."),
    }
