"""Conti bancari: collegamento automatico (open banking), conti manuali e import degli estratti conto."""
import hashlib
import json
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..integrations.banking import CONSENT_DAYS, get_banking_provider
from ..services.categories import categorize, categorize_card, load_rules
from ..services.statements import StatementError, detect_format, finish, parse_statement
from ..utils import mask_iban, new_id, now_iso, parse_date, to_cents, today
from .common import load

router = APIRouter(tags=["banks"])
AUTO_OFF = "Il collegamento automatico con le banche non è attivo: importa l'estratto conto (CSV, Excel, XML o PDF) dal conto manuale."

INITIAL_HISTORY_DAYS = 90
MAX_STATEMENT_BYTES = 15 * 1024 * 1024
MANUAL = "manuale"


class ConnectIn(BaseModel):
    bank_name: str
    # Se indicato, il conto manuale diventa automatico: tiene i movimenti già importati
    manual_account_id: str | None = None


class ManualAccountIn(BaseModel):
    bank_name: str
    label: str = "Conto corrente"
    iban: str = ""
    balance: str = ""
    balance_date: str = ""
    account_type: str = "conto"  # conto | carta
    card_last4: str = ""
    linked_account_id: str | None = None  # conto su cui si addebita la carta
    card_debit_day: int | None = None


def public_account(a: dict) -> dict:
    a = {k: v for k, v in a.items() if k not in {"_id", "iban"}}
    a["is_manual"] = a.get("provider") == MANUAL
    expires = a.get("consent_expires_at")
    if expires and not a["is_manual"]:
        a["consent_days_left"] = (parse_date(expires) - today()).days
    return a


def _new_transaction(account: dict, external_id: str, d: str, description: str, amount_cents: int,
                     value_date: str | None = None, source: str = "banca", rules: list | None = None) -> dict:
    return {
        "id": new_id(), "company_id": account["company_id"], "account_id": account["id"],
        "external_id": external_id, "date": d, "value_date": value_date or d, "description": description,
        "counterparty": "", "amount_cents": amount_cents,
        "category": (categorize_card if account.get("account_type") == "carta" else categorize)(description, amount_cents, rules),
        "category_manual": False,
        "status": "da_riconciliare", "allocations": [], "source": source, "created_at": now_iso(),
    }


async def sync_account(db, account: dict) -> int:
    provider = get_banking_provider()
    if provider is None:
        raise HTTPException(400, AUTO_OFF)
    if account.get("last_sync_at"):
        since = parse_date(account["last_sync_at"]) - timedelta(days=3)
    else:
        since = today() - timedelta(days=INITIAL_HISTORY_DAYS)
    if account.get("sync_from"):
        # conto passato da manuale ad automatico: non riscaricare il periodo già importato
        since = max(since, parse_date(account["sync_from"]))
    incoming = await provider.fetch_transactions(account, since)
    known = {t["external_id"] for t in await db.transactions.find(
        {"account_id": account["id"], "external_id": {"$in": [t["external_id"] for t in incoming]}},
        {"external_id": 1}).to_list(10000)}
    rules = await load_rules(db, account["company_id"])
    new = [_new_transaction(account, t["external_id"], t["date"], t["description"], t["amount_cents"], rules=rules)
           for t in incoming if t["external_id"] not in known]
    if new:
        await db.transactions.insert_many([dict(n) for n in new])
    balance = await provider.fetch_balance(account)
    if provider.name == "demo" and account.get("last_sync_at"):
        # La banca simulata non tiene un saldo proprio: lo aggiorniamo con i nuovi movimenti
        balance += sum(n["amount_cents"] for n in new)
    await db.bank_accounts.update_one({"id": account["id"]}, {"$set": {
        "balance_cents": balance, "balance_date": today().isoformat(), "last_sync_at": today().isoformat()}})
    return len(new)


@router.get("/companies/{company_id}/bank-accounts")
async def list_accounts(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    accounts = await get_db().bank_accounts.find({"company_id": company_id}, {"_id": 0}).sort("bank_name", 1).to_list(100)
    return [public_account(a) for a in accounts]


# ---------- Collegamento automatico ----------

@router.post("/companies/{company_id}/bank-accounts/connect")
async def connect(company_id: str, body: ConnectIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_banks")
    db = get_db()
    company = await db.companies.find_one({"id": company_id})
    manual = None
    if body.manual_account_id:
        manual = await db.bank_accounts.find_one({"id": body.manual_account_id, "company_id": company_id})
        if not manual or manual.get("provider") != MANUAL:
            raise HTTPException(400, "Il conto da trasformare non è un conto manuale di questa azienda.")
    provider = get_banking_provider()
    if provider is None:
        raise HTTPException(400, AUTO_OFF)
    result = await provider.start_connection(company, body.bank_name.strip())
    if result.get("redirect_url"):
        # Provider reale: l'utente va mandato alla pagina di consenso della banca.
        # Al ritorno (callback) si completa il collegamento, eventualmente sul conto manuale indicato.
        return {"redirect_url": result["redirect_url"]}
    created = []
    for n, acc in enumerate(result.get("accounts", [])):
        fields = {
            "provider": provider.name, "external_id": acc["external_id"], "bank_name": acc["bank_name"],
            "label": acc.get("label", ""), "consent_expires_at": acc.get("consent_expires_at"),
            "status": "attivo", "last_sync_at": None,
        }
        if manual and n == 0:
            last = await db.transactions.find({"account_id": manual["id"]}, {"date": 1}).sort("date", -1).limit(1).to_list(1)
            sync_from = (parse_date(last[0]["date"]) + timedelta(days=1)).isoformat() if last else None
            fields.update(sync_from=sync_from, bank_name=manual["bank_name"], label=manual.get("label", ""),
                          converted_from_manual_at=now_iso())
            await db.bank_accounts.update_one({"id": manual["id"]}, {"$set": fields})
            account = await db.bank_accounts.find_one({"id": manual["id"]}, {"_id": 0})
            await audit.log(user, "conto_reso_automatico", company_id, account["iban_masked"])
        else:
            account = {"id": new_id(), "company_id": company_id, **fields, "iban": acc["iban"],
                       "iban_masked": mask_iban(acc["iban"]), "balance_cents": acc.get("balance_cents", 0),
                       "balance_date": today().isoformat(), "created_at": now_iso()}
            await db.bank_accounts.insert_one(dict(account))
            await audit.log(user, "conto_collegato", company_id, f"{account['bank_name']} {account['iban_masked']}")
        await sync_account(db, account)
        created.append(public_account(await db.bank_accounts.find_one({"id": account["id"]}, {"_id": 0})))
    return {"accounts": created}


@router.post("/bank-accounts/{account_id}/sync")
async def sync(account_id: str, user: dict = Depends(get_current_user)):
    account, _ = await load("bank_accounts", account_id, user, "manage_banks")
    if account.get("status") == "scollegato":
        raise HTTPException(400, "Il conto è scollegato.")
    if account.get("provider") == MANUAL:
        raise HTTPException(400, "È un conto manuale: aggiornalo importando l'estratto conto.")
    count = await sync_account(get_db(), account)
    await audit.log(user, "conto_sincronizzato", account["company_id"], account["iban_masked"], {"nuovi": count})
    return {"new_transactions": count,
            "account": public_account(await get_db().bank_accounts.find_one({"id": account_id}, {"_id": 0}))}


@router.post("/companies/{company_id}/bank-accounts/sync-all")
async def sync_all(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_banks")
    db = get_db()
    total = 0
    for acc in await db.bank_accounts.find({"company_id": company_id, "status": "attivo",
                                            "provider": {"$ne": MANUAL}}, {"_id": 0}).to_list(100):
        total += await sync_account(db, acc)
    return {"new_transactions": total}


@router.post("/bank-accounts/{account_id}/renew-consent")
async def renew_consent(account_id: str, user: dict = Depends(get_current_user)):
    account, _ = await load("bank_accounts", account_id, user, "manage_banks")
    if account.get("provider") == MANUAL:
        raise HTTPException(400, "I conti manuali non hanno un consenso bancario.")
    # Con un provider reale qui si riapre il flusso di consenso della banca
    expires = (today() + timedelta(days=CONSENT_DAYS)).isoformat()
    await get_db().bank_accounts.update_one({"id": account_id}, {"$set": {"consent_expires_at": expires, "status": "attivo"}})
    await audit.log(user, "consenso_rinnovato", account["company_id"], account["iban_masked"])
    return public_account(await get_db().bank_accounts.find_one({"id": account_id}, {"_id": 0}))


@router.delete("/bank-accounts/{account_id}")
async def disconnect(account_id: str, user: dict = Depends(get_current_user)):
    account, _ = await load("bank_accounts", account_id, user, "manage_banks")
    await get_db().bank_accounts.update_one({"id": account_id}, {"$set": {"status": "scollegato"}})
    await audit.log(user, "conto_scollegato", account["company_id"], account["iban_masked"])
    return {"ok": True}


# ---------- Conti manuali ed estratti conto ----------

@router.post("/companies/{company_id}/bank-accounts/manual")
async def create_manual(company_id: str, body: ManualAccountIn, user: dict = Depends(get_current_user)):
    """Conto senza collegamento automatico: i movimenti arrivano importando l'estratto conto."""
    await require(user, company_id, "manage_banks")
    if not body.bank_name.strip():
        raise HTTPException(400, "Indica la banca." if body.account_type != "carta" else "Indica chi emette la carta (banca o circuito).")
    if body.account_type not in {"conto", "carta"}:
        raise HTTPException(400, "Tipo di conto non valido.")
    is_card = body.account_type == "carta"
    last4 = re.sub(r"\D", "", body.card_last4)
    if is_card and last4 and len(last4) != 4:
        raise HTTPException(400, "Indica le ultime 4 cifre della carta.")
    if is_card and body.linked_account_id and not await get_db().bank_accounts.find_one(
            {"id": body.linked_account_id, "company_id": company_id, "account_type": {"$ne": "carta"}}):
        raise HTTPException(400, "Il conto di addebito non è valido.")
    if body.card_debit_day is not None and not 1 <= body.card_debit_day <= 31:
        raise HTTPException(400, "Giorno di addebito non valido.")
    iban = "" if is_card else re.sub(r"\s", "", body.iban).upper()
    if iban and not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        raise HTTPException(400, "IBAN non valido.")
    try:
        balance = to_cents(body.balance) if body.balance.strip() else 0
    except ValueError:
        raise HTTPException(400, "Saldo non valido.")
    if is_card:
        balance = -abs(balance)  # per la carta il saldo è il debito da addebitare
    account = {
        "id": new_id(), "company_id": company_id, "provider": MANUAL, "external_id": None,
        "account_type": body.account_type, "card_last4": last4 or None,
        "linked_account_id": body.linked_account_id if is_card else None,
        "card_debit_day": body.card_debit_day if is_card else None,
        "bank_name": body.bank_name.strip(),
        "label": body.label.strip() or ("Carta di credito" if is_card else "Conto corrente"),
        "iban": iban, "iban_masked": (f"•••• {last4}" if last4 else "Carta") if is_card else (mask_iban(iban) if iban else "IBAN non indicato"),
        "balance_cents": balance, "balance_date": body.balance_date or today().isoformat(),
        "consent_expires_at": None, "status": "attivo", "last_sync_at": None,
        "last_import_at": None, "last_import_to": None, "created_at": now_iso(),
    }
    await get_db().bank_accounts.insert_one(dict(account))
    await audit.log(user, "conto_manuale_creato", company_id, f"{account['bank_name']} {account['iban_masked']}")
    return public_account(account)


def _parse_mapping(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        mapping = {}
        for key in ("date", "value_date", "amount", "debit", "credit", "balance", "reference"):
            if data.get(key) is not None and data.get(key) != "":
                mapping[key] = int(data[key])
        mapping["description"] = [int(i) for i in data.get("description", [])]
        return mapping
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Scelta delle colonne non valida.")


def _external_ids(account_id: str, movements: list[dict]) -> list[str]:
    """Impronta stabile di ogni movimento: reimportare lo stesso periodo non crea doppioni."""
    seen: dict[str, int] = {}
    ids = []
    for m in movements:
        key = f"{account_id}|{m['date']}|{m['amount_cents']}|{re.sub(r'[^a-z0-9]', '', m['description'].lower())}"
        n = seen.get(key, 0)
        seen[key] = n + 1
        ids.append("imp-" + hashlib.sha256(f"{key}|{n}".encode()).hexdigest()[:32])
    return ids


async def _read_statement(account: dict, file: UploadFile, mapping_raw: str, invert: bool = False) -> tuple[dict, list[str], set[str]]:
    if account.get("provider") != MANUAL:
        raise HTTPException(400, "L'import è per i conti manuali: questo conto si aggiorna in automatico.")
    data = await file.read(MAX_STATEMENT_BYTES + 1)
    if len(data) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, "Il file è troppo grande (massimo 15 MB).")
    is_card = account.get("account_type") == "carta"
    try:
        parsed = parse_statement(file.filename or "", data, _parse_mapping(mapping_raw), card=is_card)
    except StatementError as e:
        parsed = None
        if detect_format(file.filename or "", data) != "pdf":
            raise HTTPException(400, str(e))
        # PDF scansionato o di formato insolito: si prova con l'assistente (se collegato a Claude)
        from ..services.statement_pdf import parse_pdf_with_ai
        ai_result = await parse_pdf_with_ai(data, is_card)
        if not ai_result:
            raise HTTPException(400, f"{e} Con l'assistente collegato a Claude il PDF si può leggere anche così; altrimenti "
                                     "scarica dall'home banking il file CSV o Excel.")
        try:
            parsed = finish(ai_result, "pdf")
        except StatementError as e2:
            raise HTTPException(400, str(e2))
    if invert:
        for m in parsed["movements"]:
            m["amount_cents"] = -m["amount_cents"]
    if is_card and parsed.get("closing_balance_cents"):
        parsed["closing_balance_cents"] = -abs(parsed["closing_balance_cents"])
    ids = _external_ids(account["id"], parsed["movements"])
    existing = {t["external_id"] for t in await get_db().transactions.find(
        {"account_id": account["id"], "external_id": {"$in": ids}}, {"external_id": 1}).to_list(len(ids) + 1)}
    if parsed.get("iban") and account.get("iban") and parsed["iban"].replace(" ", "") != account["iban"]:
        parsed["warnings"].append(f"Attenzione: il file è del conto {mask_iban(parsed['iban'])}, "
                                  f"diverso da quello scelto ({account['iban_masked']}).")
    return parsed, ids, existing


@router.post("/bank-accounts/{account_id}/statement/preview")
async def preview_statement(account_id: str, file: UploadFile = File(...), mapping: str = Form(""), invert: bool = Form(False),
                            user: dict = Depends(get_current_user)):
    account, _ = await load("bank_accounts", account_id, user, "manage_banks")
    parsed, ids, existing = await _read_statement(account, file, mapping, invert)
    rows = [{**m, "duplicate": eid in existing} for m, eid in zip(parsed["movements"], ids)]
    return {
        "needs_mapping": parsed.get("needs_mapping", False), "error": parsed.get("error"),
        "raw_rows": parsed.get("raw_rows"),
        "format": parsed["format"], "format_label": parsed["format_label"], "is_card": account.get("account_type") == "carta",
        "headers": parsed["headers"], "mapping": parsed["mapping"], "detected_mapping": parsed["detected_mapping"],
        "count": len(rows), "new_count": sum(1 for r in rows if not r["duplicate"]),
        "duplicate_count": sum(1 for r in rows if r["duplicate"]),
        "date_from": parsed["date_from"], "date_to": parsed["date_to"],
        "total_in_cents": sum(r["amount_cents"] for r in rows if r["amount_cents"] > 0),
        "total_out_cents": -sum(r["amount_cents"] for r in rows if r["amount_cents"] < 0),
        "closing_balance_cents": parsed["closing_balance_cents"], "closing_balance_date": parsed["closing_balance_date"],
        "warnings": parsed["warnings"], "sample": rows[:15],
    }


@router.post("/bank-accounts/{account_id}/statement/import")
async def import_statement(account_id: str, file: UploadFile = File(...), mapping: str = Form(""),
                           closing_balance: str = Form(""), closing_balance_date: str = Form(""), invert: bool = Form(False),
                           user: dict = Depends(get_current_user)):
    account, _ = await load("bank_accounts", account_id, user, "manage_banks")
    db = get_db()
    parsed, ids, existing = await _read_statement(account, file, mapping, invert)
    if parsed.get("needs_mapping"):
        raise HTTPException(400, parsed.get("error") or "Indica quali colonne contengono data e importo.")
    rules = await load_rules(db, account["company_id"])
    new = [_new_transaction(account, eid, m["date"], m["description"], m["amount_cents"], m.get("value_date"), "import",
                            rules) for m, eid in zip(parsed["movements"], ids) if eid not in existing]
    if new:
        await db.transactions.insert_many([dict(n) for n in new])

    # Saldo: dal file se c'è, altrimenti quello scritto dall'utente
    balance, balance_date = parsed["closing_balance_cents"], parsed["closing_balance_date"]
    if closing_balance.strip():
        try:
            balance = to_cents(closing_balance)
        except ValueError:
            raise HTTPException(400, "Saldo non valido.")
        if account.get("account_type") == "carta":
            balance = -abs(balance)
        balance_date = closing_balance_date or parsed["date_to"]
    update = {"last_import_at": now_iso(),
              "last_import_to": max(parsed["date_to"], account.get("last_import_to") or "")}
    balance_updated = False
    if balance is not None and (not account.get("balance_date") or balance_date >= account["balance_date"]
                                or not account.get("last_import_at")):
        update.update(balance_cents=balance, balance_date=balance_date)
        balance_updated = True
    await db.bank_accounts.update_one({"id": account_id}, {"$set": update})
    await db.statement_imports.insert_one({
        "id": new_id(), "account_id": account_id, "company_id": account["company_id"],
        "filename": file.filename, "format": parsed["format"], "imported": len(new),
        "duplicates": len(existing), "date_from": parsed["date_from"], "date_to": parsed["date_to"],
        "imported_by": user["id"], "imported_by_name": user.get("name", ""), "at": now_iso(),
    })
    await audit.log(user, "estratto_conto_importato", account["company_id"], file.filename,
                    {"nuovi": len(new), "doppioni": len(existing), "conto": account["iban_masked"]})
    return {"imported": len(new), "duplicates": len(existing), "balance_updated": balance_updated,
            "account": public_account(await db.bank_accounts.find_one({"id": account_id}, {"_id": 0}))}


@router.get("/bank-accounts/{account_id}/imports")
async def list_imports(account_id: str, user: dict = Depends(get_current_user)):
    await load("bank_accounts", account_id, user, "view")
    return await get_db().statement_imports.find({"account_id": account_id}, {"_id": 0}).sort("at", -1).to_list(100)
