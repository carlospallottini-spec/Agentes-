"""Configuración central de Turpial Finanzas."""
import os
from pathlib import Path

# Modelo de Claude usado por los agentes de Wall Street.
MODEL = "claude-opus-4-7"

# Identificador honesto para el header User-Agent que exige la API de SEC EDGAR.
# La SEC pide un contacto real; configuralo en .env (SEC_USER_AGENT) en producción.
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "Turpial Finanzas research bot (contacto: tu-email@ejemplo.com)",
)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Pesos del framework de Risk Score (deben sumar 1.0). Vienen de las directrices:
#   Valuación 35% · Salud Financiera 35% · Crecimiento 30%.
PILLAR_WEIGHTS = {
    "valuacion": 0.35,
    "salud_financiera": 0.35,
    "crecimiento": 0.30,
}

# Bandas de riesgo (mayor puntaje = menor riesgo).
RISK_BANDS = [
    (90, 100, "Bajo Riesgo"),
    (75, 90, "Bajo-Mod"),
    (55, 75, "Moderado"),
    (30, 55, "Elevado"),
    (0, 30, "Alto"),
]


def band_for(score: float) -> str:
    """Devuelve la etiqueta de banda para un score 0-100."""
    for low, high, label in RISK_BANDS:
        if low <= score <= high:
            return label
    return "Sin dato"
