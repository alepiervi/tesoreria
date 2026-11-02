"""Provvigioni sulle attivazioni vendute per conto dei partner (Fastweb, Vodafone, SKY…).

Flusso:
1. ogni giorno si importa il file di avanzamento di ogni partner (Excel/CSV, colonne diverse per partner: la mappatura
   si salva la prima volta). Le pratiche si aggiornano per codice pratica, così si vede la storia degli stati;
2. si importa il file del backoffice, che dice per ogni vendita (account + codice fiscale del cliente) quale codice
   venditore l'ha fatta;
3. il programma abbina ogni attivazione alla vendita del backoffice (codice fiscale + account) e dal codice venditore
   risale alla struttura (azienda collegata) o al dipendente;
4. a fine mese il rendiconto calcola per ognuno: compensi delle attivazioni (listino a importo fisso per offerta),
   premi delle gare a soglie, recupero degli storni (cliente cessato entro il periodo di storno del partner) e il
   riporto di eventuali saldi negativi. Approvato il rendiconto: alle strutture si crea il pagamento nello scadenzario,
   per i dipendenti si prepara l'elenco dei bonus per il consulente del lavoro.
"""
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from ..utils import new_id, now_iso, parse_date, today
from .statements import StatementError, _table_from_csv, _table_from_xlsx, parse_date_any

STATUSES = {"in_lavorazione": "In lavorazione", "attiva": "Attiva", "ko": "KO / annullata", "cessata": "Cessata / stornata"}

PARTNER_FIELDS = {
    "pratica": ("Codice pratica / contratto", True, ["codice pratica", "id pratica", "pratica", "codice contratto", "id contratto",
                                                      "contratto", "ordine", "id ordine", "order id", "codice ordine", "id"]),
    "codice_fiscale": ("Codice fiscale / P.IVA cliente", True, ["codice fiscale", "cod fiscale", "cf cliente", "cf", "partita iva",
                                                                  "p iva", "piva", "cf/piva", "cf piva", "fiscal code"]),
    "account": ("Account / codice cliente", False, ["account", "codice cliente", "cod cliente", "id cliente", "customer id",
                                                      "numero cliente", "codice account", "billing account"]),
    "offerta": ("Offerta", True, ["offerta", "prodotto", "offer", "pacchetto", "piano", "listino", "servizio"]),
    "stato": ("Stato", True, ["stato", "status", "esito", "stato pratica", "stato ordine", "fase"]),
    "data_stato": ("Data dello stato", False, ["data stato", "data esito", "data aggiornamento", "data ultimo stato", "data"]),
    "data_attivazione": ("Data di attivazione", False, ["data attivazione", "attivazione", "data attivo", "activation date"]),
    "cliente": ("Nome cliente", False, ["cliente", "ragione sociale", "nominativo", "nome cliente", "intestatario"]),
}
BACKOFFICE_FIELDS = {
    "account": ("Account / codice cliente", False, PARTNER_FIELDS["account"][2]),
    "codice_fiscale": ("Codice fiscale / P.IVA cliente", True, PARTNER_FIELDS["codice_fiscale"][2]),
    "codice_venditore": ("Codice venditore / struttura", True, ["codice venditore", "cod venditore", "venditore", "codice agente",
                                                                "agente", "codice dealer", "dealer", "codice struttura", "struttura",
                                                                "user", "operatore", "codice"]),
    "partner": ("Partner", False, ["partner", "gestore", "operatore telefonico", "brand", "fornitore"]),
    "offerta": ("Offerta", False, PARTNER_FIELDS["offerta"][2]),
    "data_vendita": ("Data vendita", False, ["data vendita", "data inserimento", "data contratto", "data firma", "data"]),
    "cliente": ("Nome cliente", False, PARTNER_FIELDS["cliente"][2]),
}

STATUS_WORDS = [
    ("cessata", ("cessat", "storn", "recess", "disattiv", "morosit", "chiusa per", "disdett", "churn")),
    ("ko", ("ko", "annull", "rifiut", "respint", "scartat", "negativ", "bocciat", "non attivabile")),
    ("attiva", ("attiv", "espletat", "completat", "positiv", "ok", "installat", "chiusa", "acquisit", "live")),
    ("in_lavorazione", ("lavoraz", "attesa", "inserit", "pending", "sospes", "in corso", "aperta", "nuova", "verifica")),
]


class CommissionError(ValueError):
    pass


# ------------------------------------------------------------------ utilità

def norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[_\-./]+", " ", text.strip().lower())).strip()


def norm_code(text) -> str:
    """Codici (CF, account, codice venditore): maiuscolo, solo lettere e cifre, senza zeri iniziali per i soli numeri."""
    if isinstance(text, float) and text.is_integer():
        text = int(text)
    s = re.sub(r"[^A-Z0-9]", "", str(text or "").upper())
    return s.lstrip("0") if s.isdigit() else s


def guess_status(raw: str) -> str | None:
    n = norm(raw)
    if not n:
        return None
    for status, words in STATUS_WORDS:
        for w in words:
            if (len(w) <= 2 and re.search(rf"\b{w}\b", n)) or (len(w) > 2 and w in n):
                # "non attiv" non è attiva
                if status == "attiva" and re.search(r"\bnon (attiv|ok)", n):
                    continue
                return status
    return None


def read_table(filename: str, data: bytes) -> list[list]:
    name = filename.lower()
    try:
        rows = _table_from_xlsx(data) if name.endswith((".xlsx", ".xlsm")) else _table_from_csv(data)
    except StatementError as e:
        raise CommissionError(str(e))
    rows = [[("" if c is None else c) for c in r] for r in rows if any(str(c or "").strip() for c in r)]
    if len(rows) < 2:
        raise CommissionError("Il file è vuoto o ha solo l'intestazione.")
    if len(rows) > 50_000:
        raise CommissionError("Il file ha troppe righe (massimo 50.000): dividilo.")
    return rows


def _header_score(row: list, fields: dict) -> int:
    cells = {norm(c) for c in row if str(c).strip()}
    return sum(1 for _, _, syn in fields.values() if any(s in cells for s in syn))


def detect(rows: list[list], fields: dict, saved: dict | None = None) -> tuple[int, list[str], dict]:
    """Trova la riga d'intestazione e propone la mappatura campo → colonna (quella salvata ha la precedenza)."""
    best, idx = -1, 0
    for i, r in enumerate(rows[:15]):
        s = _header_score(r, fields)
        if saved:
            s += sum(3 for h in saved.values() if h and h in [str(c).strip() for c in r])
        if s > best:
            best, idx = s, i
    headers = [str(c).strip() for c in rows[idx]]
    normalized = [norm(h) for h in headers]
    mapping: dict[str, str | None] = {}
    used = set()
    for key, (_, _, syn) in fields.items():
        if saved and saved.get(key) in headers:
            mapping[key] = saved[key]
            used.add(saved[key])
            continue
        hit = None
        for s in syn:  # prima la corrispondenza esatta, poi quella parziale
            for h, n in zip(headers, normalized):
                if h not in used and n == s:
                    hit = h
                    break
            if hit:
                break
        if not hit:
            for s in syn:
                if len(s) < 4:
                    continue
                for h, n in zip(headers, normalized):
                    if h not in used and s in n:
                        hit = h
                        break
                if hit:
                    break
        mapping[key] = hit
        if hit:
            used.add(hit)
    return idx, headers, mapping


def missing_required(mapping: dict, fields: dict) -> list[str]:
    return [label for key, (label, req, _) in fields.items() if req and not mapping.get(key)]


def records(rows: list[list], header_idx: int, headers: list[str], mapping: dict) -> list[dict]:
    pos = {h: i for i, h in enumerate(headers)}
    out = []
    for r in rows[header_idx + 1:]:
        rec = {}
        for key, h in mapping.items():
            if h and h in pos and pos[h] < len(r):
                v = r[pos[h]]
                rec[key] = v.strip() if isinstance(v, str) else v
            else:
                rec[key] = None
        if any(v not in (None, "") for v in rec.values()):
            out.append(rec)
    return out


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def month_end(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()


def add_months(d: str, n: int) -> str:
    x = parse_date(d)
    y, m = x.year, x.month + n
    while m > 12:
        m -= 12
        y += 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(x.day, last)).isoformat()


# ------------------------------------------------------------------ import avanzamenti del partner

async def import_partner_file(db, company_id: str, partner: dict, filename: str, data: bytes, mapping: dict | None = None,
                              user: dict | None = None) -> dict:
    rows = read_table(filename, data)
    idx, headers, proposed = detect(rows, PARTNER_FIELDS, mapping or partner.get("mapping"))
    if mapping:
        proposed = {k: (mapping.get(k) if mapping.get(k) in headers else None) for k in PARTNER_FIELDS}
    missing = missing_required(proposed, PARTNER_FIELDS)
    if missing:
        return {"needs_mapping": True, "headers": headers, "mapping": proposed, "missing": missing,
                "sample": [[_text(c) for c in r] for r in rows[idx + 1: idx + 6]], "fields": {k: v[0] for k, v in PARTNER_FIELDS.items()},
                "required": [k for k, v in PARTNER_FIELDS.items() if v[1]]}
    await db.commission_partners.update_one({"id": partner["id"]}, {"$set": {"mapping": proposed}})
    status_map = dict(partner.get("status_map") or {})
    recs = records(rows, idx, headers, proposed)
    stats = {"rows": len(recs), "new": 0, "updated": 0, "unchanged": 0, "skipped": 0, "unknown_statuses": []}
    unknown = set()
    offers = await db.commission_offers.find({"company_id": company_id, "partner_id": partner["id"]}, {"_id": 0}).to_list(2000)
    t = today().isoformat()
    for r in recs:
        ext = _text(r.get("pratica"))
        cf = norm_code(r.get("codice_fiscale"))
        if not ext or not cf:
            stats["skipped"] += 1
            continue
        raw = _text(r.get("stato"))
        key = norm(raw)
        status = status_map.get(key)
        if status is None:
            status = guess_status(raw)
            if status:
                status_map[key] = status
            elif key:
                unknown.add(raw)
        sdate = parse_date_any(r.get("data_stato")) or t
        adate = parse_date_any(r.get("data_attivazione"))
        offer_text = _text(r.get("offerta"))
        doc = {"customer_cf": cf, "customer_name": _text(r.get("cliente")), "account": norm_code(r.get("account")),
               "offer": offer_text, "offer_id": match_offer(offers, offer_text), "raw_status": raw}
        old = await db.commission_activations.find_one({"company_id": company_id, "partner_id": partner["id"], "external_id": ext}, {"_id": 0})
        if old:
            changes = {k: v for k, v in doc.items() if old.get(k) != v}
            new_status = status or old.get("status")
            if new_status != old.get("status") and status:
                changes["status"] = status
                changes["status_date"] = sdate
                changes["history"] = (old.get("history") or []) + [{"status": status, "raw": raw, "date": sdate, "at": now_iso()}]
                if status == "attiva" and not old.get("activation_date"):
                    changes["activation_date"] = adate or sdate
                if status == "cessata":
                    changes["storno_date"] = sdate
            if adate and old.get("activation_date") != adate and (status or old.get("status")) in {"attiva", "cessata"}:
                changes["activation_date"] = adate
            if changes:
                changes["updated_at"] = now_iso()
                await db.commission_activations.update_one({"id": old["id"]}, {"$set": changes})
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        else:
            act = {"id": new_id(), "company_id": company_id, "partner_id": partner["id"], "partner_name": partner["name"],
                   "external_id": ext, **doc, "status": status, "status_date": sdate,
                   "activation_date": (adate or sdate) if status in {"attiva", "cessata"} else None,
                   "storno_date": sdate if status == "cessata" else None,
                   "history": [{"status": status, "raw": raw, "date": sdate, "at": now_iso()}],
                   "beneficiary_id": None, "sale_id": None, "assignment": None, "match_note": None,
                   "paid_statement_id": None, "paid_amount_cents": None, "storno_statement_id": None,
                   "created_at": now_iso(), "updated_at": now_iso()}
            await db.commission_activations.insert_one(dict(act))
            stats["new"] += 1
    await db.commission_partners.update_one({"id": partner["id"]}, {"$set": {"status_map": status_map, "last_import_at": now_iso()}})
    stats["unknown_statuses"] = sorted(unknown)
    await db.commission_imports.insert_one({"id": new_id(), "company_id": company_id, "kind": "partner", "partner_id": partner["id"],
                                            "filename": filename, "stats": stats, "at": now_iso(),
                                            "by_name": (user or {}).get("name", "")})
    stats["matched"] = await rematch(db, company_id)
    return stats


def match_offer(offers: list[dict], text: str) -> str | None:
    n = norm(text)
    best, best_len = None, 0
    for o in offers:
        if not o.get("active", True):
            continue
        m = norm(o.get("match") or o["name"])
        if m and m in n and len(m) > best_len:
            best, best_len = o["id"], len(m)
    return best


async def reprice(db, company_id: str) -> None:
    """Riabbina le offerte del listino a tutte le attivazioni (dopo una modifica del listino)."""
    offers_by_partner = defaultdict(list)
    for o in await db.commission_offers.find({"company_id": company_id}, {"_id": 0}).to_list(5000):
        offers_by_partner[o["partner_id"]].append(o)
    async for a in db.commission_activations.find({"company_id": company_id}, {"id": 1, "partner_id": 1, "offer": 1, "offer_id": 1}):
        oid = match_offer(offers_by_partner[a["partner_id"]], a.get("offer", ""))
        if oid != a.get("offer_id"):
            await db.commission_activations.update_one({"id": a["id"]}, {"$set": {"offer_id": oid}})


async def apply_status_map(db, company_id: str, partner: dict) -> int:
    """Dopo aver indicato come leggere uno stato, aggiorna le pratiche che lo avevano."""
    smap = partner.get("status_map") or {}
    changed = 0
    async for a in db.commission_activations.find({"company_id": company_id, "partner_id": partner["id"], "status": None}, {"_id": 0}):
        st = smap.get(norm(a.get("raw_status")))
        if not st:
            continue
        upd = {"status": st, "history": (a.get("history") or []) + [{"status": st, "raw": a.get("raw_status"), "date": a["status_date"], "at": now_iso()}]}
        if st in {"attiva", "cessata"}:
            upd["activation_date"] = a.get("activation_date") or a["status_date"]
        if st == "cessata":
            upd["storno_date"] = a["status_date"]
        await db.commission_activations.update_one({"id": a["id"]}, {"$set": upd})
        changed += 1
    return changed


# ------------------------------------------------------------------ backoffice e abbinamento

async def import_backoffice(db, company_id: str, filename: str, data: bytes, mapping: dict | None = None, user: dict | None = None) -> dict:
    settings = await db.commission_settings.find_one({"company_id": company_id}) or {}
    rows = read_table(filename, data)
    idx, headers, proposed = detect(rows, BACKOFFICE_FIELDS, mapping or settings.get("backoffice_mapping"))
    if mapping:
        proposed = {k: (mapping.get(k) if mapping.get(k) in headers else None) for k in BACKOFFICE_FIELDS}
    missing = missing_required(proposed, BACKOFFICE_FIELDS)
    if missing or (not proposed.get("account") and not proposed.get("codice_fiscale")):
        return {"needs_mapping": True, "headers": headers, "mapping": proposed, "missing": missing,
                "sample": [[_text(c) for c in r] for r in rows[idx + 1: idx + 6]], "fields": {k: v[0] for k, v in BACKOFFICE_FIELDS.items()},
                "required": [k for k, v in BACKOFFICE_FIELDS.items() if v[1]]}
    await db.commission_settings.update_one({"company_id": company_id}, {"$set": {"company_id": company_id, "backoffice_mapping": proposed}},
                                            upsert=True)
    stats = {"rows": 0, "new": 0, "updated": 0, "skipped": 0}
    for r in records(rows, idx, headers, proposed):
        cf, acc, code = norm_code(r.get("codice_fiscale")), norm_code(r.get("account")), norm_code(r.get("codice_venditore"))
        if not code or not (cf or acc):
            stats["skipped"] += 1
            continue
        stats["rows"] += 1
        doc = {"company_id": company_id, "customer_cf": cf, "account": acc, "seller_code": code, "partner_name": _text(r.get("partner")),
               "offer": _text(r.get("offerta")), "sale_date": parse_date_any(r.get("data_vendita")), "customer_name": _text(r.get("cliente")),
               "updated_at": now_iso()}
        res = await db.commission_sales.update_one({"company_id": company_id, "customer_cf": cf, "account": acc, "seller_code": code},
                                                   {"$set": doc, "$setOnInsert": {"id": new_id(), "created_at": now_iso()}}, upsert=True)
        stats["new" if res.upserted_id else "updated"] += 1
    await db.commission_imports.insert_one({"id": new_id(), "company_id": company_id, "kind": "backoffice", "filename": filename,
                                            "stats": stats, "at": now_iso(), "by_name": (user or {}).get("name", "")})
    stats["matched"] = await rematch(db, company_id)
    return stats


async def rematch(db, company_id: str) -> int:
    """Abbina le attivazioni non ancora pagate e non assegnate a mano: CF + account → vendita → codice → percettore."""
    sales = await db.commission_sales.find({"company_id": company_id}, {"_id": 0}).to_list(200_000)
    by_pair, by_account, by_cf = defaultdict(list), defaultdict(list), defaultdict(list)
    for s in sales:
        if s["customer_cf"] and s["account"]:
            by_pair[(s["customer_cf"], s["account"])].append(s)
        if s["account"]:
            by_account[s["account"]].append(s)
        if s["customer_cf"]:
            by_cf[s["customer_cf"]].append(s)
    codes = {}
    async for b in db.commission_beneficiaries.find({"company_id": company_id, "active": {"$ne": False}}, {"_id": 0}):
        for c in b.get("codes") or []:
            codes[norm_code(c)] = b
    partners = {p["id"]: norm(p["name"]) async for p in db.commission_partners.find({"company_id": company_id}, {"id": 1, "name": 1})}
    matched = 0
    async for a in db.commission_activations.find({"company_id": company_id, "paid_statement_id": None,
                                                    "assignment": {"$ne": "manuale"}}, {"_id": 0}):
        cands, how = [], ""
        if a.get("account") and (a["customer_cf"], a["account"]) in by_pair:
            cands, how = by_pair[(a["customer_cf"], a["account"])], "codice fiscale e account"
        elif a.get("account") and a["account"] in by_account:
            cands, how = by_account[a["account"]], "account"
        elif a["customer_cf"] in by_cf:
            cands, how = by_cf[a["customer_cf"]], "codice fiscale"
            pname = partners.get(a["partner_id"], "")
            same = [s for s in cands if not s.get("partner_name") or norm(s["partner_name"]) in pname or pname in norm(s["partner_name"])]
            cands = same or cands
            if len({s["seller_code"] for s in cands}) > 1:
                cands, how = [], "più vendite con lo stesso codice fiscale: scegli a mano"
        sale = max(cands, key=lambda s: s.get("sale_date") or "") if cands else None
        if not sale:
            upd = {"sale_id": None, "beneficiary_id": None, "assignment": None,
                   "match_note": how if how.startswith("più") else "Nessuna vendita del backoffice con questo codice fiscale o account"}
        elif sale["seller_code"] not in codes:
            upd = {"sale_id": sale["id"], "beneficiary_id": None, "assignment": None,
                   "match_note": f"Codice venditore {sale['seller_code']} non associato a nessuna struttura o dipendente"}
        else:
            upd = {"sale_id": sale["id"], "beneficiary_id": codes[sale["seller_code"]]["id"], "assignment": "auto",
                   "match_note": f"Abbinata per {how} (codice {sale['seller_code']})"}
            matched += 1
        if any(a.get(k) != v for k, v in upd.items()):
            await db.commission_activations.update_one({"id": a["id"]}, {"$set": upd})
    return matched


# ------------------------------------------------------------------ rendiconti

def _recoverable(a: dict, partner: dict) -> bool:
    if not a.get("storno_date") or not a.get("activation_date"):
        return False
    limit = add_months(a["activation_date"], int(partner.get("chargeback_months") or 6))
    return a["storno_date"] <= limit


def _payout(offer: dict | None, kind: str) -> int:
    if not offer:
        return 0
    return int(offer.get("payout_struttura_cents" if kind == "struttura" else "payout_dipendente_cents") or 0)


def _gara_active(g: dict, month: str) -> bool:
    return g.get("active", True) and (g.get("valid_from") or "0000-00") <= month <= (g.get("valid_to") or "9999-99")


async def compute_month(db, company_id: str, month: str) -> dict:
    """Rendiconto del mese per ogni percettore: righe già approvate (fisse) o bozza calcolata adesso."""
    cutoff = month_end(month)
    start = f"{month}-01"
    bens = {b["id"]: b for b in await db.commission_beneficiaries.find({"company_id": company_id}, {"_id": 0}).to_list(5000)}
    partners = {p["id"]: p for p in await db.commission_partners.find({"company_id": company_id}, {"_id": 0}).to_list(200)}
    offers = {o["id"]: o for o in await db.commission_offers.find({"company_id": company_id}, {"_id": 0}).to_list(5000)}
    gare = [g for g in await db.commission_contests.find({"company_id": company_id}, {"_id": 0}).to_list(500) if _gara_active(g, month)]
    approved = {s["beneficiary_id"]: s for s in await db.commission_statements.find({"company_id": company_id, "month": month}, {"_id": 0}).to_list(5000)}
    acts = await db.commission_activations.find({"company_id": company_id, "beneficiary_id": {"$ne": None}}, {"_id": 0}).to_list(200_000)

    lines: dict[str, list] = defaultdict(list)
    counts: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for a in acts:
        bid = a["beneficiary_id"]
        b = bens.get(bid)
        p = partners.get(a["partner_id"], {})
        if not b:
            continue
        if bid in approved:
            continue
        reached = a.get("status") in {"attiva", "cessata"} and a.get("activation_date")
        recov = _recoverable(a, p)
        label = f"{p.get('name', '')} · {a.get('offer') or 'offerta'} · {a.get('customer_name') or a['customer_cf']} (pratica {a['external_id']})"
        # compenso: attivata entro fine mese, non ancora pagata, non stornata in modo recuperabile prima del pagamento
        if reached and a["activation_date"] <= cutoff and not a.get("paid_statement_id") and not (recov and a["storno_date"] <= cutoff):
            amount = _payout(offers.get(a.get("offer_id")), b["kind"])
            lines[bid].append({"type": "attivazione", "activation_id": a["id"], "description": label, "amount_cents": amount,
                               "date": a["activation_date"], "partner_id": a["partner_id"],
                               "warning": None if amount else "Offerta senza compenso nel listino"})
        # storno: già pagata, cessata entro il periodo di storno del partner
        if a.get("paid_statement_id") and not a.get("storno_statement_id") and recov and a["storno_date"] <= cutoff:
            lines[bid].append({"type": "storno", "activation_id": a["id"], "description": f"Storno · {label}",
                               "amount_cents": -int(a.get("paid_amount_cents") or 0), "date": a["storno_date"], "partner_id": a["partner_id"]})
        # conteggio per le gare del mese
        if reached and start <= a["activation_date"] <= cutoff:
            counts[bid]["*"] += 1
            counts[bid][a["partner_id"]] += 1
        if recov and start <= (a.get("storno_date") or "") <= cutoff:
            counts[bid]["*"] -= 1
            counts[bid][a["partner_id"]] -= 1

    rows = []
    for bid, b in bens.items():
        if bid in approved:
            s = approved[bid]
            rows.append({"beneficiary": b, "status": s["status"], "statement_id": s["id"], "lines": s["lines"], "total_cents": s["total_cents"],
                         "approved_at": s.get("approved_at"), "approved_by": s.get("approved_by_name"), "deadline_id": s.get("deadline_id"),
                         "count": s.get("count", 0)})
            continue
        ls = list(lines.get(bid, []))
        for g in gare:
            if g.get("kind", "tutti") not in {"tutti", b["kind"]}:
                continue
            n = counts[bid][g["partner_id"]] if g.get("partner_id") else counts[bid]["*"]
            tier = None
            for t in sorted(g.get("tiers") or [], key=lambda t: t["min"]):
                if n >= t["min"]:
                    tier = t
            if tier:
                bonus = int(tier.get("bonus_cents") or 0) + int(tier.get("per_activation_cents") or 0) * n
                if bonus:
                    ls.append({"type": "gara", "description": f"Gara «{g['name']}»: {n} attivazioni nette, soglia da {tier['min']}",
                               "amount_cents": bonus, "contest_id": g["id"]})
        prev = await db.commission_statements.find_one({"company_id": company_id, "beneficiary_id": bid, "month": {"$lt": month},
                                                        "carry_cents": {"$lt": 0}, "carried_to": None}, {"_id": 0}, sort=[("month", -1)])
        if prev:
            ls.append({"type": "riporto", "description": f"Saldo negativo del rendiconto di {prev['month'][5:]}/{prev['month'][:4]} da recuperare",
                       "amount_cents": prev["carry_cents"], "from_statement_id": prev["id"]})
        if not ls:
            continue
        total = sum(line["amount_cents"] for line in ls)
        rows.append({"beneficiary": b, "status": "bozza", "statement_id": None, "lines": ls, "total_cents": total,
                     "count": counts[bid]["*"]})
    rows.sort(key=lambda r: (r["beneficiary"]["kind"], r["beneficiary"]["name"].lower()))
    summary = {"strutture_cents": sum(r["total_cents"] for r in rows if r["beneficiary"]["kind"] == "struttura" and r["total_cents"] > 0),
               "dipendenti_cents": sum(r["total_cents"] for r in rows if r["beneficiary"]["kind"] == "dipendente" and r["total_cents"] > 0),
               "storni_cents": sum(line["amount_cents"] for r in rows for line in r["lines"] if line["type"] == "storno"),
               "gare_cents": sum(line["amount_cents"] for r in rows for line in r["lines"] if line["type"] == "gara"),
               "da_approvare": sum(1 for r in rows if r["status"] == "bozza"),
               "senza_prezzo": sum(1 for r in rows for line in r["lines"] if line.get("warning"))}
    return {"month": month, "rows": rows, "summary": summary}


async def approve(db, company_id: str, month: str, beneficiary_ids: list[str] | None, user: dict, pay_day: int = 15) -> list[dict]:
    if month >= today().strftime("%Y-%m"):
        raise CommissionError("Si possono approvare solo i rendiconti dei mesi già finiti.")
    data = await compute_month(db, company_id, month)
    done = []
    y, m = int(month[:4]), int(month[5:7])
    due = date(y + (m == 12), m % 12 + 1, min(pay_day, 28)).isoformat()
    for r in data["rows"]:
        b = r["beneficiary"]
        if r["status"] != "bozza" or (beneficiary_ids and b["id"] not in beneficiary_ids):
            continue
        if any(line.get("warning") for line in r["lines"]):
            raise CommissionError(f"{b['name']}: ci sono attivazioni con offerte senza compenso nel listino.")
        sid = new_id()
        total = r["total_cents"]
        st = {"id": sid, "company_id": company_id, "beneficiary_id": b["id"], "beneficiary_name": b["name"], "kind": b["kind"],
              "month": month, "lines": r["lines"], "total_cents": total, "count": r.get("count", 0),
              "carry_cents": total if total < 0 else 0, "carried_to": None,
              "status": "approvato" if total > 0 else "chiuso", "deadline_id": None,
              "approved_by": user["id"], "approved_by_name": user.get("name") or user["email"], "approved_at": now_iso()}
        for line in r["lines"]:
            if line["type"] == "attivazione":
                await db.commission_activations.update_one({"id": line["activation_id"]}, {"$set": {
                    "paid_statement_id": sid, "paid_amount_cents": line["amount_cents"]}})
            elif line["type"] == "storno":
                await db.commission_activations.update_one({"id": line["activation_id"]}, {"$set": {"storno_statement_id": sid}})
            elif line["type"] == "riporto":
                await db.commission_statements.update_one({"id": line["from_statement_id"]}, {"$set": {"carried_to": sid}})
        if total > 0 and b["kind"] == "struttura":
            did = new_id()
            await db.deadlines.insert_one({
                "id": did, "company_id": company_id, "kind": "pagamento", "invoice_id": None,
                "description": f"Provvigioni {month[5:]}/{month[:4]} · {b['name']}", "due_date": due, "amount_cents": total,
                "beneficiary": b["name"], "iban": (b.get("iban") or "").replace(" ", "").upper(), "status": "da_pagare",
                "manual": False, "commission_statement_id": sid, "creditor": "gruppo" if b.get("group_company_id") else "fornitori",
                "created_at": now_iso()})
            st["deadline_id"] = did
        await db.commission_statements.insert_one(dict(st))
        st.pop("_id", None)
        done.append(st)
    return done


async def reopen(db, statement: dict) -> None:
    later = await db.commission_statements.find_one({"company_id": statement["company_id"], "beneficiary_id": statement["beneficiary_id"],
                                                     "month": {"$gt": statement["month"]}})
    if later:
        raise CommissionError("C'è già un rendiconto approvato di un mese successivo: riapri prima quello.")
    if statement["status"] == "pagato":
        raise CommissionError("Il rendiconto è già pagato.")
    if statement.get("deadline_id"):
        d = await db.deadlines.find_one({"id": statement["deadline_id"]})
        if d and d["status"] not in {"da_pagare"}:
            raise CommissionError("Il pagamento è già stato preparato o inviato: annullalo prima dallo scadenzario.")
        await db.deadlines.delete_one({"id": statement["deadline_id"]})
    await db.commission_activations.update_many({"paid_statement_id": statement["id"]}, {"$set": {"paid_statement_id": None, "paid_amount_cents": None}})
    await db.commission_activations.update_many({"storno_statement_id": statement["id"]}, {"$set": {"storno_statement_id": None}})
    await db.commission_statements.update_many({"carried_to": statement["id"]}, {"$set": {"carried_to": None}})
    await db.commission_statements.delete_one({"id": statement["id"]})


async def overview(db, company_id: str, month: str) -> dict:
    """Numeri del mese: attivazioni per partner e stato, abbinamenti, margine (compenso partner − provvigioni)."""
    start, end = f"{month}-01", month_end(month)
    partners = {p["id"]: p for p in await db.commission_partners.find({"company_id": company_id}, {"_id": 0}).to_list(200)}
    offers = {o["id"]: o for o in await db.commission_offers.find({"company_id": company_id}, {"_id": 0}).to_list(5000)}
    bens = {b["id"]: b for b in await db.commission_beneficiaries.find({"company_id": company_id}, {"_id": 0}).to_list(5000)}
    per_partner: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    unmatched = unpriced = unknown = 0
    revenue = payout = 0
    async for a in db.commission_activations.find({"company_id": company_id}, {"_id": 0}):
        pp = per_partner[a["partner_id"]]
        if a.get("status") is None:
            unknown += 1
        if not a.get("beneficiary_id") and a.get("status") in {"attiva", "in_lavorazione"}:
            unmatched += 1
        if a.get("status") in {"attiva", "in_lavorazione"} and not a.get("offer_id"):
            unpriced += 1
        if a.get("activation_date") and start <= a["activation_date"] <= end:
            pp["attivate"] += 1
            o = offers.get(a.get("offer_id"))
            revenue += int((o or {}).get("revenue_cents") or 0)
            b = bens.get(a.get("beneficiary_id"))
            if b:
                payout += _payout(o, b["kind"])
        if a.get("storno_date") and start <= a["storno_date"] <= end:
            pp["stornate"] += 1
            p = partners.get(a["partner_id"], {})
            if _recoverable(a, p):
                o = offers.get(a.get("offer_id"))
                revenue -= int((o or {}).get("revenue_cents") or 0)
        if a.get("status") == "ko" and start <= (a.get("status_date") or "") <= end:
            pp["ko"] += 1
        if a.get("status") == "in_lavorazione":
            pp["in_lavorazione"] += 1
    rows = [{"partner_id": pid, "partner": partners.get(pid, {}).get("name", "?"), **dict(v)} for pid, v in per_partner.items()]
    return {"month": month, "partners": sorted(rows, key=lambda r: r["partner"]), "unmatched": unmatched, "unpriced": unpriced,
            "unknown_status": unknown, "revenue_cents": revenue, "payout_cents": payout, "margin_cents": revenue - payout}
