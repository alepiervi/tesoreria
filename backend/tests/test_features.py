from datetime import date

import pyotp
import pytest

from app import db as db_module
from app.config import settings
from app.integrations.sdi import build_fatturapa_xml
from app.services.fatturapa import parse_fatturapa
from app.services.loans import french_installment, schedule
from tests.conftest import login


def companies(client, headers):
    return {c["name"]: c["id"] for c in client.get("/api/companies", headers=headers).json()}


# ---------- Intercompany ----------

def test_intercompany_candidates_and_confirm(client, owner):
    data = client.get("/api/intercompany", headers=owner).json()
    pair = next(c for c in data["candidates"] if c["kind"] == "intercompany" and c["out"] and c["in"])
    assert pair["score"] >= 85 and pair["can_confirm"]
    giro = next(c for c in data["candidates"] if c["kind"] == "giroconto")
    assert giro["out"]["company_id"] == giro["in"]["company_id"]
    r = client.post("/api/intercompany/confirm", headers=owner, json={"tx_ids": [pair["out"]["id"], pair["in"]["id"]]})
    assert r.status_code == 200
    data = client.get("/api/intercompany", headers=owner).json()
    t = data["transfers"][0]
    assert t["from_company"] == "Azienda Alfa Srl" and t["to_company"] == "Azienda Beta Srl" and t["net_cents"] == 1_000_000
    assert any(i["creditor"] == "Azienda Gamma Srl" and i["debtor"] == "Azienda Alfa Srl" for i in data["open_invoices"])
    # annullando un lato si annulla anche l'altro
    r = client.post(f"/api/transactions/{pair['out']['id']}/unmatch", headers=owner)
    assert r.status_code == 200
    queue_ids = {t["id"] for t in client.get("/api/reconciliation", headers=owner).json()}
    assert {pair["out"]["id"], pair["in"]["id"]} <= queue_ids


def test_intercompany_suggestion_in_queue_and_excluded_from_totals(client, owner):
    queue = client.get("/api/reconciliation", headers=owner).json()
    tx = next(t for t in queue if "AZIENDA BETA" in t["description"])
    assert tx["intercompany_suggestion"]["other_company_name"] == "Azienda Beta Srl"
    client.post("/api/intercompany/auto", headers=owner)
    dash = client.get("/api/dashboard/group", headers=owner).json()
    assert dash["totals"]["internal_transfers_cents"] in (0, 1_000_000)  # 0 se il trasferimento è del mese prima


def test_intercompany_invoice_flagged(client, owner):
    ids = companies(client, owner)
    inv = next(i for i in client.get(f"/api/companies/{ids['Azienda Gamma Srl']}/invoices", headers=owner).json()
               if i["number"] == "44/2026")
    assert inv["intercompany_company_id"] == ids["Azienda Alfa Srl"]


# ---------- Regole di categoria ----------

def test_category_rule_from_correction(client, admin):
    ids = companies(client, admin)
    txs = client.get(f"/api/companies/{ids['Azienda Alfa Srl']}/transactions?q=SDD ENERGIA", headers=admin).json()["items"]
    r = client.patch(f"/api/transactions/{txs[0]['id']}", headers=admin, json={"category": "Utenze"}).json()
    assert r["suggested_pattern"] == "sdd energia italia"
    r = client.post("/api/category-rules", headers=admin, json={
        "company_id": ids["Azienda Alfa Srl"], "pattern": "commissioni bancarie", "direction": "out",
        "category": "Altre uscite", "apply_existing": True}).json()
    assert r["updated"] >= 1
    assert client.post("/api/category-rules", headers=admin, json={
        "company_id": None, "pattern": "xyz", "category": "Utenze"}).status_code == 403  # di gruppo: solo titolare
    rules = client.get("/api/category-rules", headers=admin).json()
    assert any(x["pattern"] == "ferramenta" and x["company_name"] == "Tutte le aziende" for x in rules)


def test_rules_applied_on_import(client, owner):
    ids = companies(client, owner)
    client.post("/api/category-rules", headers=owner, json={
        "company_id": None, "pattern": "distributore", "direction": "out", "category": "Carburante e trasporti",
        "apply_existing": False})
    accounts = client.get(f"/api/companies/{ids['Azienda Gamma Srl']}/bank-accounts", headers=owner).json()
    acc = next(a for a in accounts if a["is_manual"])
    data = "Data;Descrizione;Importo\n03/10/2026;DISTRIBUTORE ROSSI;-50,00\n".encode()
    client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files={"file": ("a.csv", data, "text/csv")})
    tx = client.get(f"/api/companies/{ids['Azienda Gamma Srl']}/transactions?q=DISTRIBUTORE ROSSI", headers=owner).json()["items"][0]
    assert tx["category"] == "Carburante e trasporti"


# ---------- Crediti e solleciti ----------

def test_receivables_aging_and_late_payer(client, owner):
    r = client.get("/api/receivables", headers=owner).json()
    assert r["overdue_cents"] > 0 and len(r["buckets"]) == 5
    delta = next(p for p in r["parties"] if p["name"] == "Delta Spa" and p["company_name"] == "Azienda Alfa Srl")
    assert delta["avg_delay_days"] >= 25 and delta["late_payer"] and delta["email"] == "amministrazione@delta.example"
    pay = client.get("/api/receivables?direction=passiva", headers=owner).json()
    assert pay["total_cents"] > 0
    # le fatture tra aziende del gruppo non sono crediti verso clienti
    assert not any(p["name"] == "Azienda Alfa Srl" for p in r["parties"])


def test_send_reminder(client, admin, accountant):
    r = client.get("/api/receivables", headers=admin).json()
    inv = next(i for p in r["parties"] if p["name"] == "Delta Spa" for i in p["invoices"] if i["days_overdue"] > 0)
    d = client.get(f"/api/invoices/{inv['id']}/reminder-draft", headers=admin).json()
    assert d["to"] and d["subject"] and "IBAN" in d["body"]
    assert client.get(f"/api/invoices/{inv['id']}/reminder-draft", headers=accountant).status_code == 403
    r = client.post(f"/api/invoices/{inv['id']}/reminder", headers=admin, json={
        "to": d["to"], "subject": d["subject"], "body": d["body"], "level": d["level"], "attach_xml": True})
    assert r.status_code == 200 and r.json()["status"] == "demo"
    owner = login(client, "titolare@demo.it")
    out = client.get("/api/outbox", headers=owner).json()["items"]
    assert out[0]["subject"] == d["subject"] and out[0]["attachments"]


# ---------- Notifiche ----------

def test_question_notifies_owner(client, owner, accountant):
    tx = client.get("/api/reconciliation", headers=accountant).json()[0]
    client.post("/api/notes", headers=accountant, json={"target_type": "transaction", "target_id": tx["id"],
                                                         "text": "Cos'è?", "is_question": True})
    n = client.get("/api/notifications", headers=owner).json()
    assert n["unread"] >= 1 and n["items"][0]["kind"] == "chiarimento"
    client.post("/api/notifications/read-all", headers=owner)
    assert client.get("/api/notifications/unread-count", headers=owner).json()["unread"] == 0


def test_daily_alerts_and_no_duplicates(client, owner):
    first = client.post("/api/notifications/run-now", headers=owner).json()["created"]
    assert first > 0
    assert client.post("/api/notifications/run-now", headers=owner).json()["created"] == 0
    kinds = {n["kind"] for n in client.get("/api/notifications?limit=200", headers=owner).json()["items"]}
    assert {"scadenza", "crediti", "consenso"} <= kinds
    assert any(m["channel"] == "email" for m in client.get("/api/outbox", headers=owner).json()["items"])


def test_preferences_and_digest(client, admin):
    assert client.put("/api/me/notification-settings", headers=admin,
                      json={"whatsapp_alerts": True, "whatsapp_number": ""}).status_code == 400
    r = client.put("/api/me/notification-settings", headers=admin, json={
        "email_alerts": True, "whatsapp_alerts": True, "whatsapp_number": "+39 333 1234567", "weekly_digest": True})
    assert r.status_code == 200
    assert client.get("/api/me/notification-settings", headers=admin).json()["whatsapp_number"] == "+393331234567"
    assert client.post("/api/me/notification-settings/test", headers=admin).json()["sent"] == 1


def test_payment_request_notifies_and_requires_2fa(client, owner, admin, monkeypatch):
    d = next(x for x in client.get("/api/deadlines", headers=admin).json() if "352" in x["description"])
    acc = client.get(f"/api/companies/{d['company_id']}/bank-accounts", headers=admin).json()[0]["id"]
    client.post(f"/api/deadlines/{d['id']}/request-payment", headers=admin, json={"account_id": acc})
    assert any(n["kind"] == "pagamento" for n in client.get("/api/notifications", headers=owner).json()["items"])
    monkeypatch.setattr(settings, "require_2fa_for_payments", True)
    r = client.post(f"/api/deadlines/{d['id']}/authorize", headers=owner, json={"account_id": acc})
    assert r.status_code == 403 and "verifica in due passaggi" in r.json()["detail"]
    setup = client.post("/api/auth/2fa/setup", headers=owner).json()
    client.post("/api/auth/2fa/enable", headers=owner, json={"code": pyotp.TOTP(setup["secret"]).now()})
    r = client.post(f"/api/deadlines/{d['id']}/authorize", headers=owner, json={"account_id": acc})
    assert r.status_code == 200
    assert any(n["title"] == "Pagamento autorizzato" for n in client.get("/api/notifications", headers=admin).json()["items"])


# ---------- IVA ----------

def test_fatturapa_vat_and_p7m():
    xml = build_fatturapa_xml(number="1", issue_date="2026-10-01", total_cents=12200, due_date="2026-10-31",
                              seller_name="A", seller_vat="12345678901", buyer_name="B", buyer_vat="10987654321")
    doc = parse_fatturapa(xml.encode())[0]
    assert doc["vat_cents"] == 2200 and doc["taxable_cents"] == 10000
    from asn1crypto import cms
    p7m = cms.ContentInfo({"content_type": "signed_data", "content": cms.SignedData({
        "version": "v1", "digest_algorithms": [], "encap_content_info": {"content_type": "data", "content": xml.encode()},
        "signer_infos": []})}).dump()
    assert parse_fatturapa(p7m)[0]["number"] == "1"
    import base64
    assert parse_fatturapa(base64.b64encode(p7m))[0]["number"] == "1"


def test_vat_estimate_and_deadlines(client, owner):
    ids = companies(client, owner)
    alfa = ids["Azienda Alfa Srl"]
    v = client.get(f"/api/companies/{alfa}/vat", headers=owner).json()
    assert v["mode"] == "mensile" and len(v["periods"]) == 12
    today = date.today()
    xml = build_fatturapa_xml(number="900/2026", issue_date=today.isoformat(), total_cents=1_220_000,
                              due_date=today.isoformat(), seller_name="Azienda Alfa Srl", seller_vat="11111111111",
                              buyer_name="Cliente Grande", buyer_vat="12121212121")
    client.post(f"/api/companies/{alfa}/invoices/import", headers=owner, files=[("files", ("f.xml", xml.encode(), "application/xml"))])
    v = client.get(f"/api/companies/{alfa}/vat", headers=owner).json()
    cur = next(p for p in v["periods"] if p["state"] == "in_corso")
    assert cur["sales_vat_cents"] >= 220_000 and cur["deadline_id"]
    deadlines = client.get(f"/api/deadlines?company_id={alfa}", headers=owner).json()
    vat_dl = next(d for d in deadlines if d["id"] == cur["deadline_id"])
    assert vat_dl["kind"] == "f24" and vat_dl["amount_cents"] == cur["to_pay_cents"]
    # trimestrale: scadenza 16 maggio (o primo giorno lavorativo dopo) per il primo trimestre
    client.put(f"/api/companies/{alfa}/vat-settings", headers=owner, json={"vat_period": "trimestrale"})
    v = client.get(f"/api/companies/{alfa}/vat", headers=owner).json()
    assert len(v["periods"]) == 4 and v["periods"][0]["due_date"][5:7] == "05"


# ---------- Budget ----------

def test_budget(client, owner, accountant):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    b = client.get(f"/api/companies/{alfa}/budget", headers=owner).json()
    assert b["has_budget"] and any(r["category"] == "Personale" and r["budget_cents"] == 2_900_000 for r in b["rows"])
    sug = client.get(f"/api/companies/{alfa}/budget/suggest", headers=owner).json()
    assert sug.get("Personale", 0) > 0
    body = {"year": date.today().year, "items": [{"category": "Utenze", "months": [100_000] * 12}]}
    assert client.put(f"/api/companies/{alfa}/budget", headers=accountant, json=body).status_code == 403
    assert client.put(f"/api/companies/{alfa}/budget", headers=owner, json=body).status_code == 200
    b = client.get(f"/api/companies/{alfa}/budget", headers=owner).json()
    assert [r["category"] for r in b["rows"] if r["budget_cents"]] == ["Utenze"]


# ---------- Finanziamenti e scenari ----------

def test_amortization():
    assert french_installment(10_000_000, 6, 12) == 860_664
    rows = schedule({"kind": "mutuo", "start_date": "2026-01-31", "months": 12, "principal_cents": 10_000_000, "rate": 6})
    assert rows[1]["date"] == "2026-02-28" and rows[-1]["residual_cents"] == 0
    assert sum(r["principal_cents"] for r in rows) == 10_000_000


def test_loans_and_forecast(client, owner):
    data = client.get("/api/loans", headers=owner).json()
    mutuo = next(l for l in data["items"] if l["kind"] == "mutuo")
    assert mutuo["paid_installments"] >= 17 and 0 < mutuo["residual_cents"] < 150_000_00
    assert data["totals"]["credit_available_cents"] == 72_000_00
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    fc = client.get(f"/api/forecast?company_id={alfa}&weeks=8", headers=owner).json()
    assert fc["credit_available_cents"] == 50_000_00
    assert any(i["kind"] == "rata" for w in fc["weeks"] for i in w["items"])
    r = client.post(f"/api/companies/{alfa}/loans", headers=owner, json={
        "kind": "finanziamento", "lender": "Banca B", "principal": "20.000", "rate": 5, "months": 24,
        "start_date": date.today().isoformat()})
    assert r.status_code == 200 and r.json()["installment_cents"] > 0
    assert client.post(f"/api/companies/{alfa}/loans", headers=owner, json={"kind": "mutuo", "lender": "X"}).status_code == 400


def test_scenarios(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]
    items = client.get(f"/api/forecast/open-items?company_id={alfa}", headers=owner).json()
    incasso = next(i for i in items if i["kind"] == "incasso" and i["amount_cents"] == 1_580_000)
    r = client.post("/api/forecast/scenario", headers=owner, json={"company_id": alfa, "weeks": 8, "adjustments": [
        {"type": "delay", "deadline_id": incasso["id"], "days": 120},
        {"type": "extra", "date": date.today().isoformat(), "amount_cents": -5_000_000, "description": "Acquisto macchinario"}]}).json()
    base_end = r["base"]["weeks"][-1]["balance_end_cents"]
    scen_end = r["scenario"]["weeks"][-1]["balance_end_cents"]
    assert base_end - scen_end == 1_580_000 + 5_000_000
    r = client.post("/api/forecast/scenario", headers=owner, json={"company_id": alfa, "weeks": 8, "adjustments": [
        {"type": "delay_party", "name": "Delta", "days": 60}]}).json()
    assert r["scenario"]["weeks"][-1]["balance_end_cents"] < r["base"]["weeks"][-1]["balance_end_cents"]


# ---------- Report, assistente, scontrini ----------

def test_monthly_report_pdf(client, owner, accountant):
    month = date.today().strftime("%Y-%m")
    r = client.get(f"/api/reports/monthly?month={month}", headers=owner)
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 3000
    alfa = companies(client, accountant)["Azienda Alfa Srl"]
    assert client.get(f"/api/reports/monthly?month={month}&company_id={alfa}", headers=accountant).status_code == 200
    assert client.get("/api/reports/monthly?month=2026-13", headers=owner).status_code == 400


@pytest.mark.parametrize("question,expected", [
    ("Quanto ho in banca in tutto?", "Liquidità totale"),
    ("Quanto ha speso Alfa di stipendi quest'anno?", "Personale"),
    ("Quali clienti mi devono più di 5.000 €?", "Delta Spa"),
    ("Cosa devo pagare nei prossimi 7 giorni?", "Nei prossimi 7 giorni"),
    ("Andrò in rosso nelle prossime settimane?", "punto più basso"),
    ("Quanta IVA devo versare?", "commercialista"),
])
def test_assistant_demo(client, owner, question, expected):
    r = client.post("/api/assistant/ask", headers=owner, json={"question": question})
    assert r.status_code == 200, r.text
    assert expected in r.json()["answer"]


def test_assistant_scope(client, accountant):
    r = client.post("/api/assistant/ask", headers=accountant, json={"question": "Quanto ho in banca?"}).json()
    assert "Gamma" not in r["answer"] and "Alfa" in r["answer"]
    viewer_cannot = login(client, "commercialista@demo.it")
    assert client.get("/api/assistant/status", headers=viewer_cannot).json()["enabled"]


def test_ai_suggest_and_receipt(client, owner):
    queue = client.get("/api/reconciliation", headers=owner).json()
    tx = next(t for t in queue if "CARTA" in t["description"])
    s = client.post(f"/api/transactions/{tx['id']}/ai-suggest", headers=owner).json()
    assert "explanation" in s
    r = client.post(f"/api/companies/{tx['company_id']}/receipts", headers=owner,
                    files={"file": ("scontrino.jpg", b"\xff\xd8\xff fake", "image/jpeg")}).json()
    doc_id = r["document"]["id"]
    assert r["candidates"] == []  # in demo i dati si inseriscono a mano
    r = client.put(f"/api/receipts/{doc_id}", headers=owner, json={"date": tx["date"], "total": "312,40",
                                                                   "merchant": "Ferramenta Bianchi"}).json()
    assert r["candidates"][0]["id"] == tx["id"]
    assert client.post(f"/api/receipts/{doc_id}/link", headers=owner, json={"transaction_id": tx["id"]}).status_code == 200
    assert all(t["id"] != tx["id"] for t in client.get("/api/reconciliation", headers=owner).json())


# ---------- Backup e attività automatiche ----------

def test_backup_and_restore(client, owner, tmp_path):
    from app.services.backup import describe, restore, run_backup

    async def go():
        # il database di prova vive nel ciclo asincrono del TestClient: si esegue lì dentro
        db = db_module.get_db()
        path = await run_backup(db, str(tmp_path))
        raw = open(path, "rb").read()
        info = describe(raw)
        await db.transactions.delete_many({})
        counts = await restore(db, raw)
        return info, counts, await db.transactions.count_documents({})
    info, counts, after = client.portal.call(go)
    assert info["collections"]["transactions"] > 0 and after == counts["transactions"] > 0


def test_scheduler_tick_runs_once_per_day(client):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services.scheduler import tick

    async def go():
        db = db_module.get_db()
        monday = datetime(2026, 11, 2, 9, 0, tzinfo=ZoneInfo("Europe/Rome"))
        await tick(db, monday)
        jobs = {j["name"]: j async for j in db.jobs.find({})}
        before = await db.outbox.count_documents({})
        await tick(db, monday)
        return jobs, before, await db.outbox.count_documents({})
    jobs, before, after = client.portal.call(go)
    assert {"avvisi_giornalieri", "iva_stimata", "riepilogo_settimanale"} <= set(jobs)
    assert all(not j.get("error") for j in jobs.values())
    assert before == after  # la seconda volta non ripete nulla
