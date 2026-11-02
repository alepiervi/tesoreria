"""Gruppo, salute dell'azienda, piano, Centrale Rischi, paghe, chiusura del mese, classificazione, commesse,
rimanenze, export per il gestionale, QR nei solleciti."""
from datetime import date, timedelta

from app import db as db_module
from app.utils import new_id, now_iso
from tests.conftest import login

YEAR = date.today().year


def companies(client, headers):
    return {c["name"]: c["id"] for c in client.get("/api/companies", headers=headers).json()}


def run(client, fn):
    return client.portal.call(fn)


def db_find(client, coll, q):
    async def go():
        return await db_module.get_db()[coll].find(q, {"_id": 0}).to_list(1000)
    return run(client, go)


def db_insert(client, coll, doc):
    async def go():
        await db_module.get_db()[coll].insert_one(dict(doc))
    run(client, go)


def balanced(e):
    return e and sum(l["dare"] for l in e["lines"]) == sum(l["avere"] for l in e["lines"]) > 0


# ---------- gruppo ----------

def test_consolidated_eliminates_intercompany(client, owner):
    data = client.get("/api/intercompany", headers=owner).json()
    pair = next(c for c in data["candidates"] if c["kind"] == "intercompany" and c["out"] and c["in"])
    client.post("/api/intercompany/confirm", headers=owner, json={"tx_ids": [pair["out"]["id"], pair["in"]["id"]]})
    cons = client.get(f"/api/group/consolidated?year={YEAR}", headers=owner).json()
    assert cons["quadra"]
    el = cons["eliminations"]
    assert el["crediti_gruppo_cents"] >= 1_000_000 and el["debiti_gruppo_cents"] >= 1_000_000
    assert el["ricavi_gruppo_cents"] == 200_000 and el["costi_gruppo_cents"] == 200_000  # fattura Gamma → Alfa 2.440 € (imponibile 2.000)
    assert el["differenza_cents"] == 0
    agg_revenue = sum(c["valore_produzione"] for c in cons["companies"])
    assert cons["sintesi"]["valore_produzione"] == agg_revenue - 200_000
    assert cons["sintesi"]["utile"] == cons["aggregated_result_cents"]  # costi e ricavi interni si annullano
    assert all(m["difference_cents"] == 0 for m in cons["mismatches"])


def test_group_liquidity_and_transfer(client, owner, accountant):
    liq = client.get("/api/group/liquidity", headers=owner).json()
    assert len(liq["companies"]) == 3 and liq["total_cents"] > 0
    assert liq["proposals"], liq
    p = liq["proposals"][0]
    body = {"from_company_id": p["from_id"], "to_company_id": p["to_id"], "amount": str(p["amount_cents"] / 100),
            "date": (date.today() + timedelta(days=7)).isoformat()}
    assert client.post("/api/group/transfers", headers=accountant, json=body).status_code in (403, 404)
    r = client.post("/api/group/transfers", headers=owner, json=body)
    assert r.status_code == 200, r.text
    ds = db_find(client, "deadlines", {"group_transfer_id": r.json()["group_transfer_id"]})
    assert {d["kind"] for d in ds} == {"pagamento", "incasso"} and all(d["amount_cents"] == p["amount_cents"] for d in ds)
    assert next(d for d in ds if d["kind"] == "pagamento")["iban"]


def test_compare_companies(client, owner):
    data = client.get(f"/api/group/compare?year={YEAR}", headers=owner).json()
    assert len(data["rows"]) == 3
    assert all("ebitda_margin" in r["indici"] for r in data["rows"]) and data["labels"]["dso"]


# ---------- salute e crisi ----------

def test_health_ratios_and_signals(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    h = client.get(f"/api/companies/{alfa}/health", headers=owner).json()
    ids = {s["id"] for s in h["alerts"]["signals"]}
    assert {"retribuzioni", "fornitori", "banche", "iva", "inps", "inail", "riscossione", "dscr", "cassa"} <= ids
    assert {i["id"] for i in h["ratios"]["items"]} >= {"liquidita_corrente", "autonomia", "dso", "ebitda_margin"}
    assert len(h["alerts"]["dscr"]["periods"]) == 2
    # IVA scaduta oltre 20.000 € → segnale rosso
    db_insert(client, "deadlines", {"id": new_id(), "company_id": alfa, "kind": "f24", "description": "IVA agosto",
                                    "due_date": (date.today() - timedelta(days=40)).isoformat(), "amount_cents": 2_500_000,
                                    "status": "da_pagare", "auto_vat_period": "x", "created_at": now_iso()})
    # fornitore scaduto da oltre 90 giorni più dei debiti non scaduti → rosso
    db_insert(client, "deadlines", {"id": new_id(), "company_id": alfa, "kind": "pagamento", "description": "Fattura vecchia",
                                    "due_date": (date.today() - timedelta(days=120)).isoformat(), "amount_cents": 9_000_000,
                                    "status": "da_pagare", "created_at": now_iso(), "creditor": "fornitori"})
    h = client.get(f"/api/companies/{alfa}/health", headers=owner).json()
    s = {x["id"]: x for x in h["alerts"]["signals"]}
    assert s["iva"]["status"] == "rosso" and s["fornitori"]["status"] == "rosso" and h["alerts"]["overall"] == "rosso"


def test_central_risk_and_bank_signal(client, owner, admin):
    beta = companies(client, owner)["Azienda Beta Srl"]
    cr = client.get(f"/api/companies/{beta}/central-risk", headers=owner).json()
    assert cr["latest_month"] and cr["banks"]
    # sconfinamento anche nel mese dopo → presente da almeno 60 giorni e oltre il 5% → rosso
    last = cr["latest_month"]
    y, m = int(last[:4]), int(last[5:]) + 1
    nxt = f"{y + (m > 12)}-{(m - 1) % 12 + 1:02d}"
    r = client.put(f"/api/companies/{beta}/central-risk", headers=admin, json={"month": nxt, "rows": [
        {"bank": "Banca A", "category": "revoca", "granted": "10.000", "used": "11.200", "overdraft": "1.200"},
        {"bank": "Banca A", "category": "autoliquidanti", "granted": "30000", "used": "8000"}]})
    assert r.status_code == 200, r.text
    h = client.get(f"/api/companies/{beta}/health", headers=owner).json()
    assert next(s for s in h["alerts"]["signals"] if s["id"] == "banche")["status"] == "rosso"
    assert client.get(f"/api/companies/{beta}/central-risk/{nxt}", headers=owner).json()[0]["granted_cents"] == 1_000_000


def test_business_plan(client, owner, accountant):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    base = client.get(f"/api/companies/{alfa}/plan", headers=owner).json()
    assert len(base["rows"]) == 3 and base["base"]["ricavi"] > 0
    years = [{"revenue_growth": 10, "capex": "50000", "new_loan": "40000", "new_loan_rate": 4, "new_loan_months": 48}, {}, {}]
    r = client.post(f"/api/companies/{alfa}/plan", headers=owner, json={"years": years, "save": True}).json()
    assert r["rows"][0]["ricavi"] > base["rows"][0]["ricavi"]
    assert r["rows"][0]["investimenti"] == 5_000_000 and r["rows"][0]["nuovi_finanziamenti"] == 4_000_000
    assert r["rows"][1]["ammortamenti"] > base["rows"][1]["ammortamenti"]
    assert client.get(f"/api/companies/{alfa}/plan", headers=owner).json()["saved_at"]
    assert client.post(f"/api/companies/{alfa}/plan", headers=accountant, json={"years": years, "save": True}).status_code == 403
    x = client.post(f"/api/companies/{alfa}/plan/export", headers=owner, json={"years": years})
    assert x.status_code == 200 and x.content[:2] == b"PK"


# ---------- paghe ----------

def test_payroll_entry_deadlines_and_f24(client, owner):
    beta = companies(client, owner)["Azienda Beta Srl"]
    month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    bad = {"month": month, "lordo": "14000", "contributi_ditta": "4200", "contributi_dipendente": "1300", "irpef": "2900", "netto": "9000"}
    assert client.post(f"/api/companies/{beta}/payrolls", headers=owner, json=bad).status_code == 400
    ok = {**bad, "netto": "9800", "tfr": "1000", "employees": 4, "pay_date": f"{month}-27"}
    r = client.post(f"/api/companies/{beta}/payrolls", headers=owner, json=ok)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    e = db_find(client, "entries", {"source_key": f"paghe:{pid}"})[0]
    assert balanced(e) and e["causale"] == "STIP"
    ds = {d["payroll_role"]: d for d in db_find(client, "deadlines", {"payroll_id": pid})}
    assert ds["netto"]["amount_cents"] == 980_000 and ds["f24"]["amount_cents"] == 290_000 + 420_000 + 130_000
    assert client.post(f"/api/companies/{beta}/payrolls", headers=owner, json=ok).status_code == 400  # stesso mese due volte
    # pagamento dell'F24: IRPEF e contributi chiudono i debiti verso Erario e INPS
    acc = db_find(client, "bank_accounts", {"company_id": beta})[0]
    tx = {"id": new_id(), "company_id": beta, "account_id": acc["id"], "external_id": new_id(), "date": date.today().isoformat(),
          "description": "F24 PAGHE", "counterparty": "", "amount_cents": -840_000, "category": "Imposte e tasse",
          "category_manual": False, "status": "da_riconciliare", "exclusion_reason": None, "allocations": [], "created_at": now_iso()}
    db_insert(client, "transactions", tx)
    r = client.post(f"/api/transactions/{tx['id']}/match", headers=owner, json={"targets": [{"type": "deadline", "id": ds["f24"]["id"]}]})
    assert r.status_code == 200, r.text
    pay = db_find(client, "entries", {"source_key": f"tx:{tx['id']}"})[0]
    assert balanced(pay)
    assert {l["account"] for l in pay["lines"]} >= {"40.04.02", "40.05.01"}
    assert sum(l["dare"] for l in pay["lines"] if l["account"] == "40.04.02") == 290_000
    lst = client.get(f"/api/companies/{beta}/payrolls", headers=owner).json()
    assert lst["items"][0]["month"] == month
    # con le paghe registrate il bonifico degli stipendi chiude il debito verso i dipendenti
    company = db_find(client, "companies", {"id": beta})[0]
    assert company["payroll_from"] == month


# ---------- chiusura del mese ----------

def test_month_close_flow(client, owner, accountant):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    st = client.get(f"/api/companies/{alfa}/month-close?month={month}", headers=accountant).json()
    ids = {i["id"] for i in st["items"]}
    assert {"banche", "riconciliazione", "fatture", "paghe", "f24", "transitorio", "chiarimenti", "documenti", "revisione"} <= ids
    assert not st["closed"]
    r = client.put(f"/api/companies/{alfa}/month-close/{month}/items/revisione", headers=accountant, json={"done": True, "note": "ok"})
    assert r.status_code == 200
    st = client.get(f"/api/companies/{alfa}/month-close?month={month}", headers=accountant).json()
    assert next(i for i in st["items"] if i["id"] == "revisione")["done"]
    assert client.put(f"/api/companies/{alfa}/month-close/{month}/items/banche", headers=accountant, json={"done": True}).status_code == 400
    if not st["ready"]:
        assert client.post(f"/api/companies/{alfa}/month-close/{month}/close", headers=accountant).status_code == 400
    r = client.post(f"/api/companies/{alfa}/month-close/{month}/close?force=true", headers=accountant)
    assert r.status_code == 200, r.text
    assert r.json()["lock_date"].startswith(month)
    # un movimento di quel mese non si può più riconciliare
    acc = db_find(client, "bank_accounts", {"company_id": alfa})[0]
    tx = {"id": new_id(), "company_id": alfa, "account_id": acc["id"], "external_id": new_id(), "date": f"{month}-15",
          "description": "PROVA", "counterparty": "", "amount_cents": -1000, "category": "Altre uscite", "category_manual": False,
          "status": "da_riconciliare", "exclusion_reason": None, "allocations": [], "created_at": now_iso()}
    db_insert(client, "transactions", tx)
    assert client.post(f"/api/transactions/{tx['id']}/exclude", headers=owner, json={"reason": "x"}).status_code == 400
    assert client.post(f"/api/companies/{alfa}/month-close/{month}/reopen", headers=accountant).status_code == 200
    assert not db_find(client, "companies", {"id": alfa})[0].get("accounting_lock_date")


# ---------- classificazione, commesse, rimanenze ----------

def test_classify_invoices_with_suggestions(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    data = client.get(f"/api/companies/{alfa}/invoices-to-classify", headers=owner).json()
    energia = next(i for i in data["items"] if i["counterparty_name"] == "Energia Italia Spa")
    assert energia["suggestion"]["account_code"] == "60.02.02"
    before = len(data["items"])
    r = client.post(f"/api/companies/{alfa}/invoices-to-classify", headers=owner,
                    json={"items": [{"invoice_id": energia["id"], "account_code": energia["suggestion"]["account_code"]}]})
    assert r.json()["classified"] == 1
    e = db_find(client, "entries", {"source_key": f"inv:{energia['id']}"})[0]
    assert any(l["account"] == "60.02.02" for l in e["lines"])
    assert len(client.get(f"/api/companies/{alfa}/invoices-to-classify", headers=owner).json()["items"]) < before


def test_projects(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    items = client.get(f"/api/companies/{alfa}/projects", headers=owner).json()["items"]
    p = next(i for i in items if i["name"] == "Impianto Delta Spa")
    assert p["ricavi_cents"] > 0 and p["costi_cents"] > 0 and p["margine_previsto_cents"] == 1_400_000
    r = client.post(f"/api/companies/{alfa}/projects", headers=owner, json={"name": "Cantiere Nord", "budget_revenue": "10.000",
                                                                           "budget_cost": "7.000"})
    assert r.status_code == 200 and r.json()["budget_revenue_cents"] == 1_000_000
    assert client.post(f"/api/companies/{alfa}/projects", headers=owner, json={"name": ""}).status_code == 400


def test_inventory_posts_variation(client, owner):
    gamma = companies(client, owner)["Azienda Gamma Srl"]
    r = client.put(f"/api/companies/{gamma}/inventories/{YEAR}", headers=owner, json={"year": YEAR, "items": [
        {"description": "Bancali", "qty": 100, "unit_cost": "12,50"}, {"description": "Film estensibile", "qty": 40, "unit_cost": "30"}]})
    assert r.status_code == 200, r.text
    assert r.json()["total_cents"] == 125_000 + 120_000
    final = db_find(client, "entries", {"source_key": f"rim:{YEAR}"})[0]
    storno = db_find(client, "entries", {"source_key": f"rim:{YEAR}:storno"})[0]
    assert balanced(final) and balanced(storno) and storno["date"] == f"{YEAR + 1}-01-01"
    st = client.get(f"/api/companies/{gamma}/statements?year={YEAR}", headers=owner).json()
    assert st["quadra"] and st["voci"]["ce"].get("CE.B.11") == -245_000 and st["voci"]["sp"].get("SP.A.C.I") == 245_000


# ---------- export e solleciti ----------

def test_journal_export_with_account_map(client, accountant):
    cid = next(iter(companies(client, accountant).values()))
    s = client.get(f"/api/companies/{cid}/export-settings", headers=accountant).json()
    assert "conto_esterno" in s["fields"]
    cfg = {**s["settings"], "account_map": {"20.05.01": "C001"}, "columns": ["data", "conto_esterno", "dare", "avere"]}
    assert client.put(f"/api/companies/{cid}/export-settings", headers=accountant, json=cfg).status_code == 200
    d = (date.today() - timedelta(days=1)).isoformat()
    client.post(f"/api/companies/{cid}/entries", headers=accountant, json={"date": d, "causale": "GEN", "lines": [
        {"account": "60.06.02", "dare": 1000}, {"account": "20.05.01", "avere": 1000}]})
    r = client.get(f"/api/companies/{cid}/journal-export?date_from={d}&date_to={d}", headers=accountant)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "Data registrazione;Conto nel gestionale;Dare;Avere"
    assert "C001" in text and "10,00" in text
    p = client.get(f"/api/companies/{cid}/parties-export", headers=accountant)
    assert p.status_code == 200 and "Partita IVA" in p.content.decode("utf-8-sig")


def test_reminder_has_payment_qr(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    inv = next(i for i in client.get(f"/api/companies/{alfa}/invoices", headers=owner).json() if i["number"] == "128/2026")
    d = client.get(f"/api/invoices/{inv['id']}/reminder-draft", headers=owner).json()
    assert d["qr_payload"].startswith("BCD\n002\n1\nSCT") and "EUR15800.00" in d["qr_payload"]
    r = client.post(f"/api/invoices/{inv['id']}/reminder", headers=owner,
                    json={"to": "amministrazione@delta.example", "subject": d["subject"], "body": d["body"], "level": 1})
    assert r.status_code == 200, r.text
    sent = db_find(client, "outbox", {"meta.invoice_id": inv["id"]})[-1]
    assert any(a.startswith("avviso_pagamento") for a in sent["attachments"])
