"""Notifiche: nel programma (campanella), via email e via WhatsApp.

- notify(): invia una notifica a uno o più utenti, rispettando le loro preferenze.
- run_daily_alerts(): controlla ogni giorno scadenze, previsione, consensi, conti da aggiornare, budget.
- send_weekly_digests(): riepilogo settimanale via email.
Gli avvisi con una "chiave" non vengono ripetuti: lo stesso avviso arriva una volta sola.
"""
from .invoices import payable
from datetime import timedelta

from ..config import settings
from ..integrations.messaging import html_page, send_email, send_whatsapp
from ..permissions import has_permission
from ..utils import new_id, now_iso, parse_date, today

DEFAULT_PREFS = {
    "email_alerts": True,       # avvisi importanti via email
    "whatsapp_alerts": False,   # avvisi importanti via WhatsApp
    "whatsapp_number": "",
    "weekly_digest": True,      # riepilogo del lunedì
    "monthly_report": False,    # report PDF il primo del mese
}


def prefs_of(user: dict) -> dict:
    return {**DEFAULT_PREFS, **(user.get("notify") or {})}


def _eur(cents: int) -> str:
    v = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if cents < 0 else ''}{v} €"


async def users_with(db, company_id: str, permission: str) -> list[dict]:
    ids = [m["user_id"] async for m in db.memberships.find({"company_id": company_id}, {"user_id": 1, "role": 1})
           if has_permission(m["role"], permission)]
    return await db.users.find({"id": {"$in": ids}, "active": {"$ne": False}}, {"_id": 0}).to_list(500)


async def notify(db, users: list[dict], *, kind: str, title: str, body: str, link: str = "/",
                 company_id: str | None = None, key: str | None = None, important: bool = False) -> int:
    """Crea la notifica nel programma e, se importante, la manda anche via email/WhatsApp secondo le preferenze."""
    sent = 0
    for u in users:
        if key and await db.notifications.find_one({"user_id": u["id"], "key": key}):
            continue
        await db.notifications.insert_one({
            "id": new_id(), "user_id": u["id"], "company_id": company_id, "kind": kind, "title": title,
            "body": body, "link": link, "key": key, "important": important, "read_at": None, "created_at": now_iso(),
        })
        sent += 1
        if not important:
            continue
        p = prefs_of(u)
        url = settings.frontend_url + link
        if p["email_alerts"]:
            await send_email(u["email"], f"Tesoreria · {title}", f"{body}\n\n{url}",
                             html_page(title, [body], link=url), meta={"kind": kind})
        if p["whatsapp_alerts"] and p["whatsapp_number"]:
            await send_whatsapp(p["whatsapp_number"], f"{title}: {body}", meta={"kind": kind})
    return sent


async def _company_names(db) -> dict:
    return {c["id"]: c["name"] async for c in db.companies.find({}, {"id": 1, "name": 1})}


async def run_daily_alerts(db) -> int:
    """Controlli giornalieri. Restituisce il numero di notifiche create."""
    from .forecast import weekly_forecast
    from .budget import budget_status

    t = today()
    week = f"{t.isocalendar().year}-W{t.isocalendar().week}"
    names = await _company_names(db)
    created = 0
    for cid, cname in names.items():
        payers = await users_with(db, cid, "request_payment")

        # Pagamenti in scadenza entro 3 giorni o scaduti
        soon = (t + timedelta(days=3)).isoformat()
        async for d in db.deadlines.find({"company_id": cid, "status": "da_pagare", "due_date": {"$lte": soon}}):
            overdue = d["due_date"] < t.isoformat()
            created += await notify(
                db, payers, kind="scadenza", company_id=cid, link="/scadenze", important=True,
                key=f"scad{'-scaduta' if overdue else ''}:{d['id']}:{d['due_date']}",
                title=("Pagamento scaduto" if overdue else "Pagamento in scadenza") + f" · {cname}",
                body=f"{d['description']}: {_eur(d['amount_cents'])}, scadenza {parse_date(d['due_date']).strftime('%d/%m/%Y')}.")

        # Crediti scaduti da sollecitare (un avviso a settimana per azienda)
        overdue_inv = await db.invoices.find({"company_id": cid, "direction": "attiva", "status": {"$in": ["aperta", "parziale"]},
                                              "due_date": {"$lt": t.isoformat()}, "intercompany_company_id": None}).to_list(1000)
        if overdue_inv:
            total = sum(payable(i) - i.get("paid_cents", 0) for i in overdue_inv)
            created += await notify(
                db, await users_with(db, cid, "send_reminders"), kind="crediti", company_id=cid, link="/crediti",
                key=f"crediti:{cid}:{week}", important=True,
                title=f"Crediti scaduti · {cname}",
                body=f"{len(overdue_inv)} fatture di clienti scadute e non incassate, per {_eur(total)}. Valuta i solleciti.")

        # Previsione di cassa
        fc = await weekly_forecast(db, [cid], 8)
        low = fc["lowest"]
        if fc["goes_negative"] or (low["week"] and low["balance_cents"] < fc["opening_balance_cents"] * 0.3):
            created += await notify(
                db, payers, kind="previsione", company_id=cid, link=f"/aziende/{cid}", important=True,
                key=f"previsione:{cid}:{week}",
                title=f"Liquidità in calo · {cname}",
                body=(f"Nella settimana {low['week']} il saldo previsto scende a {_eur(low['balance_cents'])}"
                      + (", sotto zero." if fc["goes_negative"] else ".")))

        # Consensi bancari e conti manuali
        bankers = await users_with(db, cid, "manage_banks")
        async for a in db.bank_accounts.find({"company_id": cid, "status": "attivo"}):
            if a.get("provider") == "manuale":
                last = a.get("last_import_to")
                if not last or (t - parse_date(last)).days > 7:
                    created += await notify(
                        db, bankers, kind="estratto_conto", company_id=cid, link=f"/aziende/{cid}",
                        key=f"import:{a['id']}:{last}:{week}",
                        title=f"Estratto conto da importare · {cname}",
                        body=f"{a['bank_name']} {a['iban_masked']}: " + (f"movimenti fermi al {parse_date(last).strftime('%d/%m/%Y')}." if last else "nessun estratto conto importato."))
            elif a.get("consent_expires_at"):
                days = (parse_date(a["consent_expires_at"]) - t).days
                if days <= 14:
                    created += await notify(
                        db, bankers, kind="consenso", company_id=cid, link=f"/aziende/{cid}", important=True,
                        key=f"consenso:{a['id']}:{a['consent_expires_at']}",
                        title=f"Consenso bancario in scadenza · {cname}",
                        body=f"{a['bank_name']} {a['iban_masked']}: il collegamento scade tra {days} giorni.")

        # Budget sforato nel mese
        status = await budget_status(db, cid, t.year, t.month)
        for row in status["rows"]:
            if row["budget_cents"] and row["actual_cents"] > row["budget_cents"]:
                created += await notify(
                    db, await users_with(db, cid, "manage_budget"), kind="budget", company_id=cid, link="/budget",
                    key=f"budget:{cid}:{row['category']}:{t.year}-{t.month}",
                    title=f"Budget superato · {cname}",
                    body=f"{row['category']}: speso {_eur(row['actual_cents'])} su {_eur(row['budget_cents'])} previsti questo mese.")
    return created


async def build_digest(db, user: dict) -> tuple[str, str, str] | None:
    """Riepilogo settimanale per un utente: (oggetto, testo, html)."""
    from .forecast import weekly_forecast
    mem = [m async for m in db.memberships.find({"user_id": user["id"]})]
    ids = [m["company_id"] for m in mem if has_permission(m["role"], "view")]
    if not ids:
        return None
    names = await _company_names(db)
    t = today()
    rows = []
    balance = 0
    async for a in db.bank_accounts.find({"company_id": {"$in": ids}, "status": "attivo"}):
        balance += a.get("balance_cents", 0)
    rows.append(("Liquidità totale", _eur(balance)))
    to_rec = await db.transactions.count_documents({"company_id": {"$in": ids}, "status": "da_riconciliare"})
    rows.append(("Movimenti da riconciliare", str(to_rec)))
    week_end = (t + timedelta(days=7)).isoformat()
    pay = inc = 0
    upcoming = []
    async for d in db.deadlines.find({"company_id": {"$in": ids}, "status": {"$in": ["aperta", "da_pagare", "in_attesa_autorizzazione"]},
                                      "due_date": {"$lte": week_end}}).sort("due_date", 1):
        if d["kind"] == "incasso":
            inc += d["amount_cents"]
        else:
            pay += d["amount_cents"]
        upcoming.append(d)
    rows.append(("Da pagare entro 7 giorni (scaduti inclusi)", _eur(pay)))
    rows.append(("Da incassare entro 7 giorni (scaduti inclusi)", _eur(inc)))
    overdue = await db.invoices.find({"company_id": {"$in": ids}, "direction": "attiva", "status": {"$in": ["aperta", "parziale"]},
                                      "due_date": {"$lt": t.isoformat()}, "intercompany_company_id": None}).to_list(2000)
    rows.append(("Crediti scaduti", _eur(sum(payable(i) - i.get("paid_cents", 0) for i in overdue))))
    fc = await weekly_forecast(db, ids, 8)
    rows.append(("Saldo minimo previsto (8 settimane)", _eur(fc["lowest"]["balance_cents"])))
    questions = await db.notes.count_documents({"company_id": {"$in": ids}, "is_question": True, "resolved": False})
    if questions:
        rows.append(("Chiarimenti aperti", str(questions)))
    for d in upcoming[:8]:
        sign = "+" if d["kind"] == "incasso" else "-"
        rows.append((f"{parse_date(d['due_date']).strftime('%d/%m')} · {names.get(d['company_id'], '')} · {d['description']}",
                     f"{sign} {_eur(d['amount_cents'])}"))
    subject = f"Tesoreria · riepilogo della settimana {t.strftime('%d/%m/%Y')}"
    intro = f"Ciao {user.get('name') or ''}, ecco la situazione delle tue aziende.".replace("Ciao ,", "Ciao,")
    text = intro + "\n\n" + "\n".join(f"{a}: {b}" for a, b in rows) + f"\n\n{settings.frontend_url}"
    return subject, text, html_page("Riepilogo settimanale", [intro], rows, settings.frontend_url)


async def send_weekly_digests(db, only_user_id: str | None = None) -> int:
    count = 0
    query = {"active": {"$ne": False}}
    if only_user_id:
        query["id"] = only_user_id
    async for u in db.users.find(query, {"_id": 0}):
        if not only_user_id and not prefs_of(u)["weekly_digest"]:
            continue
        digest = await build_digest(db, u)
        if digest:
            await send_email(u["email"], digest[0], digest[1], digest[2], meta={"kind": "riepilogo"})
            count += 1
    return count


async def send_monthly_reports(db) -> int:
    """Il primo del mese: report PDF del mese precedente a chi lo ha richiesto."""
    from .report import build_monthly_pdf
    t = today()
    prev = (t.replace(day=1) - timedelta(days=1))
    month = prev.strftime("%Y-%m")
    count = 0
    async for u in db.users.find({"active": {"$ne": False}}, {"_id": 0}):
        if not prefs_of(u)["monthly_report"]:
            continue
        ids = [m["company_id"] async for m in db.memberships.find({"user_id": u["id"]}) if has_permission(m["role"], "export")]
        if not ids:
            continue
        pdf = await build_monthly_pdf(db, ids, month, title="Gruppo" if len(ids) > 1 else None)
        await send_email(u["email"], f"Tesoreria · report di {prev.strftime('%m/%Y')}",
                         "In allegato il report mensile.", attachments=[(f"report_{month}.pdf", pdf, "application/pdf")],
                         meta={"kind": "report_mensile"})
        count += 1
    return count
