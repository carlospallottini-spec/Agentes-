"""Conectores a plataformas de terceros — con honestidad sobre su disponibilidad.

El brief pide alimentarse de JustETF, Microcap Club, Value Invest Club, Dataroma,
Wisdom, TIKR, Koyfin e Insider Screener. La realidad de cada una:

  Fuente            | API pública | Estado en Turpial
  ------------------|-------------|----------------------------------------------
  SEC EDGAR         | SÍ          | Implementada de verdad (connectors/sec_edgar)
  Stooq / Yahoo     | SÍ (free)   | Implementada de verdad (connectors/prices)
  TIKR              | NO          | Adapter con hook de API key; sin key -> no_data
  Koyfin            | NO          | Adapter con hook de API key; sin key -> no_data
  JustETF           | NO oficial  | Adapter (scraping prohibido por ToS) -> manual
  Microcap Club     | NO (cerrado)| Comunidad paga; aporte manual -> manual
  Value Invest Club | NO (cerrado)| Comunidad cerrada; aporte manual -> manual
  Dataroma          | NO oficial  | Datos 13F públicos; scraping frágil -> manual/parser
  Wisdom (WisdomTree/wisesheets) | NO oficial | Adapter -> manual

Diseño: cada conector devuelve SIEMPRE un dict con la misma forma, de modo que el
agente sepa distinguir "dato real" de "no disponible públicamente". Nunca inventamos
datos: si no hay credencial o fuente pública, devolvemos status="no_data" con el motivo.
"""
from __future__ import annotations

import os


def _no_data(source: str, reason: str) -> dict:
    return {"source": source, "status": "no_data", "reason": reason, "data": None}


def _ok(source: str, data) -> dict:
    return {"source": source, "status": "ok", "reason": None, "data": data}


# --- Plataformas con posible API privada (requieren key del usuario) ---------

def tikr(ticker: str) -> dict:
    """TIKR no tiene API pública. Si tenés un endpoint/clave privada, ponela en
    TIKR_API_KEY y extendé esta función. Sin eso, devolvemos no_data honesto."""
    if not os.environ.get("TIKR_API_KEY"):
        return _no_data("tikr", "TIKR no expone API pública; falta TIKR_API_KEY.")
    # Punto de extensión: implementar llamada real con la credencial provista.
    return _no_data("tikr", "TIKR_API_KEY presente pero el adapter no está implementado.")


def koyfin(ticker: str) -> dict:
    if not os.environ.get("KOYFIN_API_KEY"):
        return _no_data("koyfin", "Koyfin no expone API pública; falta KOYFIN_API_KEY.")
    return _no_data("koyfin", "KOYFIN_API_KEY presente pero el adapter no está implementado.")


# --- Fuentes de ideas / superinvestores (sin API oficial) -------------------

def justetf(query: str) -> dict:
    return _no_data("justetf", "JustETF no tiene API pública; su ToS prohíbe scraping.")


def microcap_club(ticker: str) -> dict:
    return _no_data("microcap_club", "Comunidad paga y cerrada; sin API. Aporte manual.")


def value_invest_club(ticker: str) -> dict:
    return _no_data("value_invest_club", "Comunidad cerrada; sin API. Aporte manual.")


def dataroma(ticker: str) -> dict:
    """Dataroma publica holdings 13F de superinvestores en HTML. No hay API oficial
    y el scraping es frágil/sujeto a ToS. Para insiders reales usamos Form 4 de EDGAR
    (connectors/insiders.py), que es la fuente primaria y legal."""
    return _no_data(
        "dataroma",
        "Sin API oficial. Para insiders usá Form 4 de EDGAR (fuente primaria real).",
    )


def wisdom(ticker: str) -> dict:
    return _no_data("wisdom", "Sin API pública estable; integración manual.")


# Registro para que el agente itere sobre fuentes disponibles.
SOURCES = {
    "tikr": tikr,
    "koyfin": koyfin,
    "justetf": justetf,
    "microcap_club": microcap_club,
    "value_invest_club": value_invest_club,
    "dataroma": dataroma,
    "wisdom": wisdom,
}
