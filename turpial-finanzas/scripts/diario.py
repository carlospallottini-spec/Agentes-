#!/usr/bin/env python3
"""Diario de operaciones: registrar el plan, cerrar con el resultado, y medir.

    python3 scripts/diario.py abrir  MNQ=F largo 1 30150 30050 --nivel "Pivote S1"
    python3 scripts/diario.py cerrar a1b2c3d4 30220 --motivo objetivo
    python3 scripts/diario.py estado
    python3 scripts/diario.py analizar

El contexto del día (ATR, régimen de gamma, precio del nivel) lo completa solo: a la hora
de entrar no hay tiempo de tipear ocho datos, y un diario con fricción es un diario vacío.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import diario   # noqa: E402

RAMA = "claude/algorithmic-trading-stochastic-qc7mbu"


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


SIN_GIT = False


def commitear(mensaje: str) -> None:
    """El repositorio es la base de datos: sin commit, el contenedor se lleva el diario."""
    if SIN_GIT:
        return
    git("add", diario.DIR_DATOS)
    cod, salida = git("status", "--porcelain", diario.DIR_DATOS)
    if not salida:
        return
    git("-c", "user.email=carlospallottini@gmail.com", "-c", "user.name=Carlos Pallottini",
        "commit", "-m", mensaje)
    for espera in (2, 4, 8, 16, 0):
        if git("push", "-u", "origin", RAMA)[0] == 0:
            print("  (guardado y pusheado)")
            return
        if espera:
            __import__("time").sleep(espera)
    print("  (guardado local; el push falló, reintentá después)", file=sys.stderr)


def cmd_abrir(a) -> int:
    ctx = diario.contexto(a.symbol)
    if not ctx.get("ok"):
        print(f"Aviso: sin contexto del día ({ctx.get('motivo')}). "
              f"Se registra igual, sin ATR ni gamma.", file=sys.stderr)
        ctx = {"ok": True}

    precio_nivel = a.nivel_precio
    if a.nivel and precio_nivel is None:
        precio_nivel = (ctx.get("niveles") or {}).get(a.nivel)
        if precio_nivel is None and ctx.get("niveles"):
            print(f"Aviso: no encontré el nivel «{a.nivel}». Disponibles: "
                  f"{', '.join(sorted(ctx['niveles']))}", file=sys.stderr)

    r = diario.abrir(a.symbol, a.direccion, a.contratos, a.entrada, a.stop,
                     nivel=a.nivel, nivel_precio=precio_nivel, nota=a.nota or "",
                     ctx=ctx, dir_datos=a.datos)
    if not r.get("ok"):
        print(f"ERROR: {r['motivo']}", file=sys.stderr)
        return 1

    o = r["operacion"]
    print(f"Abierta {o['id']} · {o['symbol']} {o['direccion']} ×{o['contratos']}")
    print(f"  entrada {o['entrada']:,.2f} · stop {o['stop']:,.2f} · "
          f"riesgo {o['riesgo_puntos']:,.2f} pts"
          + (f" (US$ {o['riesgo_puntos'] * o['contratos'] * o['valor_punto']:,.0f})"
             if o.get("valor_punto") else ""))
    if o.get("riesgo_atr"):
        print(f"  riesgo = {o['riesgo_atr']} ATR de sesión (ATR {o['atr_sesion']:,.1f} pts)")
    if o.get("regimen_gamma"):
        print(f"  gamma {o['regimen_gamma']}")
    if o.get("stop_dentro_del_ruido") is True:
        print(f"  ATENCIÓN: el stop está a {o['dist_stop_nivel_atr']} ATR del nivel, "
              f"dentro de la banda de ruido ({diario.MARGEN_RUIDO_ATR} ATR). "
              f"Ahí la medición no distingue aguante de azar.", file=sys.stderr)
    commitear(f"Diario: abrir {o['id']} {o['symbol']} {o['direccion']}")
    return 0


def cmd_cerrar(a) -> int:
    r = diario.cerrar(a.id, a.salida, motivo=a.motivo, nota=a.nota or "",
                      dir_datos=a.datos)
    if not r.get("ok"):
        print(f"ERROR: {r['motivo']}", file=sys.stderr)
        return 1
    o = r["operacion"]
    signo = "+" if o["resultado_r"] >= 0 else ""
    print(f"Cerrada {o['id']} · salida {o['salida']:,.2f} · {o['motivo_salida']}")
    print(f"  {signo}{o['puntos']:,.2f} pts · {signo}{o['resultado_r']} R"
          + (f" · US$ {o['dolares']:,.2f}" if o.get("dolares") is not None else ""))
    if o.get("post_hoc"):
        print("  marcada post_hoc (abierta y cerrada a la vez): el análisis la separa, "
              "porque el plan pudo escribirse sabiendo el final.", file=sys.stderr)
    if not r.get("barras_guardadas"):
        print("  aviso: no pude guardar las velas de la sesión; el control al azar sobre "
              "esta operación va a ser imposible más adelante.", file=sys.stderr)
    commitear(f"Diario: cerrar {o['id']} {signo}{o['resultado_r']}R")
    return 0


def cmd_estado(a) -> int:
    ops = diario.leer(a.datos)
    abiertas = [o for o in ops if not o.get("cerrada")]
    print(f"{len(ops)} operaciones · {len(abiertas)} abiertas")
    for o in abiertas:
        print(f"  {o['id']} · {o['symbol']} {o['direccion']} ×{o['contratos']} · "
              f"entrada {o['entrada']:,.2f} · stop {o['stop']:,.2f}"
              + (f" · nivel {o['nivel']}" if o.get("nivel") else ""))
    for o in [x for x in ops if x.get("cerrada")][-8:]:
        signo = "+" if o["resultado_r"] >= 0 else ""
        print(f"  {o['id']} · {o['sesion']} · {o['symbol']} {o['direccion']} · "
              f"{signo}{o['resultado_r']}R · {o['motivo_salida']}")
    return 0


def cmd_barras(a) -> int:
    r = diario.recuperar_barras(a.datos)
    if not r["faltaban"]:
        print("No falta ninguna sesión de velas.")
        return 0
    print(f"Faltaban {r['faltaban']} · recuperadas {r['recuperadas']}")
    for f in r["sin_recuperar"]:
        print(f"  sin recuperar: {f}", file=sys.stderr)
    if r.get("aviso"):
        print(f"  {r['aviso']}", file=sys.stderr)
    if r["recuperadas"]:
        commitear(f"Diario: recuperar velas de {r['recuperadas']} sesión(es)")
    return 0


def cmd_analizar(a) -> int:
    rep = diario.analizar(dir_datos=a.datos, minimo=a.minimo)
    g = rep["global"]
    print(f"Diario: {rep['n_total']} operaciones · {rep['n_cerradas']} cerradas · "
          f"{rep['n_limpias']} con plan previo · {rep['abiertas']} abiertas")
    if rep.get("n_post_hoc"):
        print(f"  ({rep['n_post_hoc']} marcadas post_hoc, excluidas del análisis)")
    print()
    if g["n"]:
        if g.get("r_ee"):
            print(f"  R medio      {g['r_medio']:+.3f} ± {g['r_ee']:.3f}  (t={g['t']})")
        else:
            print(f"  R medio      {g['r_medio']:+.3f}   (una sola operación: sin error "
                  f"estándar, o sea sin forma de saber si es suerte)")
        print(f"  R total      {g['r_total']:+.2f}")
        print(f"  Acierto      {g['tasa_acierto']}%  IC95 "
              f"{g['ic95_acierto'][0]}–{g['ic95_acierto'][1]}%")
        print(f"  Mejor/peor   {g['mejor']:+.2f}R / {g['peor']:+.2f}R")
        print(f"  Dólares      {g['dolares']:+,.2f}")
        if rep.get("cortes"):
            print("\n  Por corte:")
            for k, v in rep["cortes"].items():
                if v.get("n"):
                    print(f"    {k:<26} n={v['n']:<4} R medio {v['r_medio']:+.3f}"
                          f"  acierto {v['tasa_acierto']}%")
        if rep.get("por_nivel"):
            print("\n  Por nivel de referencia:")
            for k, v in rep["por_nivel"].items():
                print(f"    {k:<26} n={v['n']:<4} R medio {v['r_medio']:+.3f}"
                      f"  acierto {v['tasa_acierto']}%")
    print(f"\n  {rep['veredicto']}")
    if rep.get("pendiente"):
        print(f"\n  Pendiente: {rep['pendiente']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("abrir", help="registrar el plan de una operación")
    a.add_argument("symbol", help="MNQ=F, MES=F, NQ=F, ES=F")
    a.add_argument("direccion", choices=["largo", "corto"])
    a.add_argument("contratos", type=int)
    a.add_argument("entrada", type=float)
    a.add_argument("stop", type=float)
    a.add_argument("--nivel", help='nivel de referencia, p. ej. "Muro de puts"')
    a.add_argument("--nivel-precio", type=float, help="si no está en el tablero de hoy")
    a.add_argument("--nota", help="texto libre")
    a.set_defaults(fn=cmd_abrir)

    c = sub.add_parser("cerrar", help="registrar el resultado")
    c.add_argument("id")
    c.add_argument("salida", type=float)
    c.add_argument("--motivo", default="manual",
                   choices=["stop", "objetivo", "manual", "cierre_sesion"])
    c.add_argument("--nota")
    c.set_defaults(fn=cmd_cerrar)

    e = sub.add_parser("estado", help="qué hay abierto y las últimas cerradas")
    e.set_defaults(fn=cmd_estado)

    b = sub.add_parser("barras", help="recuperar las velas de sesión que falten")
    b.set_defaults(fn=cmd_barras)

    an = sub.add_parser("analizar", help="qué dice el diario, con los errores puestos")
    an.add_argument("--minimo", type=int, default=30,
                    help="operaciones mínimas para considerar la muestra medible")
    an.set_defaults(fn=cmd_analizar)

    for sp in (a, c, e, b, an):
        sp.add_argument("--datos", default=diario.DIR_DATOS,
                        help="directorio de datos (para pruebas)")

    args = p.parse_args()
    if args.datos != diario.DIR_DATOS:
        diario.DIR_DATOS = args.datos        # el CLI pasa dir_datos por defecto del módulo
        globals()["SIN_GIT"] = True          # no commitear lo que es una prueba
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
