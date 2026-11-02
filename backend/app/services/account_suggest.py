"""Conto suggerito per le fatture di acquisto ancora sul conto generico.

In ordine di affidabilità:
1. conto già scelto per lo stesso fornitore in un'altra azienda del gruppo;
2. conto usato più spesso per lo stesso fornitore (fatture già classificate);
3. parole chiave nella descrizione o nel nome del fornitore.
"""
from collections import Counter

from .accounting import party_of

KEYWORDS = [
    (("energia", "elettric", "gas ", "luce", "acqua", "telefon", "fibra", "mobile", "tim ", "vodafone", "fastweb", "wind"), "costi_utenze"),
    (("carburant", "gasolio", "benzin", "autostrad", "telepass", "trasport", "spedizion", "corriere", "logistic"), "costi_trasporti"),
    (("software", "cloud", "licenz", "abbonament", "hosting", "dominio", "saas", "microsoft", "google"), "costi_software"),
    (("consulenz", "avvocat", "notai", "notar", "commercialist", "studio ", "parcella", "prestazion", "onorari"), "costi_consulenze"),
    (("affitto", "locazion", "canone sede"), "costi_affitti"),
    (("noleggi",), "costi_noleggi"),
    (("leasing",), "costi_leasing"),
    (("assicuraz", "polizza", "premio"), "costi_assicurazioni"),
    (("manutenz", "riparaz", "assistenza tecnica"), "costi_manutenzioni"),
    (("cancelleria", "materiale di consumo", "consumabil", "toner", "pulizi"), "costi_consumo"),
    (("merce", "merci", "materie prime", "material", "fornitura", "componenti", "ricambi"), "acquisti_merci"),
    (("commission", "spese bancarie"), "costi_banca"),
]


def _keyword(inv: dict) -> tuple[str, str] | None:
    text = f" {inv.get('description') or ''} {inv.get('counterparty_name') or ''} ".lower()
    for words, key in KEYWORDS:
        for w in words:
            if w in text:
                return key, w.strip()
    return None


async def suggestions(db, company: dict, invoices: list[dict], chart) -> dict[str, dict]:
    """{invoice_id: {account_code, account_name, reason, confidence}} per le fatture passive indicate."""
    # storico del gruppo: conti memorizzati per fornitore (per partita IVA)
    group_ids = [c["id"] async for c in db.companies.find({}, {"id": 1})]
    remembered: dict[str, list[str]] = {}
    async for s in db.supplier_accounts.find({"company_id": {"$in": group_ids}}, {"_id": 0}):
        remembered.setdefault(s["party_key"], []).append(s["account_code"])
    # conti usati per fornitore nelle fatture già classificate di questa azienda
    used: dict[str, Counter] = {}
    async for i in db.invoices.find({"company_id": company["id"], "direction": "passiva", "account_code": {"$ne": None}},
                                    {"_id": 0, "counterparty_vat": 1, "counterparty_name": 1, "account_code": 1}):
        used.setdefault(party_of(i)[0], Counter())[i["account_code"]] += 1

    out = {}
    for inv in invoices:
        key = party_of(inv)[0]
        sug = None
        for code in remembered.get(key, []):
            if code in chart.by_code and chart.by_code[code].get("postable"):
                sug = (code, "Stesso fornitore già classificato in un'azienda del gruppo", "alta")
                break
        if not sug and key in used:
            code = used[key].most_common(1)[0][0]
            if code in chart.by_code:
                sug = (code, "Conto usato per le altre fatture di questo fornitore", "alta")
        if not sug:
            kw = _keyword(inv)
            if kw and kw[0] in chart.by_key:
                sug = (chart.by_key[kw[0]], f"Contiene \"{kw[1]}\"", "media")
        if sug:
            out[inv["id"]] = {"account_code": sug[0], "account_name": chart.name(sug[0]), "reason": sug[1], "confidence": sug[2]}
    return out


async def to_classify(db, company: dict, chart, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """Fatture di acquisto che finiscono sul conto generico (nessun conto scelto né memorizzato per il fornitore)."""
    mapped = {s["party_key"] async for s in db.supplier_accounts.find({"company_id": company["id"]}, {"party_key": 1})}
    q: dict = {"company_id": company["id"], "direction": "passiva", "account_code": None}
    if date_from or date_to:
        q["date"] = {**({"$gte": date_from} if date_from else {}), **({"$lte": date_to} if date_to else {})}
    items = []
    async for inv in db.invoices.find(q, {"_id": 0}).sort("date", -1):
        if party_of(inv)[0] in mapped:
            continue
        items.append(inv)
    return items


