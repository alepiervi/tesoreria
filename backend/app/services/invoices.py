"""Registrazione delle fatture e creazione automatica delle scadenze collegate."""
from datetime import timedelta

from ..utils import new_id, now_iso, parse_date


def norm_vat(v: str) -> str:
    v = (v or "").upper().replace(" ", "").strip()
    return v[2:] if v.startswith("IT") else v


def _same_vat(a: str, b: str) -> bool:
    return bool(norm_vat(a)) and norm_vat(a) == norm_vat(b)


async def group_company_by_vat(db, vat: str, exclude_id: str | None = None) -> dict | None:
    """Se la partita IVA è di un'altra azienda del gruppo, restituisce quell'azienda."""
    if not norm_vat(vat):
        return None
    async for c in db.companies.find({}, {"_id": 0, "id": 1, "name": 1, "vat_number": 1}):
        if c["id"] != exclude_id and _same_vat(c.get("vat_number", ""), vat):
            return c
    return None


def payable(inv: dict) -> int:
    """Importo che si incassa o paga davvero: totale meno ritenuta d'acconto e, con lo split payment,
    meno l'IVA (che il cliente pubblico versa direttamente all'Erario)."""
    return inv.get("payable_cents", inv["total_cents"])


def invoice_status(total_cents: int, paid_cents: int) -> str:
    if paid_cents <= 0:
        return "aperta"
    if paid_cents >= total_cents:
        return "pagata"
    return "parziale"


async def register_invoice(db, company: dict, doc: dict, source: str, xml: str | None = None,
                           direction: str | None = None) -> tuple[dict, bool]:
    """Salva una fattura letta da FatturaPA (o inserita a mano).

    Restituisce (fattura, creata). Se la fattura esiste già non la duplica.
    """
    if direction is None:
        if _same_vat(doc["seller"]["vat"], company.get("vat_number", "")):
            direction = "attiva"
        elif _same_vat(doc["buyer"]["vat"], company.get("vat_number", "")):
            direction = "passiva"
        else:
            raise ValueError(
                f"La fattura {doc['number']} non riguarda {company['name']}: "
                "la partita IVA non corrisponde né al cedente né al cessionario.")
    counterparty = doc["buyer"] if direction == "attiva" else doc["seller"]

    existing = await db.invoices.find_one({
        "company_id": company["id"], "direction": direction, "number": doc["number"],
        "date": doc["date"], "counterparty_vat": counterparty["vat"],
    })
    if existing:
        existing.pop("_id", None)
        return existing, False

    group_party = await group_company_by_vat(db, counterparty["vat"], company["id"])
    vat_cents = doc.get("vat_cents")
    taxable_cents = doc.get("taxable_cents")
    breakdown = doc.get("vat_breakdown")
    if vat_cents is None:
        # fattura inserita a mano: si stima l'IVA dall'aliquota indicata (default 22%)
        rate = doc.get("vat_rate", 22)
        taxable_cents = round(doc["total_cents"] / (1 + rate / 100))
        vat_cents = doc["total_cents"] - taxable_cents
        breakdown = [{"rate": float(rate), "nature": "" if rate else "N2.2", "taxable_cents": taxable_cents,
                      "vat_cents": vat_cents}]
    if not breakdown:
        breakdown = [{"rate": round(vat_cents / taxable_cents * 100, 2) if taxable_cents else 0.0, "nature": "",
                      "taxable_cents": taxable_cents, "vat_cents": vat_cents}]
    withholding = doc.get("withholding_cents", 0) or 0
    split = bool(doc.get("split_payment")) and direction == "attiva"
    payable_cents = doc["total_cents"] - withholding - (vat_cents if split else 0)
    # Data di registrazione: la data del documento, oppure il primo giorno non ancora chiuso in contabilità
    registration_date = doc["date"]
    lock = company.get("accounting_lock_date")
    if lock and registration_date <= lock:
        registration_date = (parse_date(lock) + timedelta(days=1)).isoformat()
    installments = [i for i in doc.get("installments", []) if i.get("due_date")]
    if not installments:
        due = (parse_date(doc["date"]) + timedelta(days=30)).isoformat()
        installments = [{"due_date": due, "amount_cents": payable_cents}]
    invoice = {
        "id": new_id(),
        "company_id": company["id"],
        "direction": direction,
        "taxable_cents": taxable_cents,
        "vat_cents": vat_cents,
        "split_payment": doc.get("split_payment", False),
        "vat_breakdown": breakdown,
        "withholding_cents": withholding,
        "stamp_cents": doc.get("stamp_cents", 0) or 0,
        "payable_cents": payable_cents,
        "registration_date": registration_date,
        "account_code": None,  # conto di costo o ricavo scelto a mano (altrimenti quello predefinito)
        "cost_center_id": None,
        "intercompany_company_id": group_party["id"] if group_party else None,
        "number": doc["number"],
        "date": doc["date"],
        "doc_type": doc.get("doc_type", "TD01"),
        "counterparty_name": counterparty["name"],
        "counterparty_vat": counterparty["vat"],
        "description": doc.get("description", ""),
        "total_cents": doc["total_cents"],
        "paid_cents": 0,
        "status": "aperta",
        "due_date": min(i["due_date"] for i in installments),
        "iban": doc.get("iban", ""),
        "source": source,
        "has_xml": xml is not None,
        "created_at": now_iso(),
    }
    await db.invoices.insert_one(dict(invoice))
    if xml is not None:
        await db.invoice_xml.insert_one({"invoice_id": invoice["id"], "company_id": company["id"], "xml": xml})
    from .accounting import sync_source
    await sync_source(db, "invoice", invoice["id"])

    if invoice["payable_cents"] > 0:
        kind = "incasso" if direction == "attiva" else "pagamento"
        for n, inst in enumerate(installments, start=1):
            label = f"Fattura {doc['number']} · {counterparty['name']}"
            if len(installments) > 1:
                label += f" (rata {n}/{len(installments)})"
            await db.deadlines.insert_one({
                "id": new_id(), "company_id": company["id"], "kind": kind,
                "description": label, "due_date": inst["due_date"],
                "amount_cents": inst["amount_cents"] or invoice["payable_cents"],
                "invoice_id": invoice["id"], "beneficiary": counterparty["name"],
                "iban": doc.get("iban", "") if kind == "pagamento" else "",
                "status": "aperta" if kind == "incasso" else "da_pagare",
                "created_at": now_iso(),
            })
    return invoice, True


async def refresh_invoice_deadlines(db, invoice: dict):
    """Allinea lo stato delle scadenze allo stato della fattura."""
    done_status = "incassato" if invoice["direction"] == "attiva" else "pagato"
    if invoice["status"] == "pagata":
        await db.deadlines.update_many({"invoice_id": invoice["id"]}, {"$set": {"status": done_status}})
    else:
        open_status = "aperta" if invoice["direction"] == "attiva" else "da_pagare"
        await db.deadlines.update_many(
            {"invoice_id": invoice["id"], "status": done_status}, {"$set": {"status": open_status}})
