"""Chiusura mensile guidata: cosa va fatto a fine mese, chi lo fa, cosa manca. Alla fine si blocca il mese."""
from datetime import date, timedelta

from ..utils import now_iso, today
from .accounting import balances, load_chart

ROLE_LABELS = {"amministrazione": "Amministrazione", "commercialista": "Commercialista"}


def month_bounds(month: str) -> tuple[str, str]:
    y, m = int(month[:4]), int(month[5:7])
    end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return f"{month}-01", end.isoformat()


def previous_month(ref: date | None = None) -> str:
    ref = ref or today()
    d = ref.replace(day=1) - timedelta(days=1)
    return d.strftime("%Y-%m")


async def checklist(db, company: dict, month: str) -> dict:
    cid = company["id"]
    start, end = month_bounds(month)
    state = await db.month_closes.find_one({"company_id": cid, "month": month}, {"_id": 0}) or {}
    manual = state.get("items", {})
    items = []

    def add(id_, title, role, auto_ok, detail, link=None, applicable=True, manual_only=False):
        m = manual.get(id_, {})
        done = bool(m.get("done")) if manual_only else auto_ok
        items.append({"id": id_, "title": title, "role": role, "role_label": ROLE_LABELS[role], "done": done if applicable else True,
                      "applicable": applicable, "auto": not manual_only, "detail": detail, "link": link,
                      "done_by": m.get("by_name"), "done_at": m.get("at"), "note": m.get("note", "")})

    # 1. estratti conto aggiornati
    stale = []
    async for b in db.bank_accounts.find({"company_id": cid, "status": {"$ne": "scollegato"}}, {"_id": 0}):
        last = b.get("last_import_to") or b.get("balance_date") or (b.get("last_sync_at") or "")[:10]
        if not last or last < end:
            stale.append(f"{b['bank_name']} {b.get('label', '')}".strip())
    add("banche", "Movimenti bancari aggiornati a fine mese", "amministrazione", not stale,
        "Tutti i conti sono aggiornati." if not stale else "Da aggiornare o importare: " + ", ".join(stale), "/impostazioni")

    # 2. movimenti sistemati
    pending = await db.transactions.count_documents({"company_id": cid, "status": "da_riconciliare", "date": {"$gte": start, "$lte": end}})
    add("riconciliazione", "Movimenti del mese riconciliati", "amministrazione", pending == 0,
        "Tutti i movimenti sono abbinati o spiegati." if not pending else (f"{pending} movimenti da riconciliare." if pending > 1 else "1 movimento da riconciliare."), "/riconciliazione")

    # 3. fatture classificate
    chart = await load_chart(db, company)
    from .account_suggest import to_classify
    unclassified = len(await to_classify(db, company, chart, start, end))
    add("fatture", "Fatture di acquisto con il conto giusto", "commercialista", unclassified == 0,
        "Nessuna fattura sul conto generico." if not unclassified else (f"{unclassified} fatture da classificare." if unclassified > 1 else "1 fattura da classificare."),
        "/contabilita/da-classificare")

    # 4. paghe
    has_staff = bool(company.get("payroll_enabled")) or bool(await db.recurring.find_one(
        {"company_id": cid, "active": True, "description": {"$regex": "stipend", "$options": "i"}}))
    payroll = await db.payrolls.find_one({"company_id": cid, "month": month})
    add("paghe", "Paghe del mese registrate", "amministrazione", bool(payroll),
        "Registrate." if payroll else "Inserisci il riepilogo paghe del consulente del lavoro.", "/paghe", applicable=has_staff)

    # 5. F24 del mese pagati
    f24_open = await db.deadlines.count_documents({"company_id": cid, "kind": "f24", "due_date": {"$gte": start, "$lte": end},
                                                   "status": {"$in": ["da_pagare", "in_attesa_autorizzazione"]}})
    add("f24", "F24 in scadenza nel mese pagati", "amministrazione", f24_open == 0,
        "Nessun F24 in sospeso." if not f24_open else f"{f24_open} F24 non risultano pagati.", "/scadenze")

    # 6. liquidazione IVA (solo se un periodo IVA finisce in questo mese)
    from .vat import periods_for
    mode = company.get("vat_period", "mensile")
    period = next((p for p in periods_for(int(month[:4]), mode) if p["end"].isoformat() == end), None)
    posted = bool(period) and bool(await db.entries.find_one({"company_id": cid, "source_key": f"liqiva:{period['key']}"}))
    add("iva", "Liquidazione IVA registrata", "commercialista", posted,
        (f"Periodo {period['label']}: " + ("registrata." if posted else "da registrare (Chiusure e rettifiche).")) if period else
        "Nessuna liquidazione IVA questo mese.", "/contabilita/chiusure", applicable=bool(period) and end < today().isoformat())

    # 7. nessun importo da attribuire
    trans = chart.by_key.get("transitorio")
    bal = (await balances(db, cid, None, end)).get(trans, {}).get("saldo", 0) if trans else 0
    add("transitorio", "Nessun importo da attribuire", "commercialista", bal == 0,
        "Il conto transitorio è a zero." if not bal else f"Sul conto {trans} restano {abs(bal) / 100:,.2f} €.".replace(",", "X").replace(".", ",").replace("X", "."),
        f"/contabilita/piano-conti?conto={trans}")

    # 8. chiarimenti
    questions = await db.notes.count_documents({"company_id": cid, "is_question": True, "resolved": False})
    add("chiarimenti", "Domande del commercialista risolte", "amministrazione", questions == 0,
        "Nessuna domanda aperta." if not questions else f"{questions} domande in attesa di risposta.", "/chiarimenti")

    # 9-10. controlli manuali
    add("documenti", "Documenti del mese caricati (F24 quietanzati, contratti, spese senza fattura)", "amministrazione", False,
        "Da spuntare a mano.", "/documenti", manual_only=True)
    add("revisione", "Prima nota controllata", "commercialista", False, "Da spuntare a mano dal commercialista.",
        "/contabilita/prima-nota", manual_only=True)

    lock = company.get("accounting_lock_date") or ""
    closed = lock >= end
    todo = [i for i in items if i["applicable"] and not i["done"]]
    return {"month": month, "from": start, "to": end, "items": items, "closed": closed, "lock_date": lock or None,
            "closed_by": state.get("closed_by_name"), "closed_at": state.get("closed_at"),
            "ready": not todo, "missing": len(todo), "month_ended": end < today().isoformat(),
            "previous_open": bool(lock) and lock < (date.fromisoformat(start) - timedelta(days=1)).isoformat() and
            not closed and month > lock[:7]}


async def set_manual(db, company_id: str, month: str, item: str, done: bool, note: str, user: dict) -> None:
    await db.month_closes.update_one({"company_id": company_id, "month": month}, {"$set": {
        "company_id": company_id, "month": month,
        f"items.{item}": {"done": done, "note": note, "by": user["id"], "by_name": user.get("name") or user["email"], "at": now_iso()}}},
        upsert=True)


async def close(db, company: dict, month: str, user: dict) -> str:
    _, end = month_bounds(month)
    lock = company.get("accounting_lock_date") or ""
    if lock >= end:
        return lock
    await db.companies.update_one({"id": company["id"]}, {"$set": {"accounting_lock_date": end}})
    await db.month_closes.update_one({"company_id": company["id"], "month": month}, {"$set": {
        "company_id": company["id"], "month": month, "closed_at": now_iso(), "closed_by": user["id"], "previous_lock": lock or None,
        "closed_by_name": user.get("name") or user["email"]}}, upsert=True)
    return end


async def reopen(db, company: dict, month: str) -> str:
    start, end = month_bounds(month)
    lock = company.get("accounting_lock_date") or ""
    if lock != end:
        raise ValueError("Si può riaprire solo l'ultimo mese chiuso.")
    if await db.entries.find_one({"company_id": company["id"], "source_key": f"close:{month[:4]}:sp"}):
        raise ValueError("L'esercizio è chiuso: riapri prima l'esercizio.")
    state = await db.month_closes.find_one({"company_id": company["id"], "month": month}) or {}
    new_lock = state.get("previous_lock") if "previous_lock" in state else (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    await db.companies.update_one({"id": company["id"]}, {"$set": {"accounting_lock_date": new_lock}})
    await db.month_closes.update_one({"company_id": company["id"], "month": month}, {"$set": {"closed_at": None, "closed_by_name": None}})
    return new_lock or ""
