"""Dati di esempio per le provvigioni: Azienda Beta vende offerte Fastweb, Vodafone e SKY tramite due strutture
(una è Azienda Gamma, del gruppo) e tre dipendenti."""
import random
from datetime import date, timedelta

from .services import commissions as cm
from .utils import new_id, now_iso, today

LETTERS = "ABCDEFGHILMNPRSTUVZ"
NAMES = ["Rossi Mario", "Bianchi Anna", "Esposito Luca", "Romano Sara", "Colombo Paolo", "Ricci Elena", "Marino Davide",
         "Greco Chiara", "Bruno Andrea", "Gallo Marta", "Conti Fabio", "De Luca Giulia", "Mancini Simone", "Costa Laura",
         "Giordano Matteo", "Rizzo Silvia", "Lombardi Marco", "Moretti Alice", "Barbieri Pietro", "Fontana Irene"]

PARTNERS = [("Fastweb", 6), ("Vodafone", 6), ("SKY", 12)]
OFFERS = {
    "Fastweb": [("Fastweb Casa", "fastweb casa", 180, 90, 25), ("Fastweb Mobile", "fastweb mobile", 40, 20, 5)],
    "Vodafone": [("Vodafone Fibra", "fibra", 150, 75, 20), ("Vodafone Giga", "giga", 35, 15, 5)],
    "SKY": [("Sky TV", "sky tv", 120, 60, 15), ("Sky Wifi", "sky wifi", 100, 50, 15)],
}
OFFER_TEXT = {
    "Fastweb": ["FASTWEB CASA LIGHT", "FASTWEB CASA PLUS", "FASTWEB MOBILE 150GB"],
    "Vodafone": ["VODAFONE FIBRA 2.5 GIGA", "VODAFONE GIGA 200", "Vodafone Fibra Family"],
    "SKY": ["SKY TV + NETFLIX", "SKY WIFI 1 GIGA", "SKY TV CALCIO"],
}


def fake_cf(rng) -> str:
    return ("".join(rng.choice(LETTERS) for _ in range(6)) + f"{rng.randint(50, 99)}" + rng.choice("ABCDEHLMPRST")
            + f"{rng.randint(1, 28):02d}" + rng.choice("FGHL") + f"{rng.randint(100, 999)}" + rng.choice(LETTERS))


def month_shift(ref: date, n: int) -> date:
    y, m = ref.year, ref.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def seed_commissions(db, company: dict, group_company: dict) -> None:
    rng = random.Random(7)
    cid = company["id"]
    t = today()
    partners = {}
    for name, months in PARTNERS:
        p = {"id": new_id(), "company_id": cid, "name": name, "chargeback_months": months, "mapping": None, "status_map": {},
             "created_at": now_iso()}
        partners[name] = p
        await db.commission_partners.insert_one(dict(p))
        for oname, match, rev, s, d in OFFERS[name]:
            await db.commission_offers.insert_one({"id": new_id(), "company_id": cid, "partner_id": p["id"], "name": oname, "match": match,
                                                   "revenue_cents": rev * 100, "payout_struttura_cents": s * 100,
                                                   "payout_dipendente_cents": d * 100, "active": True, "created_at": now_iso()})
    bens = [
        {"kind": "struttura", "name": "Telco Point Srl", "codes": ["TP01", "TP02"], "tax_code": "09988776655", "iban": "IT22B0306909606100000012345"},
        {"kind": "struttura", "name": group_company["name"], "codes": ["GAM"], "tax_code": group_company.get("vat_number", ""),
         "iban": "IT81X8496965328710122691669", "group_company_id": group_company["id"]},
        {"kind": "dipendente", "name": "Marco Rossi", "codes": ["MR01"], "tax_code": "RSSMRC85M01F205X"},
        {"kind": "dipendente", "name": "Giulia Bianchi", "codes": ["GB01"], "tax_code": "BNCGLI90A41H501Y"},
        {"kind": "dipendente", "name": "Luca Verdi", "codes": ["LV01"], "tax_code": "VRDLCU88C10L219Z"},
    ]
    for b in bens:
        await db.commission_beneficiaries.insert_one({"id": new_id(), "company_id": cid, "email": "", "iban": "", "group_company_id": None,
                                                      "active": True, "created_at": now_iso(), **b})
    first = month_shift(t, 2)
    await db.commission_contests.insert_one({
        "id": new_id(), "company_id": cid, "name": "Gara attivazioni", "kind": "tutti", "partner_id": None,
        "valid_from": first.strftime("%Y-%m"), "valid_to": None, "active": True, "created_at": now_iso(),
        "tiers": [{"min": 5, "bonus_cents": 100_00, "per_activation_cents": 0}, {"min": 8, "bonus_cents": 250_00, "per_activation_cents": 5_00}]})

    codes = ["TP01", "TP02", "GAM", "MR01", "GB01", "LV01"]
    sales, acts = [], []
    n = 0
    for back in (2, 1, 0):
        mstart = month_shift(t, back)
        for _ in range(22 if back else 14):
            n += 1
            partner = rng.choice(list(partners))
            p = partners[partner]
            cf, account = fake_cf(rng), f"{rng.randint(1_000_000, 9_999_999)}"
            day = mstart + timedelta(days=rng.randint(0, 26))
            if day > t:
                day = t - timedelta(days=rng.randint(0, 3))
            code = rng.choice(codes) if n % 13 else "XX99"  # un venditore non ancora censito
            if n % 17:
                sales.append({"id": new_id(), "company_id": cid, "customer_cf": cf, "account": account, "seller_code": code,
                              "partner_name": partner, "offer": "", "sale_date": (day - timedelta(days=rng.randint(5, 15))).isoformat(),
                              "customer_name": rng.choice(NAMES), "created_at": now_iso(), "updated_at": now_iso()})
            r = rng.random()
            status = "attiva" if r < 0.68 else "in_lavorazione" if r < 0.85 else "ko"
            if back == 0 and status == "attiva" and rng.random() < 0.4:
                status = "in_lavorazione"
            offer = rng.choice(OFFER_TEXT[partner])
            hist = [{"status": "in_lavorazione", "raw": "In lavorazione", "date": (day - timedelta(days=7)).isoformat(), "at": now_iso()}]
            a = {"id": new_id(), "company_id": cid, "partner_id": p["id"], "partner_name": partner, "external_id": f"{partner[:2].upper()}{100000 + n}",
                 "customer_cf": cf, "customer_name": sales[-1]["customer_name"] if sales and sales[-1]["customer_cf"] == cf else rng.choice(NAMES),
                 "account": account, "offer": offer, "offer_id": None, "raw_status": {"attiva": "Attivata", "in_lavorazione": "In lavorazione",
                                                                                         "ko": "KO tecnico"}[status],
                 "status": status, "status_date": day.isoformat(), "activation_date": day.isoformat() if status == "attiva" else None,
                 "storno_date": None, "history": hist + ([{"status": status, "raw": status, "date": day.isoformat(), "at": now_iso()}]
                                                         if status != "in_lavorazione" else []),
                 "beneficiary_id": None, "sale_id": None, "assignment": None, "match_note": None, "paid_statement_id": None,
                 "paid_amount_cents": None, "storno_statement_id": None, "created_at": now_iso(), "updated_at": now_iso()}
            acts.append(a)
    await db.commission_sales.insert_many([dict(s) for s in sales])
    await db.commission_activations.insert_many([dict(a) for a in acts])
    for p in partners.values():
        await db.commission_partners.update_one({"id": p["id"]}, {"$set": {"status_map": {
            "attivata": "attiva", "in lavorazione": "in_lavorazione", "ko tecnico": "ko", "cessata": "cessata"}}})
    await cm.reprice(db, cid)
    await cm.rematch(db, cid)

    # rendiconti di due mesi fa già approvati e pagati
    owner = await db.users.find_one({"email": "titolare@demo.it"}, {"_id": 0})
    m2 = month_shift(t, 2).strftime("%Y-%m")
    done = await cm.approve(db, cid, m2, None, owner)
    for s in done:
        await db.commission_statements.update_one({"id": s["id"]}, {"$set": {"status": "pagato" if s["total_cents"] > 0 else s["status"],
                                                                            "paid_at": now_iso()}})
        if s.get("deadline_id"):
            await db.deadlines.update_one({"id": s["deadline_id"]}, {"$set": {"status": "pagato", "done_at": now_iso()}})
    # due clienti pagati due mesi fa recedono il mese scorso: lo storno si recupera nel rendiconto del mese scorso
    paid = await db.commission_activations.find({"company_id": cid, "paid_statement_id": {"$ne": None}}, {"_id": 0}).to_list(100)
    for a in paid[:2]:
        sd = (month_shift(t, 1) + timedelta(days=10)).isoformat()
        await db.commission_activations.update_one({"id": a["id"]}, {"$set": {
            "status": "cessata", "raw_status": "Cessata", "status_date": sd, "storno_date": sd,
            "history": a["history"] + [{"status": "cessata", "raw": "Cessata", "date": sd, "at": now_iso()}]}})
