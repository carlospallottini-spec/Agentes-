"""Motor de Risk Score — implementa el framework de las directrices.

Tres pilares (0-100, MAYOR puntaje = MENOR riesgo):
  - Valuación        35%
  - Salud Financiera 35%
  - Crecimiento      30%

El cálculo es determinístico a partir de los fundamentales XBRL de EDGAR + precio.
El agente Claude luego agrega narrativa, badges (Ancla/Flex/Alerta) y trade-offs.
"""
from __future__ import annotations

from config import PILLAR_WEIGHTS, band_for
from connectors import sec_edgar as sec

# Nombres XBRL alternativos por concepto (varían entre empresas).
_REVENUE = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]
_NET_INCOME = ["NetIncomeLoss", "ProfitLoss"]
_ASSETS = ["Assets"]
_EQUITY = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
_CUR_ASSETS = ["AssetsCurrent"]
_CUR_LIAB = ["LiabilitiesCurrent"]
_LIAB = ["Liabilities"]
_CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
_LT_DEBT = ["LongTermDebtNoncurrent", "LongTermDebt"]
_OP_INCOME = ["OperatingIncomeLoss"]
_INTEREST = ["InterestExpense", "InterestExpenseDebt"]
_DA = ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
       "DepreciationAndAmortization"]
_OCF = ["NetCashProvidedByUsedInOperatingActivities"]
_CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
_EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]


def _map(value: float | None, at0: float, at100: float) -> float | None:
    """Mapea linealmente: value==at0 -> 0, value==at100 -> 100 (clamp a [0,100])."""
    if value is None:
        return None
    if at0 == at100:
        return 50.0
    t = (value - at0) / (at100 - at0)
    return max(0.0, min(100.0, t * 100.0))


def _cagr(series: list[float]) -> float | None:
    """CAGR % entre el primer y último valor de una serie anual."""
    if len(series) < 2 or series[0] <= 0:
        return None
    years = len(series) - 1
    return ((series[-1] / series[0]) ** (1 / years) - 1) * 100


def _best_revenue(facts: dict) -> tuple[float | None, list[float], str]:
    """Elige el concepto de ingresos TOTALES: entre sinónimos XBRL, el de mayor valor
    (las etiquetas alternativas suelen ser segmentos parciales mucho menores)."""
    best_val, best_concept = None, _REVENUE[0]
    for c in _REVENUE:
        v = sec.latest_annual(f := facts, c)
        if v is not None and (best_val is None or v > best_val):
            best_val, best_concept = v, c
    return best_val, sec.annual_series(facts, best_concept), best_concept


def _shares_outstanding(facts: dict) -> float | None:
    try:
        units = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
        rows = sorted([r for r in units if r.get("end")], key=lambda r: r["end"])
        return float(rows[-1]["val"]) if rows else None
    except KeyError:
        return None


def _avg(vals: list[float | None]) -> float | None:
    present = [v for v in vals if v is not None]
    return sum(present) / len(present) if present else None


def compute_risk_score(facts: dict, price: float | None) -> dict:
    """Calcula el Risk Score completo. Devuelve estructura lista para narrar y graficar."""
    f = facts

    revenue, rev_series, _ = _best_revenue(f)
    net_income = sec.first_available(f, _NET_INCOME)
    assets = sec.first_available(f, _ASSETS)
    equity = sec.first_available(f, _EQUITY)
    cur_assets = sec.first_available(f, _CUR_ASSETS)
    cur_liab = sec.first_available(f, _CUR_LIAB)
    total_liab = sec.first_available(f, _LIAB)
    cash = sec.first_available(f, _CASH)
    lt_debt = sec.first_available(f, _LT_DEBT)
    op_income = sec.first_available(f, _OP_INCOME)
    interest = sec.first_available(f, _INTEREST)
    da = sec.first_available(f, _DA)
    ocf = sec.first_available(f, _OCF)
    capex = sec.first_available(f, _CAPEX)
    eps = sec.first_available(f, _EPS, unit="USD/shares")
    shares = _shares_outstanding(f)

    market_cap = price * shares if (price and shares) else None

    # --- Ratios ---
    pe = (market_cap / net_income) if (market_cap and net_income and net_income > 0) else None
    ps = (market_cap / revenue) if (market_cap and revenue and revenue > 0) else None
    pb = (market_cap / equity) if (market_cap and equity and equity > 0) else None
    fcf = (ocf - capex) if (ocf is not None and capex is not None) else None
    fcf_yield = (fcf / market_cap * 100) if (fcf is not None and market_cap) else None

    current_ratio = (cur_assets / cur_liab) if (cur_assets and cur_liab) else None
    debt_equity = (total_liab / equity) if (total_liab and equity and equity > 0) else None
    interest_cov = (op_income / interest) if (op_income and interest and interest > 0) else None
    ebitda = (op_income + da) if (op_income is not None and da is not None) else op_income
    net_debt = ((lt_debt or 0) - (cash or 0)) if (lt_debt is not None or cash is not None) else None
    nd_ebitda = (net_debt / ebitda) if (net_debt is not None and ebitda and ebitda > 0) else None
    roe = (net_income / equity * 100) if (net_income and equity and equity > 0) else None
    net_margin = (net_income / revenue * 100) if (net_income and revenue and revenue > 0) else None

    eps_series = sec.annual_series(f, _next_concept(f, _EPS, "USD/shares"), unit="USD/shares")
    rev_cagr = _cagr(rev_series)
    eps_cagr = _cagr(eps_series)

    # --- Subscores por métrica (mayor = menor riesgo) ---
    def metric(key, label, value, unit, at0, at100, default_badge):
        return {
            "key": key, "label": label, "value": value, "unit": unit,
            "subscore": _map(value, at0, at100), "badge": default_badge,
        }

    valuacion = [
        metric("pe", "P/E (precio/ganancias)", pe, "x", 45, 8, "Ancla"),
        metric("ps", "P/S (precio/ventas)", ps, "x", 15, 1, "Flex"),
        metric("pb", "P/B (precio/valor libro)", pb, "x", 8, 0.8, "Flex"),
        metric("fcf_yield", "FCF yield (flujo libre/cap. mercado)", fcf_yield, "%", 0, 8, "Ancla"),
    ]
    salud = [
        metric("current_ratio", "Liquidez corriente", current_ratio, "x", 0.8, 2.5, "Ancla"),
        metric("debt_equity", "Pasivo/Patrimonio", debt_equity, "x", 3.0, 0.3, "Ancla"),
        metric("interest_cov", "Cobertura de intereses", interest_cov, "x", 1, 12, "Alerta"),
        metric("nd_ebitda", "Deuda neta/EBITDA", nd_ebitda, "x", 5, 0, "Alerta"),
        metric("roe", "ROE (retorno s/patrimonio)", roe, "%", 0, 25, "Flex"),
        metric("net_margin", "Margen neto", net_margin, "%", 0, 20, "Ancla"),
    ]
    crecimiento = [
        metric("rev_cagr", "CAGR de ingresos", rev_cagr, "%", -5, 20, "Ancla"),
        metric("eps_cagr", "CAGR de EPS (ganancia/acción)", eps_cagr, "%", -10, 25, "Flex"),
    ]

    p_val = _avg([m["subscore"] for m in valuacion])
    p_sal = _avg([m["subscore"] for m in salud])
    p_cre = _avg([m["subscore"] for m in crecimiento])

    pillars = {
        "valuacion": {"score": p_val, "weight": PILLAR_WEIGHTS["valuacion"], "metrics": valuacion},
        "salud_financiera": {"score": p_sal, "weight": PILLAR_WEIGHTS["salud_financiera"], "metrics": salud},
        "crecimiento": {"score": p_cre, "weight": PILLAR_WEIGHTS["crecimiento"], "metrics": crecimiento},
    }

    weighted = 0.0
    wsum = 0.0
    for p in pillars.values():
        if p["score"] is not None:
            weighted += p["score"] * p["weight"]
            wsum += p["weight"]
    overall = round(weighted / wsum, 1) if wsum else None

    return {
        "overall_score": overall,
        "band": band_for(overall) if overall is not None else "Sin dato suficiente",
        "coverage": round(wsum / sum(PILLAR_WEIGHTS.values()) * 100),
        "pillars": pillars,
        "raw": {
            "market_cap": market_cap, "shares": shares, "revenue": revenue,
            "net_income": net_income, "equity": equity, "fcf": fcf,
            "rev_series": rev_series, "eps_series": eps_series,
        },
    }


def _next_concept(facts: dict, concepts: list[str], unit: str = "USD") -> str:
    """Devuelve el primer concepto XBRL con datos anuales, para series temporales."""
    for c in concepts:
        if sec.annual_series(facts, c, unit):
            return c
    return concepts[0]
