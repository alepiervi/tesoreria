"""Paghe: dal riepilogo mensile del consulente del lavoro alla registrazione contabile e alle scadenze.

Per ogni mese si inseriscono (o si leggono dal PDF con l'assistente) i totali del prospetto contabile:
lordo, contributi a carico azienda e dipendente, ritenute IRPEF, altre trattenute, netto, TFR maturato.
Il programma crea:
- la registrazione degli stipendi (STIP) con i debiti verso dipendenti, INPS ed Erario;
- la scadenza del netto da pagare ai dipendenti e quella dell'F24 del 16 del mese successivo;
- il collegamento "Personale → Dipendenti c/retribuzioni", così il bonifico degli stipendi chiude il debito.
"""
from datetime import date

from ..utils import new_id, now_iso, parse_date
from .accounting import AccountingError, Lines, load_chart, sync_company, upsert_auto_entry
from .withholding import MONTHS, _due

FIELDS = ("lordo", "contributi_ditta", "contributi_dipendente", "irpef", "altre_trattenute", "netto", "tfr")


def check(p: dict) -> list[str]:
    errors = []
    if p["lordo_cents"] <= 0 or p["netto_cents"] <= 0:
        errors.append("Lordo e netto devono essere maggiori di zero.")
    expected = p["netto_cents"] + p["irpef_cents"] + p["contributi_dipendente_cents"] + p["altre_trattenute_cents"]
    if abs(expected - p["lordo_cents"]) > 100:
        errors.append(f"Il lordo ({p['lordo_cents'] / 100:.2f}) deve essere uguale a netto + IRPEF + contributi del dipendente "
                      f"+ altre trattenute ({expected / 100:.2f}).".replace(".", ","))
    return errors


def label(month: str) -> str:
    return f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}"


async def post(db, company: dict, p: dict) -> None:
    """Registrazione degli stipendi del mese e scadenze collegate."""
    chart = await load_chart(db, company)
    y, m = int(p["month"][:4]), int(p["month"][5:7])
    month_end = date(y + (m == 12), m % 12 + 1, 1).toordinal() - 1
    entry_date = date.fromordinal(month_end).isoformat()
    L = Lines()
    # piccola differenza di arrotondamento del prospetto: va sul lordo
    diff = p["netto_cents"] + p["irpef_cents"] + p["contributi_dipendente_cents"] + p["altre_trattenute_cents"] - p["lordo_cents"]
    L.add(chart.k("costi_stipendi"), p["lordo_cents"] + diff, "D", cost_center_id=p.get("cost_center_id"))
    L.add(chart.k("costi_oneri_sociali"), p["contributi_ditta_cents"], "D", cost_center_id=p.get("cost_center_id"))
    L.add(chart.k("costi_tfr"), p["tfr_cents"], "D", cost_center_id=p.get("cost_center_id"))
    L.add(chart.k("debiti_dipendenti"), p["netto_cents"], "A", description="Netto in busta")
    L.add(chart.k("debiti_inps"), p["contributi_ditta_cents"] + p["contributi_dipendente_cents"], "A", description="Contributi INPS")
    L.add(chart.k("ritenute_da_versare"), p["irpef_cents"], "A", description="Ritenute IRPEF")
    L.add("40.06.02", p["altre_trattenute_cents"], "A", description="Altre trattenute (sindacati, cessioni, pignoramenti)")
    L.add(chart.k("fondo_tfr"), p["tfr_cents"], "A")
    dare, avere = L.totals()
    if dare != avere:
        raise AccountingError("La registrazione delle paghe non quadra.")
    entry = {"date": entry_date, "causale": "STIP", "description": f"Paghe {label(p['month'])} ({p.get('employees') or '—'} dipendenti)",
             "doc_number": None, "doc_date": None, "lines": L.items}
    res = await upsert_auto_entry(db, company, f"paghe:{p['id']}", entry, source="paghe")
    if res == "bloccata":
        raise AccountingError("Il mese è in un periodo contabile chiuso.")

    # scadenze: netto ai dipendenti e F24 (IRPEF + INPS) del 16 del mese dopo
    pay_date = p.get("pay_date") or entry_date
    f24 = p["irpef_cents"] + p["contributi_ditta_cents"] + p["contributi_dipendente_cents"]
    for role, desc, amount, due, kind, creditor in (
        ("netto", f"Stipendi {label(p['month'])}", p["netto_cents"], pay_date, "pagamento", "dipendenti"),
        ("f24", f"F24 paghe {label(p['month'])} (IRPEF e contributi)", f24, _due(p["month"]).isoformat(), "f24", "inps"),
    ):
        existing = await db.deadlines.find_one({"company_id": company["id"], "payroll_id": p["id"], "payroll_role": role})
        doc = {"description": desc, "amount_cents": amount, "due_date": due, "payroll_split": {
            "irpef": p["irpef_cents"], "inps": p["contributi_ditta_cents"] + p["contributi_dipendente_cents"]} if role == "f24" else None}
        if existing:
            if existing["status"] in {"da_pagare", "in_attesa_autorizzazione"}:
                await db.deadlines.update_one({"id": existing["id"]}, {"$set": doc})
        elif amount > 0:
            await db.deadlines.insert_one({"id": new_id(), "company_id": company["id"], "kind": kind, "invoice_id": None,
                                           "beneficiary": "Dipendenti" if role == "netto" else "Agenzia delle Entrate",
                                           "iban": "", "status": "da_pagare", "manual": False, "payroll_id": p["id"],
                                           "payroll_role": role, "payroll_month": p["month"], "creditor": creditor,
                                           "created_at": now_iso(), **doc})

    # da questo mese in poi il bonifico degli stipendi chiude il debito verso i dipendenti (non va a costo una seconda volta)
    start = company.get("payroll_from")
    if not start or p["month"] < start:
        await db.companies.update_one({"id": company["id"]}, {"$set": {"payroll_from": p["month"], "payroll_enabled": True}})
        await sync_company(db, company["id"])


async def remove(db, company: dict, p: dict) -> None:
    res = await upsert_auto_entry(db, company, f"paghe:{p['id']}", None, source="paghe")
    if res == "bloccata":
        raise AccountingError("Il mese è in un periodo contabile chiuso.")
    await db.deadlines.delete_many({"payroll_id": p["id"], "status": "da_pagare"})


def from_body(body: dict) -> dict:
    from ..utils import to_cents
    out = {"month": body["month"], "employees": int(body.get("employees") or 0) or None,
           "pay_date": body.get("pay_date") or None, "cost_center_id": body.get("cost_center_id") or None,
           "note": (body.get("note") or "").strip()}
    parse_date(out["month"] + "-01")
    for f in FIELDS:
        out[f"{f}_cents"] = to_cents(body.get(f) or 0)
        if out[f"{f}_cents"] < 0:
            raise ValueError("Gli importi non possono essere negativi.")
    return out
