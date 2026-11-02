"""Centrale Rischi della Banca d'Italia: dati mensili per banca, inseriti a mano dal prospetto (o letti dal PDF).

Categorie principali del prospetto: rischi autoliquidanti (anticipi fatture, SBF), rischi a scadenza (mutui,
finanziamenti, leasing), rischi a revoca (fidi di cassa), garanzie rilasciate (crediti di firma).
"""
from collections import defaultdict

CATEGORIES = {
    "autoliquidanti": "Rischi autoliquidanti (anticipi, SBF)",
    "scadenza": "Rischi a scadenza (mutui, finanziamenti, leasing)",
    "revoca": "Rischi a revoca (fidi di cassa)",
    "firma": "Garanzie e crediti di firma",
}

READ_PROMPT = (
    "Questo è un prospetto della Centrale Rischi della Banca d'Italia di un'impresa. Rispondi SOLO con JSON: "
    '{"mese": "AAAA-MM", "righe": [{"banca": "nome", "categoria": "autoliquidanti|scadenza|revoca|firma", '
    '"accordato": numero, "utilizzato": numero, "sconfinamento": numero, "scaduto": numero}]}. '
    "Importi in euro. Lo sconfinamento è la parte di utilizzato oltre l'accordato operativo; lo scaduto sono le rate "
    "o gli importi scaduti e non pagati. Se un dato manca usa 0."
)


async def summary(db, company_id: str, loans: list[dict]) -> dict:
    rows = await db.central_risk.find({"company_id": company_id}, {"_id": 0}).sort([("month", -1), ("bank", 1)]).to_list(3000)
    months = sorted({r["month"] for r in rows}, reverse=True)
    trend = []
    for m in sorted(months)[-12:]:
        rs = [r for r in rows if r["month"] == m]
        trend.append({"month": m, "granted_cents": sum(r["granted_cents"] for r in rs), "used_cents": sum(r["used_cents"] for r in rs),
                      "overdraft_cents": sum(r["overdraft_cents"] + r["past_due_cents"] for r in rs)})
    latest = [r for r in rows if months and r["month"] == months[0]]
    by_bank: dict[str, dict] = defaultdict(lambda: {"granted_cents": 0, "used_cents": 0, "overdraft_cents": 0, "past_due_cents": 0})
    for r in latest:
        b = by_bank[r["bank"]]
        for k in ("granted_cents", "used_cents", "overdraft_cents", "past_due_cents"):
            b[k] += r[k]
    banks = [{"bank": k, **v, "usage": v["used_cents"] / v["granted_cents"] if v["granted_cents"] else None} for k, v in by_bank.items()]
    # confronto con i fidi inseriti in Finanziamenti
    program: dict[str, int] = defaultdict(int)
    for loan in loans:
        if loan["kind"] in {"fido", "anticipo_fatture"} and loan.get("active", True):
            program[loan["lender"].strip().lower()] += int(loan.get("limit_cents") or 0)
    diffs = []
    for b in banks:
        cr_granted = sum(r["granted_cents"] for r in latest if r["bank"] == b["bank"] and r["category"] in {"autoliquidanti", "revoca"})
        mine = program.get(b["bank"].strip().lower())
        if mine is not None and mine != cr_granted:
            diffs.append({"bank": b["bank"], "program_cents": mine, "central_risk_cents": cr_granted})
    return {"months": months, "latest_month": months[0] if months else None, "rows": [r for r in rows if months and r["month"] == months[0]],
            "banks": sorted(banks, key=lambda b: -b["used_cents"]), "trend": trend, "differences": diffs,
            "categories": CATEGORIES}
