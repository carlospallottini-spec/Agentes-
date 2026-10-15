"""Histórico propio de interés abierto y volumen por strike.

El feed de opciones devuelve **una sola foto del momento**, sin fecha y sin histórico: no
existe forma de pedirle "el interés abierto del martes pasado". Y el interés abierto es
diario por construcción — la OCC lo publica a la mañana siguiente, así que lo que se ve
durante la sesión son las posiciones del cierre anterior. No hay interés abierto intradía
en ningún lado, a ningún precio.

La única manera de tener la serie es fabricarla: sacar una foto por día y guardarla. Este
módulo hace eso. El repositorio es la base de datos, porque el contenedor donde corre es
efímero y cualquier cosa guardada en disco local se pierde cuando se recicla.

Dos cosas se capturan, y la segunda importa más de lo que parece:

- **Interés abierto por strike**: lo que pidió el usuario. Cambia una vez por día.
- **Volumen por strike**: para 0DTE es el número que de verdad manda. En un strike de SPX
  medido el 2026-10-15 el volumen era 126.152 contra un interés abierto de 762: toda esa
  actividad abre y muere dentro de la sesión y nunca llega a ser interés abierto. Justo lo
  que mueve al índice intradía es lo que el interés abierto no ve.

**Un desfase de un día que hay que tener presente.** El volumen de la foto es el de la
sesión en curso, pero el interés abierto que se ve durante esa sesión es el del cierre
ANTERIOR, porque la OCC lo publica a la mañana siguiente. O sea que en una misma línea,
`volumen` y `oi` no son del mismo día: el oi va un día atrasado respecto del volumen.
Quien regrese "cambio de interés abierto" contra "retorno de la sesión siguiente" sin
saber esto se equivoca por un día y obtiene un resultado que parece real. Por eso
`serie()` devuelve el campo `desfase_oi` explícito en vez de dejarlo implícito.

Nada de esto está medido todavía. Hace falta acumular antes de poder testear si el
**cambio** de interés abierto o de GEX predice algo, y cuando haya muestra va a pasar por
el mismo control al azar que hundió a los niveles de sesión.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from quant import futuros as fu
from quant import niveles as nv
from quant import opciones as op

# Un strike a 20% del dinero no aporta nada y multiplica el tamaño del archivo.
RANGO_PCT = 8.0
DIR_DATOS = "data/opciones"


def capturar(indice: str = "^SPX", n_vencimientos: int = 3,
             rango_pct: float = RANGO_PCT) -> dict:
    """Una foto del interés abierto y el volumen por strike, más los agregados."""
    cadenas, spot = fu._cadenas(indice, n_vencimientos)
    if not cadenas or not spot:
        return {"ok": False, "indice": indice,
                "motivo": "El feed no devolvió cadena de opciones."}

    ahora = datetime.now(tz=timezone.utc)
    lo, hi = spot * (1 - rango_pct / 100), spot * (1 + rango_pct / 100)

    # Un registro por strike, con calls y puts juntos para que la fila sea chica.
    por_strike: dict[float, dict] = {}
    for cad in cadenas:
        for lado, clave_v, clave_oi in (("calls", "vc", "oic"), ("puts", "vp", "oip")):
            for o in cad.get(lado) or []:
                k = o.get("strike")
                if k is None or not (lo <= k <= hi):
                    continue
                f = por_strike.setdefault(k, {"k": k, "vc": 0, "vp": 0, "oic": 0, "oip": 0})
                f[clave_v] += o.get("volume") or 0
                f[clave_oi] += o.get("open_interest") or 0

    if not por_strike:
        return {"ok": False, "indice": indice,
                "motivo": f"Ningún strike dentro de ±{rango_pct}% del spot."}

    ag = op.analizar(cadenas, spot, spot, rango_pct=rango_pct)
    agregados = {}
    if ag.get("ok"):
        agregados = {k: ag.get(k) for k in
                     ("gex_total", "regimen_gamma", "oi_calls", "oi_puts",
                      "ratio_put_call_oi", "vol_calls", "vol_puts",
                      "ratio_put_call_vol", "n_strikes")}
        # max pain, gamma cero y los muros no son claves sueltas: `analizar` los devuelve
        # como niveles con nombre. Se extraen por nombre, no por posición.
        por_nombre = {n["nombre"]: n.get("precio") for n in ag.get("niveles") or []}
        agregados["max_pain"] = por_nombre.get("Max pain")
        agregados["gamma_cero"] = por_nombre.get("Gamma cero")
        agregados["muro_calls"] = por_nombre.get("Muro de calls")
        agregados["muro_puts"] = por_nombre.get("Muro de puts")

    return {
        "ok": True,
        "indice": indice,
        # `sesion` es la fecha de NY, no la UTC: una foto a las 20:30 NY es de ESE día,
        # aunque en UTC ya sea el siguiente.
        "sesion": nv.hora_ny(int(ahora.timestamp())).date().isoformat(),
        "momento": ahora.isoformat(timespec="seconds"),
        "spot": round(spot, 2),
        "vencimientos": [c.get("selected_expiration") for c in cadenas],
        "agregados": agregados,
        "strikes": sorted(por_strike.values(), key=lambda f: f["k"]),
    }


def ruta(indice: str, dir_datos: str = DIR_DATOS) -> str:
    return os.path.join(dir_datos, indice.replace("^", "") + ".jsonl")


def guardar(snap: dict, dir_datos: str = DIR_DATOS) -> dict:
    """Agrega la foto al histórico. Una línea por captura, formato JSONL.

    JSONL y no una base: el archivo vive en git, así que conviene que cada día sea una
    línea nueva y el diff muestre exactamente lo que se agregó.
    """
    if not snap.get("ok"):
        return {"ok": False, "motivo": snap.get("motivo", "Foto inválida.")}
    r = ruta(snap["indice"], dir_datos)
    os.makedirs(os.path.dirname(r), exist_ok=True)

    # Dos capturas del mismo minuto son la misma observación: no se duplica.
    previas = leer(snap["indice"], dir_datos)
    if any(p.get("momento") == snap["momento"] for p in previas):
        return {"ok": True, "duplicada": True, "total": len(previas), "ruta": r}

    with open(r, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap, separators=(",", ":"), ensure_ascii=False) + "\n")
    return {"ok": True, "duplicada": False, "total": len(previas) + 1, "ruta": r,
            "strikes": len(snap["strikes"]), "sesion": snap["sesion"]}


def leer(indice: str, dir_datos: str = DIR_DATOS) -> list[dict]:
    """Todas las fotos guardadas de un índice, en orden de captura."""
    r = ruta(indice, dir_datos)
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
                # Una línea rota no debe tirar abajo el histórico entero.
                continue
    out.sort(key=lambda s: s.get("momento") or "")
    return out


def serie(indice: str, dir_datos: str = DIR_DATOS) -> dict:
    """Serie diaria de los agregados, con el cambio día a día.

    Se queda con la ÚLTIMA foto de cada sesión: el interés abierto que vale es el del
    cierre, y si hubo varias capturas intradía las anteriores son la misma cifra de ayer.
    """
    fotos = leer(indice, dir_datos)
    if not fotos:
        return {"ok": False, "indice": indice, "n": 0,
                "motivo": "Todavía no hay fotos guardadas."}

    por_sesion: dict[str, dict] = {}
    for s in fotos:
        por_sesion[s["sesion"]] = s          # la última de cada sesión gana
    dias = [por_sesion[k] for k in sorted(por_sesion)]

    filas = []
    for i, s in enumerate(dias):
        ag = s.get("agregados") or {}
        fila = {"sesion": s["sesion"], "spot": s.get("spot"),
                "gex_total": ag.get("gex_total"), "max_pain": ag.get("max_pain"),
                "gamma_cero": ag.get("gamma_cero"),
                "regimen_gamma": ag.get("regimen_gamma"),
                "muro_calls": ag.get("muro_calls"), "muro_puts": ag.get("muro_puts"),
                "oi_calls": ag.get("oi_calls"), "oi_puts": ag.get("oi_puts"),
                "ratio_put_call_oi": ag.get("ratio_put_call_oi"),
                "ratio_put_call_vol": ag.get("ratio_put_call_vol"),
                "volumen_total": sum(f["vc"] + f["vp"] for f in s.get("strikes") or [])}
        if i > 0:
            ant = dias[i - 1].get("agregados") or {}
            for k in ("gex_total", "max_pain", "gamma_cero", "oi_calls", "oi_puts",
                      "muro_calls", "muro_puts"):
                a, b = ant.get(k), ag.get(k)
                fila["d_" + k] = round(b - a, 4) if (a is not None and b is not None) else None
        filas.append(fila)

    # Sin esto, alguien va a graficar 4 puntos y creer que ve una tendencia.
    n = len(filas)
    faltan = max(0, 60 - n)
    return {
        "ok": True, "indice": indice, "n": n, "capturas": len(fotos),
        "desde": filas[0]["sesion"], "hasta": filas[-1]["sesion"],
        "serie": filas,
        "medible": n >= 60,
        # Explícito y no implícito: el interés abierto de la fila va un día atrasado
        # respecto del volumen de la misma fila. Ver el encabezado del módulo.
        "desfase_oi": -1,
        "aviso": (f"{n} sesión(es) guardadas. Faltan ~{faltan} para que valga la pena "
                  f"testear algo: con menos, cualquier patrón que aparezca es ruido. "
                  f"Y cuando haya muestra, va a pasar por el control al azar."
                  if not n >= 60 else
                  f"{n} sesiones: ya hay con qué testear. Correr el control al azar "
                  f"antes de creerle a cualquier resultado."),
    }
