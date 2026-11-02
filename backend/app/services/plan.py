"""Piano economico-finanziario a 3 anni (conto economico, flussi di cassa, debito, DSCR annuo).

Si parte dai numeri dell'ultimo esercizio (o dell'anno in corso riportato a 12 mesi) e si applicano le ipotesi
dell'utente anno per anno. È uno strumento di simulazione: le ipotesi sono dell'imprenditore.
"""
from datetime import date

from ..utils import today
from .accounting_close import asset_schedule
from .analysis import _sum
from .accounting_reports import financial_statements
from .loans import CREDIT_LINES, schedule

DEFAULT_YEAR = {"revenue_growth": 5.0, "variable_cost_pct": None, "fixed_cost_growth": 2.0, "staff_growth": 3.0,
                "capex_cents": 0, "capex_rate": 20.0, "new_loan_cents": 0, "new_loan_rate": 5.0, "new_loan_months": 60,
                "dso_days": None, "dpo_days": None, "tax_rate": 27.9}


async def base_figures(db, company: dict) -> dict:
    """Valori di partenza: ultimo esercizio chiuso con dati, altrimenti l'anno in corso riportato a 12 mesi."""
    t = today()
    st = await financial_statements(db, company["id"], t.year)
    ce = st["voci"]["ce"]
    elapsed = (t - date(t.year, 1, 1)).days + 1
    factor = 365 / elapsed
    source = f"anno {t.year} riportato a 12 mesi ({elapsed} giorni di dati)"
    prev = st["voci"]["ce_prev"]
    if _sum(prev, "CE.A.1") > 0 and elapsed < 180:
        ce, factor, source = prev, 1.0, f"esercizio {t.year - 1}"
    sp = st["voci"]["sp"]

    def y(v):
        return round(v * factor)
    ricavi = y(_sum(ce, "CE.A"))
    variable = y(_sum(ce, "CE.B.6") + _sum(ce, "CE.B.7") + _sum(ce, "CE.B.11"))
    fixed = y(_sum(ce, "CE.B.8") + _sum(ce, "CE.B.14"))
    staff = y(_sum(ce, "CE.B.9"))
    crediti = _sum(sp, "SP.A.C.II.1")
    fornitori = _sum(sp, "SP.P.D.7")
    banks = await db.bank_accounts.find({"company_id": company["id"], "status": {"$ne": "scollegato"}}, {"balance_cents": 1}).to_list(50)
    return {"source": source, "ricavi": ricavi, "variable": variable, "fixed": fixed, "staff": staff,
            "variable_pct": round(variable / ricavi * 100, 1) if ricavi else 60.0,
            "dso_days": round(crediti / (ricavi * 1.22) * 365) if ricavi else 60,
            "dpo_days": round(fornitori / (variable * 1.22) * 365) if variable else 60,
            "crediti": crediti, "fornitori": fornitori, "cash": sum(b.get("balance_cents", 0) for b in banks),
            "patrimonio": _sum(sp, "SP.P.A")}


async def project(db, company: dict, assumptions: list[dict] | None = None) -> dict:
    base = await base_figures(db, company)
    t = today()
    start_year = t.year + 1 if t.month >= 10 else t.year
    years = [start_year, start_year + 1, start_year + 2]
    hyp = [{**DEFAULT_YEAR, **(assumptions[i] if assumptions and i < len(assumptions) else {})} for i in range(3)]
    loans = await db.loans.find({"company_id": company["id"], "active": {"$ne": False}}, {"_id": 0}).to_list(200)
    assets = await db.assets.find({"company_id": company["id"]}, {"_id": 0}).to_list(2000)

    revenue, variable_pct, fixed, staff = base["ricavi"], base["variable_pct"], base["fixed"], base["staff"]
    receivables, payables, cash = base["crediti"], base["fornitori"], base["cash"]
    new_loans: list[dict] = []
    new_assets: list[dict] = []
    rows = []
    for i, (yr, h) in enumerate(zip(years, hyp)):
        revenue = round(revenue * (1 + h["revenue_growth"] / 100))
        vpct = h["variable_cost_pct"] if h["variable_cost_pct"] is not None else variable_pct
        var_cost = round(revenue * vpct / 100)
        fixed = round(fixed * (1 + h["fixed_cost_growth"] / 100))
        staff = round(staff * (1 + h["staff_growth"] / 100))
        ebitda = revenue - var_cost - fixed - staff

        if h["capex_cents"]:
            new_assets.append({"cost_cents": int(h["capex_cents"]), "rate": h["capex_rate"], "purchase_date": f"{yr}-07-01",
                               "first_year_half": True})
        depreciation = 0
        for a in assets + new_assets:
            row = next((r for r in asset_schedule(a, yr) if r["year"] == yr), None)
            depreciation += row["quota_cents"] if row else 0
        if h["new_loan_cents"]:
            new_loans.append({"kind": "finanziamento", "principal_cents": int(h["new_loan_cents"]), "rate": h["new_loan_rate"],
                              "months": int(h["new_loan_months"]), "start_date": f"{yr}-02-01", "installment_cents": 0,
                              "lender": "Nuovo finanziamento", "active": True})
        interest = principal = 0
        debt_end = 0
        for loan in loans + new_loans:
            if loan["kind"] in CREDIT_LINES:
                continue
            sched = schedule(loan)
            for r in sched:
                if r["date"][:4] == str(yr):
                    interest += r["interest_cents"]
                    principal += r["principal_cents"]
            if loan.get("principal_cents"):
                past = [r for r in sched if r["date"] <= f"{yr}-12-31"]
                debt_end += past[-1]["residual_cents"] if past else loan["principal_cents"]
        ebit = ebitda - depreciation
        ebt = ebit - interest
        taxes = round(max(0, ebt) * h["tax_rate"] / 100)
        net = ebt - taxes

        dso = h["dso_days"] if h["dso_days"] is not None else base["dso_days"]
        dpo = h["dpo_days"] if h["dpo_days"] is not None else base["dpo_days"]
        new_rec = round(revenue * 1.22 * dso / 365)
        new_pay = round(var_cost * 1.22 * dpo / 365)
        delta_wc = (new_rec - receivables) - (new_pay - payables)
        receivables, payables = new_rec, new_pay
        operating_cf = ebitda - taxes - delta_wc
        service = principal + interest
        cash_flow = operating_cf - int(h["capex_cents"]) * 1.22 + int(h["new_loan_cents"]) - service
        cash = round(cash + cash_flow)
        rows.append({"year": yr, "ricavi": revenue, "costi_variabili": var_cost, "costi_fissi": fixed, "personale": staff,
                     "ebitda": ebitda, "ammortamenti": depreciation, "ebit": ebit, "interessi": interest, "imposte": taxes,
                     "utile": net, "variazione_circolante": delta_wc, "flusso_operativo": operating_cf,
                     "investimenti": int(h["capex_cents"]), "nuovi_finanziamenti": int(h["new_loan_cents"]),
                     "rimborsi_capitale": principal, "servizio_debito": service, "cassa_fine": cash,
                     "debito_fine": debt_end, "pfn": debt_end - cash,
                     "dscr": round(operating_cf / service, 2) if service else None,
                     "ebitda_margin": round(ebitda / revenue * 100, 1) if revenue else None})
    return {"base": base, "years": years, "assumptions": hyp, "rows": rows,
            "note": "Simulazione basata sulle tue ipotesi: IVA al 22% su crediti e debiti, imposte stimate sull'utile, "
                    "nuovi investimenti a metà anno e nuovi finanziamenti da febbraio."}


