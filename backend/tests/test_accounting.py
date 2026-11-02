"""Contabilità generale: partita doppia, registrazioni automatiche, bilancio, chiusure."""
from datetime import date, timedelta

from app import db as db_module
from app.integrations.sdi import build_fatturapa_xml
from app.utils import new_id, now_iso
from tests.conftest import login

YEAR = date.today().year


def companies(client, headers):
    return {c["name"]: c["id"] for c in client.get("/api/companies", headers=headers).json()}


def run(client, coro_fn):
    return client.portal.call(coro_fn)


def entry_for(client, key):
    async def go():
        return await db_module.get_db().entries.find_one({"source_key": key}, {"_id": 0})
    return run(client, go)


def account_by_key(client, cid, key):
    async def go():
        return (await db_module.get_db().accounts.find_one({"company_id": cid, "key": key}))["code"]
    return run(client, go)


def assert_balanced(entry):
    assert entry, "registrazione mancante"
    assert sum(l["dare"] for l in entry["lines"]) == sum(l["avere"] for l in entry["lines"]) > 0


def insert_tx(client, cid, desc, cents, d=None):
    async def go():
        db = db_module.get_db()
        acc = await db.bank_accounts.find_one({"company_id": cid})
        tx = {"id": new_id(), "company_id": cid, "account_id": acc["id"], "external_id": new_id(),
              "date": d or (date.today() - timedelta(days=1)).isoformat(), "description": desc, "counterparty": "",
              "amount_cents": cents, "category": "Fornitori" if cents < 0 else "Incassi clienti", "category_manual": False,
              "status": "da_riconciliare", "exclusion_reason": None, "allocations": [], "created_at": now_iso()}
        await db.transactions.insert_one(dict(tx))
        return tx["id"]
    return run(client, go)


def import_xml(client, headers, cid, xml):
    r = client.post(f"/api/companies/{cid}/invoices/import", headers=headers,
                    files=[("files", ("f.xml", xml.encode(), "application/xml"))])
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["ok"], res
    return res["invoice_id"]


# ---------- dati di esempio ----------

def test_seed_books_are_balanced(client, owner):
    for name, cid in companies(client, owner).items():
        checks = {c["id"]: c for c in client.get(f"/api/companies/{cid}/accounting-checks", headers=owner).json()}
        assert checks["quadratura"]["ok"], name
        assert all(c["ok"] for k, c in checks.items() if k.startswith("banca:")), (name, checks)
        assert checks["transitorio"]["ok"], (name, checks["transitorio"])
        tb = client.get(f"/api/companies/{cid}/trial-balance?year={YEAR}", headers=owner).json()
        assert tb["totals"]["balanced"]
        st = client.get(f"/api/companies/{cid}/statements?year={YEAR}", headers=owner).json()
        assert st["quadra"] and st["totale_attivo"] == st["totale_passivo"] > 0


def test_sales_invoice_entry(client, owner):
    ids = companies(client, owner)
    alfa = ids["Azienda Alfa Srl"]
    inv = next(i for i in client.get(f"/api/companies/{alfa}/invoices", headers=owner).json() if i["number"] == "131/2026")
    e = entry_for(client, f"inv:{inv['id']}")
    assert_balanced(e)
    assert e["causale"] == "FV"
    clienti = account_by_key(client, alfa, "clienti")
    line = next(l for l in e["lines"] if l["account"] == clienti)
    assert line["dare"] == 488_000 and line["party_name"] == "Kappa Srl"
    assert sum(l["avere"] for l in e["lines"] if l["account"] == account_by_key(client, alfa, "iva_debito")) == 88_000


def test_reconcile_creates_and_undo_removes_entry(client, owner):
    ids = companies(client, owner)
    alfa = ids["Azienda Alfa Srl"]
    queue = client.get("/api/reconciliation", headers=owner).json()
    tx = next(t for t in queue if "DELTA SPA SALDO FT 125" in t["description"])
    inv = next(i for i in client.get(f"/api/companies/{alfa}/invoices", headers=owner).json() if i["number"] == "125/2026")
    r = client.post(f"/api/transactions/{tx['id']}/match", headers=owner, json={"targets": [{"type": "invoice", "id": inv["id"]}]})
    assert r.status_code == 200, r.text
    e = entry_for(client, f"tx:{tx['id']}")
    assert_balanced(e)
    clienti = account_by_key(client, alfa, "clienti")
    assert any(l["account"] == clienti and l["avere"] == 732_000 for l in e["lines"])
    # il partitario del cliente Delta scende
    parties = client.get(f"/api/companies/{alfa}/parties?account={clienti}", headers=owner).json()
    assert parties
    client.post(f"/api/transactions/{tx['id']}/unmatch", headers=owner)
    assert entry_for(client, f"tx:{tx['id']}") is None


def test_withholding_invoice_and_payment(client, owner):
    ids = companies(client, owner)
    beta = ids["Azienda Beta Srl"]
    d = (date.today() - timedelta(days=3)).isoformat()
    xml = build_fatturapa_xml(number="P-12", issue_date=d, total_cents=122_000, due_date=d,
                              seller_name="Studio Rossi", seller_vat="12312312312", buyer_name="Azienda Beta Srl",
                              buyer_vat="22222222222", description="Consulenza", withholding_cents=20_000)
    inv_id = import_xml(client, owner, beta, xml)
    e = entry_for(client, f"inv:{inv_id}")
    assert_balanced(e)
    fornitori = account_by_key(client, beta, "fornitori")
    assert sum(l["avere"] for l in e["lines"] if l["account"] == fornitori) == 122_000
    # pagamento del netto (1.020 €): la ritenuta va tra i debiti verso l'Erario
    tx_id = insert_tx(client, beta, "BONIFICO A STUDIO ROSSI", -102_000, d)
    r = client.post(f"/api/transactions/{tx_id}/match", headers=owner, json={"targets": [{"type": "invoice", "id": inv_id}]})
    assert r.status_code == 200, r.text
    pay = entry_for(client, f"tx:{tx_id}")
    assert_balanced(pay)
    rit = account_by_key(client, beta, "ritenute_da_versare")
    assert sum(l["avere"] for l in pay["lines"] if l["account"] == rit) == 20_000
    assert sum(l["dare"] for l in pay["lines"] if l["account"] == fornitori) == 122_000

    async def deadlines():
        return await db_module.get_db().deadlines.find({"company_id": beta, "auto_withholding_period": {"$exists": True}},
                                                       {"_id": 0}).to_list(10)
    dl = run(client, deadlines)
    if date.fromisoformat(d).month == date.today().month or date.today().day <= 16:
        assert dl and dl[0]["amount_cents"] == 20_000 and "1040" in dl[0]["description"]


def test_split_payment_sales_invoice(client, owner):
    ids = companies(client, owner)
    gamma = ids["Azienda Gamma Srl"]
    d = (date.today() - timedelta(days=2)).isoformat()
    xml = build_fatturapa_xml(number="SP-1", issue_date=d, total_cents=122_000, due_date=d, seller_name="Azienda Gamma Srl",
                              seller_vat="33333333333", buyer_name="Comune di Esempio", buyer_vat="80000000000",
                              split_payment=True)
    inv_id = import_xml(client, owner, gamma, xml)
    inv = next(i for i in client.get(f"/api/companies/{gamma}/invoices", headers=owner).json() if i["id"] == inv_id)
    assert inv["payable_cents"] == 100_000
    e = entry_for(client, f"inv:{inv_id}")
    assert_balanced(e)
    clienti = account_by_key(client, gamma, "clienti")
    assert sum(l["dare"] - l["avere"] for l in e["lines"] if l["account"] == clienti) == 100_000
    reg = client.get(f"/api/companies/{gamma}/vat-registers?direction=attiva&year={YEAR}", headers=owner).json()
    assert any(r.get("split_payment") for r in reg["rows"])


# ---------- prima nota ----------

def test_manual_entry_validation(client, accountant):
    ids = companies(client, accountant)
    cid = next(iter(ids.values()))
    cassa = account_by_key(client, cid, "cassa")
    altri = account_by_key(client, cid, "costi_altri")
    d = (date.today() - timedelta(days=1)).isoformat()
    bad = {"date": d, "causale": "GEN", "description": "Prova", "lines": [
        {"account": altri, "dare": 1000}, {"account": cassa, "avere": 900}]}
    assert client.post(f"/api/companies/{cid}/entries", headers=accountant, json=bad).status_code == 400
    mastro = {"date": d, "causale": "GEN", "lines": [{"account": "60", "dare": 1000}, {"account": cassa, "avere": 1000}]}
    assert client.post(f"/api/companies/{cid}/entries", headers=accountant, json=mastro).status_code == 400
    ok = {"date": d, "causale": "GEN", "description": "Marche da bollo", "lines": [
        {"account": altri, "dare": 1600}, {"account": cassa, "avere": 1600}]}
    r = client.post(f"/api/companies/{cid}/entries", headers=accountant, json=ok)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    j = client.get(f"/api/companies/{cid}/entries?year={YEAR}&q=bollo", headers=accountant).json()
    assert j["total"] == 1 and j["items"][0]["id"] == eid
    led = client.get(f"/api/companies/{cid}/ledger?account={cassa}&year={YEAR}", headers=accountant).json()
    assert led["rows"][-1]["avere"] == 1600
    assert client.delete(f"/api/entries/{eid}", headers=accountant).status_code == 200
    # le registrazioni automatiche non si cancellano a mano
    auto = client.get(f"/api/companies/{cid}/entries?year={YEAR}&source=auto&limit=1", headers=accountant).json()["items"][0]
    assert client.delete(f"/api/entries/{auto['id']}", headers=accountant).status_code == 400


def test_read_only_cannot_post(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    inv = client.post("/api/invites", headers=owner, json={
        "email": "lettore@demo.it", "name": "Lettore", "role": "lettura", "company_ids": [alfa]}).json()
    token = inv["invite_url"].rsplit("/", 1)[-1]
    assert client.post(f"/api/invites/token/{token}/accept", json={"name": "Lettore", "password": "PasswordSicura1"}).status_code == 200
    h = login(client, "lettore@demo.it", "PasswordSicura1")
    assert client.get(f"/api/companies/{alfa}/trial-balance", headers=h).status_code == 200
    cassa = account_by_key(client, alfa, "cassa")
    r = client.post(f"/api/companies/{alfa}/entries", headers=h, json={"date": f"{YEAR}-01-10", "lines": [
        {"account": cassa, "dare": 1}, {"account": "60.06.02", "avere": 1}]})
    assert r.status_code == 403
    assert client.post(f"/api/companies/{alfa}/fiscal-years/{YEAR}/close", headers=h).status_code == 403


def test_chart_subaccount_and_templates(client, accountant):
    cid = next(iter(companies(client, accountant).values()))
    r = client.post(f"/api/companies/{cid}/accounts", headers=accountant, json={"parent_code": "60.02", "name": "Pubblicità"})
    assert r.status_code == 200, r.text
    assert r.json()["code"].startswith("60.02.5")
    accounts = client.get(f"/api/companies/{cid}/accounts", headers=accountant).json()
    assert any(a["name"] == "Pubblicità" for a in (accounts["items"] if isinstance(accounts, dict) else accounts))
    t = client.get(f"/api/companies/{cid}/entry-templates", headers=accountant).json()
    assert t["templates"] and "APE" in t["causali"]


# ---------- fine anno ----------

def test_assets_and_depreciation(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    data = client.get(f"/api/companies/{alfa}/assets?year={YEAR}", headers=owner).json()
    assert len(data["items"]) >= 3 and data["totals"]["quota"] > 0
    # capannone: 3% di 280.000 = 8.400 €
    cap = next(a for a in data["items"] if a["category"] == "fabbricati")
    assert cap["quota_cents"] == 840_000
    r = client.post(f"/api/companies/{alfa}/depreciation?year={YEAR}", headers=owner)
    assert r.status_code == 200, r.text
    e = entry_for(client, f"amm:{YEAR}")
    assert_balanced(e)
    assert sum(l["dare"] for l in e["lines"]) == data["totals"]["quota"]
    # ripetere non duplica
    client.post(f"/api/companies/{alfa}/depreciation?year={YEAR}", headers=owner)

    async def count():
        return await db_module.get_db().entries.count_documents({"source_key": f"amm:{YEAR}", "company_id": alfa})
    assert run(client, count) == 1


def test_prepaid_expense(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    ass = "60.02.07"  # Assicurazioni
    r = client.post(f"/api/companies/{alfa}/accruals", headers=owner, json={
        "kind": "risconto_attivo", "description": "Polizza annuale", "amount": "1200", "start": f"{YEAR}-10-01",
        "end": f"{YEAR + 1}-09-30", "account_code": ass, "year": YEAR})
    assert r.status_code == 200, r.text
    portion = r.json()["portion_cents"]
    assert 89_000 < portion < 91_000  # 9 mesi su 12 circa
    e = entry_for(client, f"rat:{r.json()['id']}")
    assert_balanced(e)
    storno = entry_for(client, f"rat:{r.json()['id']}:storno")
    assert storno and storno["date"] == f"{YEAR + 1}-01-01"
    # conto di tipo sbagliato
    r = client.post(f"/api/companies/{alfa}/accruals", headers=owner, json={
        "kind": "risconto_attivo", "description": "x", "amount": "100", "start": f"{YEAR}-10-01",
        "end": f"{YEAR + 1}-09-30", "account_code": "90.01.01", "year": YEAR})
    assert r.status_code == 400


def test_close_and_reopen_year(client, owner, admin):
    ids = companies(client, owner)
    beta = ids["Azienda Beta Srl"]
    assert client.post(f"/api/companies/{beta}/fiscal-years/{YEAR}/close", headers=admin).status_code == 403
    before = client.get(f"/api/companies/{beta}/statements?year={YEAR}", headers=owner).json()
    r = client.post(f"/api/companies/{beta}/fiscal-years/{YEAR}/close", headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["result_cents"] == before["sintesi"]["utile"]
    for key in (f"close:{YEAR}:ce", f"close:{YEAR}:sp", f"open:{YEAR + 1}"):
        assert_balanced(entry_for(client, key))
    # dopo la chiusura i conti economici sono a zero e lo stato patrimoniale quadra
    tb = client.get(f"/api/companies/{beta}/trial-balance?year={YEAR}", headers=owner).json()
    assert tb["totals"]["balanced"]
    after = client.get(f"/api/companies/{beta}/statements?year={YEAR}", headers=owner).json()
    assert after["quadra"] and after["sintesi"]["utile"] == before["sintesi"]["utile"]
    nxt = client.get(f"/api/companies/{beta}/statements?year={YEAR + 1}", headers=owner).json()
    assert nxt["quadra"] and nxt["totale_attivo"] == after["totale_attivo"]
    # periodo bloccato: niente registrazioni né riconciliazioni con data nell'anno chiuso
    cassa = account_by_key(client, beta, "cassa")
    r = client.post(f"/api/companies/{beta}/entries", headers=owner, json={"date": f"{YEAR}-06-01", "lines": [
        {"account": cassa, "dare": 100}, {"account": "60.06.02", "avere": 100}]})
    assert r.status_code == 400
    tx = next(t for t in client.get("/api/reconciliation", headers=owner).json() if t["company_id"] == beta)
    assert client.post(f"/api/transactions/{tx['id']}/exclude", headers=owner, json={"reason": "prova"}).status_code == 400
    years = client.get(f"/api/companies/{beta}/fiscal-years", headers=owner).json()
    assert years["lock_date"] == f"{YEAR}-12-31"
    # riapertura
    assert client.post(f"/api/companies/{beta}/fiscal-years/{YEAR}/reopen", headers=owner).status_code == 200
    assert entry_for(client, f"open:{YEAR + 1}") is None
    assert client.get(f"/api/companies/{beta}/fiscal-years", headers=owner).json()["lock_date"] in (None, f"{YEAR - 1}-12-31")


def test_vat_registers_and_settlements(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    sales = client.get(f"/api/companies/{alfa}/vat-registers?direction=attiva&year={YEAR}", headers=owner).json()
    purchases = client.get(f"/api/companies/{alfa}/vat-registers?direction=passiva&year={YEAR}", headers=owner).json()
    assert sales["rows"] and purchases["rows"]
    assert [r["protocol"] for r in sales["rows"]] == list(range(1, len(sales["rows"]) + 1))
    r = client.post(f"/api/companies/{alfa}/vat-settlements?year={YEAR}", headers=owner)
    assert r.status_code == 200, r.text


def test_cost_centers(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    ccs = client.get(f"/api/companies/{alfa}/cost-centers", headers=owner).json()
    assert {c["name"] for c in ccs} >= {"Produzione", "Amministrazione"}
    rep = client.get(f"/api/companies/{alfa}/cost-center-report?year={YEAR}", headers=owner).json()
    assert rep["rows"]
    # assegnare un conto e un centro di costo a una fattura di acquisto, ricordandolo per il fornitore
    inv = next(i for i in client.get(f"/api/companies/{alfa}/invoices", headers=owner).json() if i["number"] == "352")
    prod = next(c["id"] for c in ccs if c["name"] == "Produzione")
    r = client.put(f"/api/invoices/{inv['id']}/accounting", headers=owner,
                   json={"account_code": "60.01.01", "cost_center_id": prod, "remember_for_supplier": True})
    assert r.status_code == 200, r.text
    e = entry_for(client, f"inv:{inv['id']}")
    assert any(l["account"] == "60.01.01" and l["cost_center_id"] == prod for l in e["lines"])
    other = next(i for i in client.get(f"/api/companies/{alfa}/invoices", headers=owner).json() if i["number"] == "341")
    assert any(l["account"] == "60.01.01" for l in entry_for(client, f"inv:{other['id']}")["lines"])


def test_accounting_exports(client, accountant):
    cid = next(iter(companies(client, accountant).values()))
    for kind in ("journal", "trial", "statements", "vat_sales", "vat_purchases"):
        r = client.get(f"/api/companies/{cid}/accounting-export?kind={kind}&year={YEAR}", headers=accountant)
        assert r.status_code == 200, (kind, r.text)
        assert r.content[:2] == b"PK"
    r = client.get(f"/api/companies/{cid}/accounting-export?kind=statements&year={YEAR}&format=pdf", headers=accountant)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_intercompany_and_transfer_entries(client, owner):
    ids = companies(client, owner)
    alfa, beta = ids["Azienda Alfa Srl"], ids["Azienda Beta Srl"]
    data = client.get("/api/intercompany", headers=owner).json()
    pair = next(c for c in data["candidates"] if c["kind"] == "intercompany" and c["out"] and c["in"])
    giro = next(c for c in data["candidates"] if c["kind"] == "giroconto")
    for c in (pair, giro):
        r = client.post("/api/intercompany/confirm", headers=owner, json={"tx_ids": [c["out"]["id"], c["in"]["id"]]})
        assert r.status_code == 200, r.text
    out_e, in_e = entry_for(client, f"tx:{pair['out']['id']}"), entry_for(client, f"tx:{pair['in']['id']}")
    assert_balanced(out_e)
    assert_balanced(in_e)
    assert any(l["account"] == account_by_key(client, alfa, "gruppo_crediti") and l["dare"] == 1_000_000 for l in out_e["lines"])
    assert any(l["account"] == account_by_key(client, beta, "gruppo_debiti") and l["avere"] == 1_000_000 for l in in_e["lines"])
    # giroconto: una sola registrazione, banca contro banca
    g = entry_for(client, f"tx:{giro['out']['id']}")
    assert_balanced(g)
    assert g["causale"] == "GIRO" and all(l["account"].startswith("20.05.") for l in g["lines"])
    assert entry_for(client, f"tx:{giro['in']['id']}") is None
