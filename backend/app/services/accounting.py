"""Contabilità generale in partita doppia.

Ogni registrazione ha righe in DARE e in AVERE che devono pareggiare. Le registrazioni nascono:
- in automatico da fatture e movimenti bancari sistemati (source_key "inv:<id>" / "tx:<id>"):
  si rigenerano da sole quando cambia l'origine (es. si annulla una riconciliazione);
- a mano dalla prima nota (source "manuale");
- dalle procedure di fine anno: ammortamenti, ratei e risconti, chiusura e apertura dei conti.
Le date fino a `accounting_lock_date` dell'azienda sono chiuse: lì nulla si crea, modifica o cancella.
"""
import re

from ..utils import new_id, now_iso, parse_date
from .chart import BANK_PARENT, CATEGORY_ACCOUNT_KEYS, template_accounts
from .invoices import norm_vat, payable

CAUSALI = {
    "FV": "Fattura di vendita", "NCV": "Nota di credito emessa", "FA": "Fattura di acquisto",
    "NCA": "Nota di credito ricevuta", "INC": "Incasso", "PAG": "Pagamento", "GIRO": "Giroconto",
    "IC": "Movimento tra società del gruppo", "BAN": "Movimento bancario", "STIP": "Stipendi",
    "F24": "Versamento F24", "AMM": "Ammortamenti", "RAT": "Ratei e risconti", "STO": "Storno",
    "APE": "Apertura conti", "CHI": "Chiusura conti", "GEN": "Registrazione generica",
}


class AccountingError(ValueError):
    pass


# ------------------------------------------------------------------ piano dei conti

_UPGRADED: set = set()


async def ensure_chart(db, company_id: str) -> None:
    """Crea il piano dei conti dell'azienda (la prima volta) e i sottoconti delle banche.
    Se il programma aggiunge conti di base in una nuova versione, li inserisce nei piani già esistenti."""
    if not await db.accounts.find_one({"company_id": company_id}):
        docs = [{"id": new_id(), "company_id": company_id, **a, "active": True} for a in template_accounts()]
        await db.accounts.insert_many(docs)
        _UPGRADED.add((id(db), company_id))
    elif (id(db), company_id) not in _UPGRADED:
        existing = {a["code"]: a async for a in db.accounts.find({"company_id": company_id}, {"code": 1, "key": 1, "system": 1})}
        for a in template_accounts():
            cur = existing.get(a["code"])
            if cur is None:
                await db.accounts.insert_one({"id": new_id(), "company_id": company_id, **a, "active": True})
            elif cur.get("system") and a["key"] and not cur.get("key"):
                await db.accounts.update_one({"company_id": company_id, "code": a["code"]}, {"$set": {"key": a["key"]}})
        _UPGRADED.add((id(db), company_id))
    async for bank in db.bank_accounts.find({"company_id": company_id}):
        await ensure_bank_account(db, bank)


async def ensure_bank_account(db, bank: dict) -> str:
    key = f"banca:{bank['id']}"
    acc = await db.accounts.find_one({"company_id": bank["company_id"], "key": key})
    if acc:
        return acc["code"]
    used = [a["code"] async for a in db.accounts.find({"company_id": bank["company_id"],
                                                        "code": {"$regex": f"^{re.escape(BANK_PARENT)}\\.1"}})]
    n = 10 + len(used)
    code = f"{BANK_PARENT}.{n}"
    await db.accounts.insert_one({
        "id": new_id(), "company_id": bank["company_id"], "code": code,
        "name": f"{bank['bank_name']} {bank.get('label', '')} {bank.get('iban_masked', '')}".replace("  ", " ").strip(),
        "kind": "attivo", "level": 3, "postable": True, "cee": "SP.A.C.IV", "cee_neg": "SP.P.D.4", "key": key,
        "party": None, "system": True, "active": True})
    return code


class Chart:
    def __init__(self, accounts: list[dict], category_map: dict | None = None):
        self.by_code = {a["code"]: a for a in accounts}
        self.by_key = {a["key"]: a["code"] for a in accounts if a.get("key")}
        self.category_map = category_map or {}

    def k(self, key: str) -> str:
        if key not in self.by_key:
            raise AccountingError(f"Nel piano dei conti manca il conto '{key}'.")
        return self.by_key[key]

    def for_category(self, category: str) -> str:
        code = self.category_map.get(category)
        if code and code in self.by_code:
            return code
        return self.k(CATEGORY_ACCOUNT_KEYS.get(category, "transitorio"))

    def name(self, code: str) -> str:
        return self.by_code.get(code, {}).get("name", code)


async def load_chart(db, company: dict) -> Chart:
    await ensure_chart(db, company["id"])
    accounts = await db.accounts.find({"company_id": company["id"]}, {"_id": 0}).to_list(5000)
    return Chart(accounts, company.get("accounting_category_map") or {})


# ------------------------------------------------------------------ righe e controlli

class Lines:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, account: str, amount_cents: int, side: str, party: tuple | None = None,
            cost_center_id: str | None = None, description: str | None = None):
        """side 'D' o 'A'. Un importo negativo passa automaticamente dall'altra parte."""
        if not amount_cents:
            return
        if amount_cents < 0:
            amount_cents, side = -amount_cents, ("A" if side == "D" else "D")
        self.items.append({
            "account": account, "dare": amount_cents if side == "D" else 0, "avere": amount_cents if side == "A" else 0,
            "party_key": party[0] if party else None, "party_name": party[1] if party else None,
            "cost_center_id": cost_center_id, "description": description,
        })

    def totals(self) -> tuple[int, int]:
        return sum(l["dare"] for l in self.items), sum(l["avere"] for l in self.items)


def validate_lines(lines: list[dict], chart: Chart) -> None:
    if len(lines) < 2:
        raise AccountingError("Una registrazione deve avere almeno due righe.")
    dare = sum(int(l.get("dare") or 0) for l in lines)
    avere = sum(int(l.get("avere") or 0) for l in lines)
    if dare != avere:
        raise AccountingError(f"La registrazione non quadra: dare {dare / 100:.2f} € e avere {avere / 100:.2f} €.")
    if dare == 0:
        raise AccountingError("La registrazione è vuota.")
    for l in lines:
        acc = chart.by_code.get(l["account"])
        if not acc:
            raise AccountingError(f"Il conto {l['account']} non esiste.")
        if not acc.get("postable"):
            raise AccountingError(f"Il conto {l['account']} {acc['name']} è un mastro: scegli un sottoconto.")
        if (l.get("dare") or 0) < 0 or (l.get("avere") or 0) < 0:
            raise AccountingError("Gli importi non possono essere negativi.")
        if l.get("dare") and l.get("avere"):
            raise AccountingError("Una riga va solo in dare oppure solo in avere.")


def is_locked(company: dict, date: str) -> bool:
    lock = company.get("accounting_lock_date")
    return bool(lock) and date <= lock


def party_of(inv: dict) -> tuple:
    return (norm_vat(inv.get("counterparty_vat")) or inv.get("counterparty_name", "").lower(), inv.get("counterparty_name", ""))


# ------------------------------------------------------------------ registrazioni automatiche

async def _invoice_account(db, company: dict, inv: dict, chart: Chart) -> str:
    if inv.get("account_code") and inv["account_code"] in chart.by_code:
        return inv["account_code"]
    if inv["direction"] == "attiva":
        return chart.k("ricavi_gruppo" if inv.get("intercompany_company_id") else "ricavi")
    default = await db.supplier_accounts.find_one({"company_id": company["id"], "party_key": party_of(inv)[0]})
    if default and default["account_code"] in chart.by_code:
        return default["account_code"]
    return chart.k("costi_generici")


async def build_invoice_entry(db, company: dict, inv: dict, chart: Chart) -> dict | None:
    total = inv["total_cents"]
    if not total:
        return None
    vat = inv.get("vat_cents") or 0
    taxable = inv.get("taxable_cents") if inv.get("taxable_cents") is not None else total - vat
    withholding = inv.get("withholding_cents") or 0
    split = inv.get("split_payment") and inv["direction"] == "attiva"
    party = party_of(inv)
    group = bool(inv.get("intercompany_company_id"))
    cc = inv.get("cost_center_id")
    main = await _invoice_account(db, company, inv, chart)
    credit_note = total < 0 or inv.get("doc_type") == "TD04"
    L = Lines()
    if inv["direction"] == "attiva":
        causale = "NCV" if credit_note else "FV"
        L.add(chart.k("gruppo_crediti" if group else "clienti"), payable(inv), "D", party)
        if withholding:
            L.add(chart.k("ritenute_subite"), withholding, "D")
        L.add(main, taxable, "A", cost_center_id=cc)
        if vat and not split:
            L.add(chart.k("iva_debito"), vat, "A")
        rest = payable(inv) + withholding - taxable - (0 if split else vat)
        L.add(chart.k("altri_ricavi"), rest, "A", description="Bollo e altri importi")
    else:
        causale = "NCA" if credit_note else "FA"
        L.add(main, taxable, "D", cost_center_id=cc)
        if vat:
            L.add(chart.k("iva_credito"), vat, "D")
        rest = total - taxable - vat
        L.add(main, rest, "D", cost_center_id=cc, description="Bollo e altri importi")
        L.add(chart.k("gruppo_debiti" if group else "fornitori"), total, "A", party)
    return {
        "date": inv.get("registration_date") or inv["date"], "causale": causale,
        "description": f"{'Fattura' if not credit_note else 'Nota di credito'} {inv['number']} del "
                       f"{parse_date(inv['date']).strftime('%d/%m/%Y')} · {inv.get('counterparty_name', '')}",
        "doc_number": inv["number"], "doc_date": inv["date"], "lines": L.items,
    }


def _loan_split(tx: dict, loans: list[dict]) -> tuple | None:
    """Se il movimento corrisponde a una rata di un finanziamento, restituisce (prestito, riga del piano)."""
    from .loans import schedule
    amount = -tx["amount_cents"]
    if amount <= 0:
        return None
    d = parse_date(tx["date"])
    for loan in loans:
        if loan["kind"] in {"fido", "anticipo_fatture"}:
            continue
        for row in schedule(loan):
            if row["installment_cents"] == amount and abs((parse_date(row["date"]) - d).days) <= 10:
                return loan, row
    return None


async def build_transaction_entry(db, company: dict, tx: dict, chart: Chart) -> dict | None:
    if tx["status"] not in {"riconciliato", "escluso"}:
        return None
    bank = chart.by_key.get(f"banca:{tx['account_id']}")
    if not bank:
        b = await db.bank_accounts.find_one({"id": tx["account_id"]})
        if not b:
            return None
        bank = await ensure_bank_account(db, b)
        chart.by_key[f"banca:{tx['account_id']}"] = bank
        chart.by_code[bank] = await db.accounts.find_one({"company_id": company["id"], "code": bank}, {"_id": 0})
    amount = tx["amount_cents"]
    incoming = amount > 0
    cc = tx.get("cost_center_id")
    L = Lines()
    L.add(bank, amount, "D")  # entrata in dare, uscita (negativa) in avere
    causale = "INC" if incoming else "PAG"
    desc = tx["description"]

    ic = tx.get("intercompany")
    if ic:
        if ic["company_id"] == tx["company_id"]:
            # giroconto tra due conti della stessa azienda: si registra una sola volta, dal lato dell'uscita
            if ic.get("pair_tx_id"):
                if incoming:
                    return None
                pair = await db.transactions.find_one({"id": ic["pair_tx_id"]})
                other_bank = chart.by_key.get(f"banca:{pair['account_id']}") if pair else None
                if not other_bank and pair:
                    b = await db.bank_accounts.find_one({"id": pair["account_id"]})
                    other_bank = await ensure_bank_account(db, b) if b else None
                L.add(other_bank or chart.k("transitorio"), -amount, "D")
            else:
                L.add(chart.k("transitorio"), -amount, "D")
            causale = "GIRO"
        else:
            other = await db.companies.find_one({"id": ic["company_id"]}, {"name": 1, "vat_number": 1})
            party = (norm_vat(other.get("vat_number")) or other["name"].lower(), other["name"]) if other else None
            L.add(chart.k("gruppo_debiti" if incoming else "gruppo_crediti"), -amount, "D", party)
            causale = "IC"
    elif tx["status"] == "riconciliato":
        remaining = abs(amount)
        for a in tx.get("allocations") or []:
            alloc = a["amount_cents"]
            remaining -= alloc
            if a["type"] == "invoice":
                inv = await db.invoices.find_one({"id": a["id"]}, {"_id": 0})
                if not inv:
                    L.add(chart.k("transitorio"), -alloc if incoming else alloc, "D")
                    continue
                party = party_of(inv)
                group = bool(inv.get("intercompany_company_id"))
                w = inv.get("withholding_cents") or 0
                share = round(w * alloc / payable(inv)) if w and payable(inv) else 0
                if inv["direction"] == "attiva":
                    L.add(chart.k("gruppo_crediti" if group else "clienti"), alloc, "A", party)
                else:
                    L.add(chart.k("gruppo_debiti" if group else "fornitori"), alloc + share, "D", party)
                    if share:
                        L.add(chart.k("ritenute_da_versare"), share, "A", description="Ritenuta d'acconto")
            else:
                d = await db.deadlines.find_one({"id": a["id"]}, {"_id": 0})
                if d and d.get("payroll_role") == "f24" and d.get("payroll_split"):
                    split = d["payroll_split"]
                    tot = (split.get("irpef") or 0) + (split.get("inps") or 0)
                    irpef = round(alloc * (split.get("irpef") or 0) / tot) if tot else 0
                    sign = -1 if incoming else 1
                    L.add(chart.k("ritenute_da_versare"), sign * irpef, "D", description="Ritenute IRPEF dipendenti")
                    L.add(chart.k("debiti_inps"), sign * (alloc - irpef), "D", description="Contributi INPS")
                    causale = "F24"
                    continue
                if d and d.get("payroll_role") == "netto":
                    L.add(chart.k("debiti_dipendenti"), -alloc if incoming else alloc, "D")
                    causale = "STIP"
                    continue
                if d and d.get("auto_vat_period"):
                    code, causale = chart.k("erario_iva"), "F24"
                elif d and d.get("auto_withholding_period"):
                    code, causale = chart.k("ritenute_da_versare"), "F24"
                elif d and d["kind"] == "f24":
                    code, causale = chart.k("erario_tributi"), "F24"
                else:
                    code = chart.for_category(tx.get("category", ""))
                L.add(code, -alloc if incoming else alloc, "D", cost_center_id=cc)
        if remaining > 0:
            L.add(chart.k("transitorio"), -remaining if incoming else remaining, "D", description="Parte non abbinata")
    else:
        # movimento senza fattura: conto in base alla categoria (o rata di un finanziamento)
        loans = await db.loans.find({"company_id": tx["company_id"]}, {"_id": 0}).to_list(100)
        split = _loan_split(tx, loans) if tx.get("category") in {"Leasing e finanziamenti", "Da classificare", "Altre uscite"} else None
        if split:
            loan, row = split
            if loan["kind"] == "leasing":
                L.add(chart.k("costi_leasing"), row["installment_cents"], "D", cost_center_id=cc)
            else:
                L.add(chart.k("debiti_finanziamenti"), row["principal_cents"], "D", description=f"Quota capitale rata {row['n']}")
                L.add(chart.k("interessi_mutui"), row["interest_cents"], "D", description=f"Interessi rata {row['n']}")
            desc = f"Rata {row['n']} · {loan['lender']} {loan.get('description', '')}".strip()
        else:
            code = chart.for_category(tx.get("category", ""))
            if tx.get("category") == "Personale" and company.get("payroll_from") and tx["date"][:7] >= company["payroll_from"]:
                code = chart.k("debiti_dipendenti")  # con le paghe registrate il bonifico chiude il debito verso i dipendenti
            if code == chart.by_key.get("debiti_dipendenti") or tx.get("category") == "Personale":
                causale = "STIP"
            elif tx.get("category") == "Imposte e tasse":
                causale = "F24"
            elif causale in {"INC", "PAG"}:
                causale = "BAN"
            L.add(code, -amount, "D", cost_center_id=cc)
    dare, avere = L.totals()
    if dare != avere:  # sicurezza: non dovrebbe mai succedere
        L.add(chart.k("transitorio"), dare - avere, "A", description="Differenza da verificare")
    return {"date": tx["date"], "causale": causale, "description": desc, "doc_number": None, "doc_date": None,
            "lines": L.items}


# ------------------------------------------------------------------ salvataggio

async def upsert_auto_entry(db, company: dict, source_key: str, entry: dict | None, source: str = "auto") -> str:
    """Crea, aggiorna o elimina la registrazione automatica di una origine. Restituisce cosa è successo."""
    existing = await db.entries.find_one({"company_id": company["id"], "source_key": source_key})
    if existing and is_locked(company, existing["date"]):
        return "bloccata"
    if entry and is_locked(company, entry["date"]):
        return "bloccata"
    if not entry:
        if existing:
            await db.entries.delete_one({"id": existing["id"]})
            return "eliminata"
        return "nessuna"
    doc = {"company_id": company["id"], "year": int(entry["date"][:4]), "source": source, "source_key": source_key,
           **entry, "updated_at": now_iso()}
    if existing:
        same = all(existing.get(k) == doc.get(k) for k in ("date", "causale", "description", "lines"))
        if same:
            return "invariata"
        await db.entries.update_one({"id": existing["id"]}, {"$set": doc})
        return "aggiornata"
    await db.entries.insert_one({"id": new_id(), "created_at": now_iso(), "created_by": None, **doc})
    return "creata"


async def sync_source(db, kind: str, obj_id: str) -> str:
    """Rigenera la registrazione automatica di una fattura ('invoice') o di un movimento ('transaction')."""
    coll = "invoices" if kind == "invoice" else "transactions"
    obj = await db[coll].find_one({"id": obj_id}, {"_id": 0})
    key = f"{'inv' if kind == 'invoice' else 'tx'}:{obj_id}"
    if not obj:
        doc = await db.entries.find_one({"source_key": key})
        if doc:
            company = await db.companies.find_one({"id": doc["company_id"]}, {"_id": 0})
            return await upsert_auto_entry(db, company, key, None)
        return "nessuna"
    company = await db.companies.find_one({"id": obj["company_id"]}, {"_id": 0})
    if company.get("accounting_enabled") is False:
        return "disattivata"
    chart = await load_chart(db, company)
    entry = await (build_invoice_entry if kind == "invoice" else build_transaction_entry)(db, company, obj, chart)
    if entry:
        validate_lines(entry["lines"], chart)
    return await upsert_auto_entry(db, company, key, entry)


async def sync_transactions(db, tx_ids: list[str]) -> None:
    for i in tx_ids:
        await sync_source(db, "transaction", i)


async def sync_company(db, company_id: str) -> dict:
    """Ricostruisce tutte le registrazioni automatiche dell'azienda (quelle in periodi chiusi non si toccano)."""
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    await ensure_chart(db, company_id)
    stats: dict[str, int] = {}
    seen = set()
    async for inv in db.invoices.find({"company_id": company_id}, {"id": 1}):
        r = await sync_source(db, "invoice", inv["id"])
        stats[r] = stats.get(r, 0) + 1
        seen.add(f"inv:{inv['id']}")
    async for tx in db.transactions.find({"company_id": company_id, "status": {"$in": ["riconciliato", "escluso"]}}, {"id": 1}):
        r = await sync_source(db, "transaction", tx["id"])
        stats[r] = stats.get(r, 0) + 1
        seen.add(f"tx:{tx['id']}")
    async for e in db.entries.find({"company_id": company_id, "source": "auto"}, {"id": 1, "source_key": 1, "date": 1}):
        if e["source_key"] not in seen and not is_locked(company, e["date"]):
            await db.entries.delete_one({"id": e["id"]})
            stats["eliminata"] = stats.get("eliminata", 0) + 1
    from .withholding import sync_withholding_deadlines
    await sync_withholding_deadlines(db, company)
    return stats


async def save_manual_entry(db, company: dict, body: dict, user: dict, entry_id: str | None = None) -> dict:
    chart = await load_chart(db, company)
    lines = [{
        "account": l["account"], "dare": int(l.get("dare") or 0), "avere": int(l.get("avere") or 0),
        "party_key": (l.get("party_name") or "").strip().lower() or None, "party_name": (l.get("party_name") or "").strip() or None,
        "cost_center_id": l.get("cost_center_id") or None, "description": (l.get("description") or "").strip() or None,
    } for l in body["lines"] if (l.get("dare") or l.get("avere"))]
    validate_lines(lines, chart)
    parse_date(body["date"])
    if is_locked(company, body["date"]):
        raise AccountingError("La data è in un periodo contabile chiuso.")
    if body.get("causale") not in CAUSALI:
        raise AccountingError("Causale non valida.")
    doc = {"company_id": company["id"], "date": body["date"], "year": int(body["date"][:4]), "causale": body["causale"],
           "description": body.get("description", "").strip() or CAUSALI[body["causale"]],
           "doc_number": body.get("doc_number") or None, "doc_date": body.get("doc_date") or None,
           "lines": lines, "updated_at": now_iso()}
    if entry_id:
        old = await db.entries.find_one({"id": entry_id, "company_id": company["id"]})
        if not old:
            raise AccountingError("Registrazione non trovata.")
        if old["source"] != "manuale":
            raise AccountingError("Le registrazioni automatiche si modificano cambiando la fattura o il movimento d'origine.")
        if is_locked(company, old["date"]):
            raise AccountingError("La registrazione è in un periodo contabile chiuso.")
        await db.entries.update_one({"id": entry_id}, {"$set": doc})
        return {**old, **doc}
    full = {"id": new_id(), "source": "manuale", "source_key": None, "created_at": now_iso(),
            "created_by": user["id"], "created_by_name": user.get("name", ""), **doc}
    await db.entries.insert_one(dict(full))
    full.pop("_id", None)
    return full


# ------------------------------------------------------------------ saldi

async def balances(db, company_id: str, date_from: str | None = None, date_to: str | None = None,
                   exclude_sources: tuple = ()) -> dict[str, dict]:
    """Totali dare/avere per conto nel periodo. {codice: {'dare', 'avere', 'saldo'}} (saldo = dare - avere)."""
    q: dict = {"company_id": company_id}
    if date_from or date_to:
        q["date"] = {**({"$gte": date_from} if date_from else {}), **({"$lte": date_to} if date_to else {})}
    if exclude_sources:
        q["source"] = {"$nin": list(exclude_sources)}
    out: dict[str, dict] = {}
    async for e in db.entries.find(q, {"lines": 1}):
        for l in e["lines"]:
            b = out.setdefault(l["account"], {"dare": 0, "avere": 0})
            b["dare"] += l["dare"]
            b["avere"] += l["avere"]
    for b in out.values():
        b["saldo"] = b["dare"] - b["avere"]
    return out
