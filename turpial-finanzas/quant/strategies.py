"""Reglas de trading derivadas del OU y del régimen markoviano.

La estrategia base es **reversión a la media sobre el z-score del OU**:

    z_t = (X_t − μ̂) / σ̂_eq      con μ̂, σ̂_eq calibrados SOLO con datos hasta t

  · z ≤ −entrada  ⇒ el resorte está estirado hacia abajo ⇒ posición larga (+1)
  · z ≥ +entrada  ⇒ estirado hacia arriba ⇒ posición corta (−1)
  · |z| ≤ salida  ⇒ volvió al equilibrio ⇒ cerrar (0)
  · |z| ≥ stop    ⇒ la tesis de reversión falló (el equilibrio se movió) ⇒ cortar (0)

El **half-life** entra como límite de tiempo, no como adorno: si la posición lleva más de
`max_hold_hl` half-lives abierta y no revirtió, la hipótesis del modelo dejó de valer y se
cierra. Es la traducción operativa de "la fuerza restauradora debería haber actuado ya".

Encima va el **filtro de régimen** de Markov: no se opera contra un régimen persistente.
Comprar la caída dentro de un régimen bajista con P_ii alto es pelearse con una tendencia
que el propio modelo dice que va a continuar. El filtro se activa solo si el test χ² de
memoria rechaza la independencia; si no hay evidencia de memoria, no filtra nada.
"""
from __future__ import annotations

FLAT, LONG, SHORT = 0, 1, -1


def ou_position(z: float, prev_pos: int, bars_held: int, half_life: float,
                entry: float = 1.5, exit_: float = 0.5, stop: float = 3.0,
                max_hold_hl: float = 3.0) -> tuple[int, str]:
    """Posición objetivo dado el z-score actual. Devuelve (posición, motivo)."""
    max_bars = max(1.0, max_hold_hl * half_life)

    if prev_pos == FLAT:
        if z <= -entry:
            return LONG, "entrada larga: z bajo el umbral"
        if z >= entry:
            return SHORT, "entrada corta: z sobre el umbral"
        return FLAT, "sin señal"

    if bars_held >= max_bars:
        return FLAT, f"tiempo agotado: {max_hold_hl}× half-life sin reversión"

    if prev_pos == LONG:
        if z <= -stop:
            return FLAT, "stop: la desviación siguió creciendo"
        if z >= -exit_:
            return FLAT, "objetivo: volvió al equilibrio"
        return LONG, "mantener larga"

    if z >= stop:
        return FLAT, "stop: la desviación siguió creciendo"
    if z <= exit_:
        return FLAT, "objetivo: volvió al equilibrio"
    return SHORT, "mantener corta"


def regime_allows(target: int, regimen: dict | None, persistencia_min: float = 0.6) -> bool:
    """¿El régimen markoviano deja abrir esta posición?

    Bloquea comprar dentro de un régimen bajista persistente y vender dentro de uno
    alcista persistente. Si no hay reporte de régimen, o el χ² no encontró memoria,
    deja pasar todo (no inventamos un filtro sin evidencia).
    """
    if target == FLAT or not regimen or not regimen.get("ok"):
        return True
    if not regimen.get("test_memoria", {}).get("hay_memoria_5pct"):
        return True
    persistente = regimen.get("persistencia_actual", 0.0) >= persistencia_min
    if not persistente:
        return True
    actual = regimen.get("regimen_actual")
    if target == LONG and actual == "bajista":
        return False
    if target == SHORT and actual == "alcista":
        return False
    return True
