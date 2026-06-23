"""Persistencia de reportes del oráculo (JSON en disco)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import REPORTS_DIR

_INDEX = REPORTS_DIR / "index.json"


def _load_index() -> list[dict]:
    if _INDEX.exists():
        return json.loads(_INDEX.read_text(encoding="utf-8"))
    return []


def save_report(report: dict, html_path: Path) -> dict:
    """Guarda el JSON del reporte y registra la entrada en el índice."""
    ticker = report.get("ticker", "NA")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    json_path = REPORTS_DIR / f"{ticker}_{stamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    entry = {
        "ticker": ticker,
        "company": report.get("company"),
        "score": (report.get("score") or {}).get("overall_score"),
        "band": (report.get("score") or {}).get("band"),
        "generated_at": report.get("generated_at"),
        "json": json_path.name,
        "html": html_path.name,
    }
    index = _load_index()
    index.insert(0, entry)
    _INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def list_reports(ticker: str | None = None, limit: int = 50) -> list[dict]:
    index = _load_index()
    if ticker:
        index = [e for e in index if e["ticker"] == ticker.upper()]
    return index[:limit]


def latest_for(ticker: str) -> dict | None:
    reports = list_reports(ticker, limit=1)
    return reports[0] if reports else None
