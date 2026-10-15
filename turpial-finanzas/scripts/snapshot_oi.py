#!/usr/bin/env python3
"""Saca la foto diaria de interés abierto y la deja commiteada en el repo.

Pensado para correr desatendido una vez por día. El contenedor es efímero, así que
guardar en disco local no sirve: el histórico se persiste haciendo commit y push.

Uso:
    python3 scripts/snapshot_oi.py              # captura, guarda y commitea
    python3 scripts/snapshot_oi.py --sin-git    # sólo captura y guarda
"""

from __future__ import annotations

import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import snapshots as sn   # noqa: E402

INDICES = ["^SPX", "^NDX"]
RAMA = "claude/algorithmic-trading-stochastic-qc7mbu"


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    con_git = "--sin-git" not in sys.argv
    resultados, fallos = [], []

    for ind in INDICES:
        snap = sn.capturar(ind)
        if not snap.get("ok"):
            fallos.append(f"{ind}: {snap.get('motivo')}")
            print(f"FALLO {ind}: {snap.get('motivo')}", file=sys.stderr)
            continue
        r = sn.guardar(snap)
        estado = "duplicada" if r.get("duplicada") else "nueva"
        print(f"{ind}: {estado} · sesión {snap['sesion']} · {len(snap['strikes'])} strikes "
              f"· spot {snap['spot']} · total guardadas {r['total']}")
        if not r.get("duplicada"):
            resultados.append(f"{ind} ({snap['sesion']})")

    if not resultados:
        # Sin foto nueva no hay nada que commitear; tampoco es un error si ya estaba.
        print("Sin fotos nuevas." + (f" Fallos: {'; '.join(fallos)}" if fallos else ""))
        return 1 if fallos and not resultados else 0

    if not con_git:
        return 0

    git("add", sn.DIR_DATOS)
    cod, salida = git("status", "--porcelain", sn.DIR_DATOS)
    if not salida:
        print("Nada que commitear.")
        return 0

    msg = ("Foto diaria de interés abierto: " + ", ".join(resultados) +
           "\n\nCapturado por scripts/snapshot_oi.py. El feed no tiene histórico de "
           "interés abierto, así que la serie se fabrica guardando una foto por día.\n"
           "\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>")
    cod, salida = git("-c", "user.email=carlospallottini@gmail.com",
                      "-c", "user.name=Carlos Pallottini", "commit", "-m", msg)
    if cod != 0:
        print(f"Commit falló: {salida}", file=sys.stderr)
        return 1

    for intento, espera in enumerate((2, 4, 8, 16, 0)):
        cod, salida = git("push", "-u", "origin", RAMA)
        if cod == 0:
            print(f"Push OK a {RAMA}.")
            return 0
        print(f"Push falló (intento {intento + 1}): {salida}", file=sys.stderr)
        if espera:
            __import__("time").sleep(espera)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
