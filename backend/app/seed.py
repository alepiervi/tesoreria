"""Dati di esempio: 3 aziende, 3 utenti con ruoli diversi, conti, movimenti, fatture e scadenze.

Si caricano solo se il database è vuoto e SEED_DEMO=true.
Utenti demo (password: variabile DEMO_PASSWORD, oppure generata a caso e mostrata nel log):
  titolare@demo.it        -> titolare di tutte le aziende
  amministrazione@demo.it -> amministrazione su tutte le aziende
  commercialista@demo.it  -> commercialista solo su Alfa e Beta
"""
import os
import random
import secrets
from datetime import date, timedelta

from .db import get_db
from .integrations.sdi import build_fatturapa_xml
from .security import hash_password
from .services.categories import categorize
from .services.invoices import register_invoice
from .utils import mask_iban, new_id, now_iso, today

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(12) + "7a"

COMPANIES = [
    {"key": "alfa", "name": "Azienda Alfa Srl", "vat": "11111111111", "scale": 1.0,
     "payroll": 28_600, "rent": 3_200, "balances": [152_140_00, 32_180_00],
     "banks": [("Banca A", "Conto principale"), ("Banca B", "Conto anticipi")], "consent": [142, 12]},
    {"key": "beta", "name": "Azienda Beta Srl", "vat": "22222222222", "scale": 0.45,
     "payroll": 9_800, "rent": 2_400, "balances": [62_910_00], "banks": [("Banca A", "Conto ordinario")],
     "consent": [88]},
    {"key": "gamma", "name": "Azienda Gamma Srl", "vat": "33333333333", "scale": 0.25,
     "payroll": 11_200, "rent": 1_500, "balances": [29_450_00, 12_330_00],
     "banks": [("Banca C", "Conto corrente"), ("Banca A", "Conto carte")], "consent": [160, 160]},
]

USERS = [
    {"email": "titolare@demo.it", "name": "Titolare (demo)", "is_owner": True, "role": "titolare",
     "companies": ["alfa", "beta", "gamma"]},
    {"email": "amministrazione@demo.it", "name": "Ufficio amministrazione (demo)", "is_owner": False,
     "role": "amministrazione", "companies": ["alfa", "beta", "gamma"]},
    {"email": "commercialista@demo.it", "name": "Studio commercialista (demo)", "is_owner": False,
     "role": "commercialista", "companies": ["alfa", "beta"]},
]

CLIENTI = ["Delta Spa", "Kappa Srl", "Studio Lambda", "Omicron Srl", "Rho Trasporti"]
FORNITORI = ["Omega Srl", "Sigma Forniture", "Tau Logistica", "Ypsilon Servizi"]


def _iban(rng) -> str:
    return "IT" + f"{rng.randint(10, 99)}" + "X" + "".join(str(rng.randint(0, 9)) for _ in range(22))


def _d(offset_days: int) -> str:
    return (today() + timedelta(days=offset_days)).isoformat()


def _month_day(months_ago: int, day: int) -> date | None:
    t = today()
    y, m = t.year, t.month - months_ago
    while m <= 0:
        y, m = y - 1, m + 12
    try:
        d = date(y, m, day)
    except ValueError:
        d = date(y, m, 28)
    return d if d <= t else None


def _tx(company_id, account_id, d: str, desc: str, cents: int, status="da_riconciliare", reason=None):
    return {"id": new_id(), "company_id": company_id, "account_id": account_id, "external_id": f"seed-{new_id()}",
            "date": d, "description": desc, "counterparty": "", "amount_cents": cents,
            "category": categorize(desc, cents), "category_manual": False, "status": status,
            "exclusion_reason": reason, "allocations": [], "created_at": now_iso()}


async def ensure_developer(email: str, password_hash: str, name: str) -> str | None:
    """Crea l'account Sviluppatore o converte quello esistente: niente titolarità e nessun accesso alle aziende."""
    db = get_db()
    if not email:
        return None
    email = email.strip().lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        has_access = await db.memberships.count_documents({"user_id": existing["id"]}) > 0
        if existing.get("is_developer") and not existing.get("is_owner") and not has_access:
            return None
        await db.memberships.delete_many({"user_id": existing["id"]})
        await db.users.update_one({"id": existing["id"]}, {"$set": {"is_developer": True, "is_owner": False},
                                                           "$inc": {"token_version": 1}})
        return "converted"
    if not password_hash.startswith("$2") or await db.users.count_documents({"is_developer": True}) > 0:
        return None
    await db.users.insert_one({
        "id": new_id(), "email": email, "name": name, "password_hash": password_hash,
        "is_owner": False, "is_developer": True, "active": True, "totp_enabled": False, "token_version": 0,
        "created_at": now_iso(),
    })
    return "created"


async def seed_if_empty() -> bool:
    db = get_db()
    if await db.users.count_documents({}) > 0:
        return False
    rng = random.Random(42)

    company_ids, accounts_by_company, company_docs = {}, {}, {}
    for c in COMPANIES:
        cid = new_id()
        company_ids[c["key"]] = cid
        doc = {"id": cid, "name": c["name"], "vat_number": c["vat"], "tax_code": c["vat"], "sdi_code": "",
               "pec": "", "address": "", "created_at": now_iso(), "created_by": None}
        company_docs[c["key"]] = doc
        await db.companies.insert_one(dict(doc))
        accounts_by_company[c["key"]] = []
        for (bank, label), balance, consent in zip(c["banks"], c["balances"], c["consent"]):
            iban = _iban(rng)
            acc = {"id": new_id(), "company_id": cid, "provider": "demo", "external_id": f"demo-{rng.randint(10**9, 10**10)}",
                   "bank_name": bank, "label": label, "iban": iban, "iban_masked": mask_iban(iban),
                   "balance_cents": balance, "balance_date": today().isoformat(),
                   "consent_expires_at": _d(consent), "status": "attivo", "last_sync_at": today().isoformat(),
                   "created_at": now_iso()}
            await db.bank_accounts.insert_one(dict(acc))
            accounts_by_company[c["key"]].append(acc)

    # Un conto senza collegamento automatico, aggiornato con l'import dell'estratto conto
    manual = accounts_by_company["gamma"][1]
    await db.bank_accounts.update_one({"id": manual["id"]}, {"$set": {
        "provider": "manuale", "external_id": None, "consent_expires_at": None, "last_sync_at": None,
        "last_import_at": None, "last_import_to": None, "balance_date": _d(-6)}})

    for u in USERS:
        uid = new_id()
        await db.users.insert_one({"id": uid, "email": u["email"], "name": u["name"],
                                   "password_hash": hash_password(DEMO_PASSWORD), "is_owner": u["is_owner"],
                                   "active": True, "totp_enabled": False, "token_version": 0, "created_at": now_iso()})
        for key in u["companies"]:
            await db.memberships.insert_one({"id": new_id(), "user_id": uid, "company_id": company_ids[key],
                                             "role": u["role"], "created_at": now_iso()})
        if u["is_owner"]:
            for doc in company_docs.values():
                await db.companies.update_one({"id": doc["id"]}, {"$set": {"created_by": uid}})

    # Storico movimenti degli ultimi 6 mesi (già sistemato) per grafici e previsioni
    history_cutoff = today() - timedelta(days=12)
    for c in COMPANIES:
        cid, acc = company_ids[c["key"]], accounts_by_company[c["key"]][0]["id"]
        s = c["scale"]
        txs = []
        for months_ago in range(5, -1, -1):
            plan = []
            for _ in range(rng.randint(4, 7)):
                plan.append((rng.randint(1, 28), f"Bonifico da {rng.choice(CLIENTI)} saldo fattura",
                             int(rng.randint(6000, 18000) * s) * 100))
            for _ in range(rng.randint(2, 4)):
                plan.append((rng.randint(1, 28), "Incassi POS", int(rng.randint(800, 4200) * s) * 100))
            for _ in range(rng.randint(2, 4)):
                plan.append((rng.randint(1, 28), f"Bonifico a {rng.choice(FORNITORI)}",
                             -int(rng.randint(1500, 9000) * s) * 100))
            plan.append((27, "Stipendi mese", -c["payroll"] * 100))
            plan.append((5, "Affitto sede", -c["rent"] * 100))
            plan.append((12, "Addebito SDD fornitura energia", -int(rng.randint(900, 2100) * s) * 100))
            plan.append((16, "Pagamento F24 Agenzia Entrate", -int(rng.randint(3000, 9000) * s) * 100))
            plan.append((28, "Commissioni bancarie", -rng.randint(12, 38) * 100))
            for day, desc, cents in plan:
                d = _month_day(months_ago, day)
                if d is None or d > history_cutoff:
                    continue
                txs.append(_tx(cid, acc, d.isoformat(), desc, cents, "escluso", "Storico importato"))
        await db.transactions.insert_many(txs)

    # ---- Situazioni attuali da gestire ----
    alfa, beta, gamma = company_docs["alfa"], company_docs["beta"], company_docs["gamma"]

    async def invoice(company, direction, number, issue_off, due_off, party, party_vat, euro, iban=""):
        seller = (company["name"], company["vat_number"]) if direction == "attiva" else (party, party_vat)
        buyer = (party, party_vat) if direction == "attiva" else (company["name"], company["vat_number"])
        xml = build_fatturapa_xml(number=number, issue_date=_d(issue_off), total_cents=euro * 100,
                                  due_date=_d(due_off), seller_name=seller[0], seller_vat=seller[1],
                                  buyer_name=buyer[0], buyer_vat=buyer[1], iban=iban)
        from .services.fatturapa import parse_fatturapa
        doc = parse_fatturapa(xml.encode())[0]
        inv, _ = await register_invoice(db, company, doc, "sdi", xml)
        return inv

    # Alfa: fatture attive e passive aperte + movimenti da abbinare
    await invoice(alfa, "attiva", "128/2026", -22, 8, "Delta Spa", "44444444444", 15_800)
    await invoice(alfa, "attiva", "125/2026", -40, -10, "Delta Spa", "44444444444", 7_320)
    await invoice(alfa, "attiva", "131/2026", -5, 25, "Kappa Srl", "55555555555", 4_880)
    await invoice(alfa, "passiva", "341", -35, -5, "Omega Srl", "01234567890", 9_350, "IT60X0542811101000000123456")
    await invoice(alfa, "passiva", "352", -20, 3, "Omega Srl", "01234567890", 7_420, "IT60X0542811101000000123456")
    await invoice(alfa, "passiva", "884/2026", -18, -3, "Energia Italia Spa", "66666666666", 1_840)
    await invoice(alfa, "passiva", "2026-77", -10, 20, "Tau Logistica Spa", "11223344556", 2_196, "IT02L1234512345123456789012")
    acc_alfa = accounts_by_company["alfa"][0]["id"]
    await db.transactions.insert_many([
        _tx(alfa["id"], acc_alfa, _d(-2), "BONIFICO DA DELTA SPA SALDO FT 125", 732_000),
        _tx(alfa["id"], acc_alfa, _d(-4), "BONIFICO A OMEGA SRL FT 341", -935_000),
        _tx(alfa["id"], acc_alfa, _d(-3), "SDD ENERGIA ITALIA RIF 10/2026", -184_000),
        _tx(alfa["id"], acc_alfa, _d(-6), "PAGAMENTO CARTA ***2210 FERRAMENTA", -31_240),
        _tx(alfa["id"], acc_alfa, _d(-1), "Stipendi mese", -2_860_000),
    ])

    # Beta: un bonifico che salda due fatture insieme + F24 in scadenza
    await invoice(beta, "attiva", "77/2026", -50, -12, "Delta Spa", "44444444444", 2_500)
    await invoice(beta, "attiva", "79/2026", -45, -8, "Delta Spa", "44444444444", 3_600)
    await invoice(beta, "passiva", "2026/410", -15, 14, "Sigma Forniture Srl", "09876543210", 4_780, "IT45R0300203280000400123456")
    acc_beta = accounts_by_company["beta"][0]["id"]
    await db.transactions.insert_many([
        _tx(beta["id"], acc_beta, _d(-5), "BONIFICO DA DELTA SPA SALDO FT 77 E 79", 610_000),
        _tx(beta["id"], acc_beta, _d(-2), "Commissioni bancarie", -1_800),
    ])
    await db.deadlines.insert_one({"id": new_id(), "company_id": beta["id"], "kind": "f24",
                                   "description": "F24 ritenute e contributi", "due_date": _d(18), "amount_cents": 493_000,
                                   "invoice_id": None, "beneficiary": "Agenzia delle Entrate", "iban": "",
                                   "status": "da_pagare", "manual": True, "created_at": now_iso()})

    # Gamma
    await invoice(gamma, "passiva", "2026-1021", -9, -2, "Ypsilon Servizi Srl", "77777777777", 180)
    await invoice(gamma, "attiva", "41/2026", -12, 18, "Rho Trasporti Srl", "88888888888", 5_300)
    acc_gamma = accounts_by_company["gamma"][0]["id"]
    await db.transactions.insert_many([
        _tx(gamma["id"], acc_gamma, _d(-3), "ADDEBITO CANONE YPSILON SERVIZI 10/26", -18_000),
    ])
    await db.deadlines.insert_one({"id": new_id(), "company_id": gamma["id"], "kind": "f24",
                                   "description": "F24 contributi dipendenti", "due_date": _d(18),
                                   "amount_cents": 421_000, "invoice_id": None, "beneficiary": "Agenzia delle Entrate",
                                   "iban": "", "status": "da_pagare", "manual": True, "created_at": now_iso()})

    # Spese ricorrenti per la previsione
    for key, items in {
        "alfa": [("uscita", "Stipendi", 28_900, 27), ("uscita", "Affitto sede", 3_200, 5)],
        "beta": [("uscita", "Stipendi", 9_800, 27), ("uscita", "Affitto sede", 2_400, 5)],
        "gamma": [("uscita", "Stipendi", 11_200, 27), ("uscita", "Affitto magazzino", 1_500, 5)],
    }.items():
        for kind, desc, euro, day in items:
            await db.recurring.insert_one({"id": new_id(), "company_id": company_ids[key], "kind": kind,
                                           "description": desc, "amount_cents": euro * 100, "day_of_month": day,
                                           "active": True, "created_at": now_iso()})

    await _seed_extras(db, company_ids, company_docs, accounts_by_company, invoice)
    return True


async def _seed_extras(db, company_ids, company_docs, accounts_by_company, invoice):
    """Dati di esempio per intercompany, crediti, budget, finanziamenti, IVA e notifiche."""
    from .services.vat import sync_all_vat
    alfa, beta, gamma = company_docs["alfa"], company_docs["beta"], company_docs["gamma"]
    acc_alfa, acc_beta = accounts_by_company["alfa"][0], accounts_by_company["beta"][0]

    # Periodicità IVA
    await db.companies.update_one({"id": beta["id"]}, {"$set": {"vat_period": "trimestrale"}})
    for c in (alfa, gamma):
        await db.companies.update_one({"id": c["id"]}, {"$set": {"vat_period": "mensile"}})

    # Intercompany: Alfa presta 10.000 € a Beta (due movimenti da abbinare) e un giroconto tra i conti di Alfa
    await db.transactions.insert_many([
        _tx(alfa["id"], acc_alfa["id"], _d(-8), "BONIFICO A AZIENDA BETA SRL FINANZIAMENTO SOCI", -1_000_000),
        _tx(beta["id"], acc_beta["id"], _d(-7), "BONIFICO DA AZIENDA ALFA SRL FINANZIAMENTO SOCI", 1_000_000),
        _tx(alfa["id"], acc_alfa["id"], _d(-9), "GIROCONTO A CONTO ANTICIPI", -500_000),
        _tx(alfa["id"], accounts_by_company["alfa"][1]["id"], _d(-9), "GIROCONTO DA CONTO PRINCIPALE", 500_000),
    ])
    # Fattura tra aziende del gruppo: Gamma fattura un servizio di logistica ad Alfa
    await invoice(gamma, "attiva", "44/2026", -14, 16, alfa["name"], alfa["vat_number"], 2_440)
    await invoice(alfa, "passiva", "44/2026", -14, 16, gamma["name"], gamma["vat_number"], 2_440)

    # Storico pagamenti di Delta: paga in ritardo (serve per il "ritardo medio")
    for number, issue, due, paid in (("110/2026", -150, -120, -92), ("115/2026", -110, -80, -55), ("119/2026", -80, -50, -24)):
        inv = await invoice(alfa, "attiva", number, issue, due, "Delta Spa", "44444444444", 6_100)
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"status": "pagata", "paid_cents": inv["total_cents"],
                                                                 "paid_at": _d(paid)}})
        await db.deadlines.update_many({"invoice_id": inv["id"]}, {"$set": {"status": "incassato"}})
    await db.invoices.update_one({"company_id": alfa["id"], "number": "125/2026"},
                                 {"$push": {"reminders": {"at": now_iso(), "level": 1, "to": "amministrazione@delta.example",
                                                          "by": None, "by_name": "Ufficio amministrazione (demo)",
                                                          "status": "demo"}}})
    await db.contacts.insert_many([
        {"id": new_id(), "company_id": alfa["id"], "vat_key": "44444444444", "name": "Delta Spa",
         "email": "amministrazione@delta.example", "phone": ""},
        {"id": new_id(), "company_id": beta["id"], "vat_key": "44444444444", "name": "Delta Spa",
         "email": "amministrazione@delta.example", "phone": ""},
    ])

    # Finanziamenti e fidi
    t = today()
    def months_ago(n, day):
        from .services.loans import add_months
        return add_months(t.replace(day=1), -n, day).isoformat()
    await db.loans.insert_many([
        {"id": new_id(), "company_id": alfa["id"], "kind": "mutuo", "lender": "Banca A", "description": "Mutuo capannone",
         "principal_cents": 150_000_00, "installment_cents": 0, "rate": 4.5, "months": 60,
         "start_date": months_ago(18, 10), "active": True, "created_at": now_iso()},
        {"id": new_id(), "company_id": beta["id"], "kind": "leasing", "lender": "Leasing Uno Spa", "description": "Furgone",
         "principal_cents": 0, "installment_cents": 690_00, "rate": 0, "months": 48,
         "start_date": months_ago(12, 20), "active": True, "created_at": now_iso()},
        {"id": new_id(), "company_id": alfa["id"], "kind": "fido", "lender": "Banca A", "description": "Fido di cassa",
         "limit_cents": 50_000_00, "used_cents": 0, "active": True, "created_at": now_iso()},
        {"id": new_id(), "company_id": beta["id"], "kind": "anticipo_fatture", "lender": "Banca A",
         "description": "Anticipo fatture", "limit_cents": 30_000_00, "used_cents": 8_000_00, "active": True,
         "created_at": now_iso()},
    ])

    # Budget mensile dell'anno per Alfa
    budget = {"Incassi clienti": 60_000, "Personale": 29_000, "Fornitori": 18_000, "Utenze": 1_800, "Affitti": 3_200,
              "Carburante e trasporti": 600, "Oneri bancari": 60, "Imposte e tasse": 7_000}
    await db.budgets.insert_many([{"id": new_id(), "company_id": alfa["id"], "year": t.year, "category": c,
                                   "months": [v * 100] * 12, "updated_at": now_iso()} for c, v in budget.items()])

    # Una regola di categoria valida per tutto il gruppo
    await db.category_rules.insert_one({"id": new_id(), "company_id": None, "pattern": "ferramenta", "direction": "out",
                                        "category": "Altre uscite", "created_by": None,
                                        "created_by_name": "Dati di esempio", "created_at": now_iso()})

    # Il titolare riceve anche il report mensile
    await db.users.update_one({"email": "titolare@demo.it"}, {"$set": {"notify": {
        "email_alerts": True, "whatsapp_alerts": False, "whatsapp_number": "", "weekly_digest": True, "monthly_report": True}}})

    await sync_all_vat(db)

    from .seed_accounting import seed_accounting, seed_control
    await seed_accounting(db, company_docs, accounts_by_company)
    await seed_control(db, company_docs, accounts_by_company)

    from .seed_commissions import seed_commissions
    await seed_commissions(db, company_docs["beta"], company_docs["gamma"])
