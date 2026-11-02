"""Dati di esempio per la contabilità: centri di costo, cespiti, saldi iniziali e riepiloghi dello storico.

Lo storico dei movimenti dei dati di esempio non ha le fatture collegate: per avere un bilancio
credibile si aggiunge, mese per mese, una registrazione di riepilogo (vendite, acquisti, contributi).
Con i dati veri queste registrazioni non servono: le fanno da sole fatture e movimenti riconciliati.
"""
from collections import defaultdict
from datetime import date, timedelta

from .services.accounting import Lines, balances, ensure_chart, load_chart, party_of, sync_company
from .services.accounting_close import ASSET_CATEGORIES, asset_schedule
from .services.loans import schedule
from .utils import new_id, now_iso, today

COST_CENTERS = {
    "alfa": [("Produzione", "Reparto produttivo e capannone"), ("Commerciale", "Vendite e marketing"),
             ("Amministrazione", "Uffici e servizi generali")],
    "beta": [("Servizi", "Attività operativa"), ("Sede", "Costi generali")],
    "gamma": [("Logistica", "Magazzino e trasporti"), ("Sede", "Costi generali")],
}

ASSETS = {
    "alfa": [("Capannone via dell'Industria", "fabbricati", 280_000_00, "2021-03-15", "Produzione"),
             ("Linea di confezionamento", "impianti", 64_000_00, "2023-06-20", "Produzione"),
             ("Arredi uffici", "mobili", 14_500_00, "2024-02-10", "Amministrazione"),
             ("Computer e server", "elettroniche", 9_800_00, None, "Amministrazione")],
    "beta": [("Arredi sede", "mobili", 12_000_00, "2023-09-01", "Sede"),
             ("Notebook e stampanti", "elettroniche", 6_500_00, "2024-04-15", "Sede")],
    "gamma": [("Scaffalature magazzino", "attrezzature", 18_000_00, "2025-01-20", "Logistica"),
              ("Muletto elettrico", "automezzi", 26_000_00, "2024-07-08", "Logistica"),
              ("Gestionale di magazzino", "software", 4_800_00, None, "Logistica")],
}

CAPITAL = {"alfa": 50_000_00, "beta": 10_000_00, "gamma": 20_000_00}


def _entry(company_id: str, d: str, causale: str, description: str, lines: list[dict], doc_number=None) -> dict:
    return {"id": new_id(), "company_id": company_id, "date": d, "year": int(d[:4]), "causale": causale,
            "description": description, "doc_number": doc_number, "doc_date": None, "lines": lines,
            "source": "manuale", "source_key": None, "created_at": now_iso(), "updated_at": now_iso(),
            "created_by": None, "created_by_name": "Dati di esempio"}


def _split(gross: int) -> tuple[int, int]:
    net = round(gross / 1.22)
    return net, gross - net


async def seed_accounting(db, company_docs: dict, accounts_by_company: dict) -> None:
    t = today()
    year_start = date(t.year, 1, 1).isoformat()
    for key, company in company_docs.items():
        cid = company["id"]
        await ensure_chart(db, cid)
        company = await db.companies.find_one({"id": cid}, {"_id": 0})
        chart = await load_chart(db, company)

        # Centri di costo
        cc_ids = {}
        for name, descr in COST_CENTERS[key]:
            cc_ids[name] = new_id()
            await db.cost_centers.insert_one({"id": cc_ids[name], "company_id": cid, "name": name, "description": descr,
                                              "active": True, "created_at": now_iso()})
        # Affitto e utenze sui centri di costo "di sede"
        main_cc = cc_ids.get("Amministrazione") or cc_ids.get("Sede")
        await db.transactions.update_many({"company_id": cid, "category": {"$in": ["Affitti", "Utenze"]}},
                                          {"$set": {"cost_center_id": main_cc}})

        # Cespiti (quelli senza data sono stati acquistati quest'anno)
        assets = []
        for name, cat, cost, purchase, cc in ASSETS[key]:
            purchase = purchase or date(t.year, max(1, t.month - 6), 12).isoformat()
            a = {"id": new_id(), "company_id": cid, "name": name, "category": cat, "rate": ASSET_CATEGORIES[cat][1],
                 "cost_cents": cost, "purchase_date": purchase, "first_year_half": True, "accumulated_before_cents": 0,
                 "accumulated_before_year": None, "disposed_date": None, "cost_center_id": cc_ids.get(cc),
                 "invoice_id": None, "created_at": now_iso()}
            assets.append(a)
        await db.assets.insert_many([dict(a) for a in assets])

        entries = []
        # Acquisto dei cespiti dell'anno (pagati dalla banca principale: entrano nel saldo iniziale calcolato sotto)
        bank_main = chart.k(f"banca:{accounts_by_company[key][0]['id']}")
        for a in assets:
            if a["purchase_date"] >= year_start:
                net = a["cost_cents"]
                L = Lines()
                L.add(chart.k(ASSET_CATEGORIES[a["category"]][2]), net, "D", cost_center_id=a["cost_center_id"])
                L.add(chart.k("iva_credito"), round(net * 0.22), "D")
                L.add(bank_main, net + round(net * 0.22), "A")
                entries.append(_entry(cid, a["purchase_date"], "GEN", f"Acquisto cespite: {a['name']}", L.items))

        # Riepilogo mensile dello storico (vendite, acquisti e contributi senza fattura collegata)
        months: dict[str, dict] = defaultdict(lambda: {"sales": 0, "purchases": 0, "f24": 0, "last": ""})
        async for tx in db.transactions.find({"company_id": cid, "exclusion_reason": "Storico importato"}, {"_id": 0}):
            m = months[tx["date"][:7]]
            target = chart.for_category(tx.get("category", ""))
            if tx["amount_cents"] > 0 and target == chart.k("transitorio"):
                m["sales"] += tx["amount_cents"]
            elif tx["amount_cents"] < 0 and target == chart.k("anticipi_fornitori"):
                m["purchases"] += -tx["amount_cents"]
            elif tx["amount_cents"] < 0 and target == chart.k("erario_tributi"):
                m["f24"] += -tx["amount_cents"]
            m["last"] = max(m["last"], tx["date"])
        for ym, m in sorted(months.items()):
            L = Lines()
            if m["sales"]:
                net, vat = _split(m["sales"])
                L.add(chart.k("transitorio"), m["sales"], "D", description="Incassi del mese")
                L.add(chart.k("ricavi"), net, "A", cost_center_id=cc_ids.get("Commerciale"), description="Vendite del mese")
                L.add(chart.k("iva_debito"), vat, "A")
            if m["purchases"]:
                net, vat = _split(m["purchases"])
                L.add(chart.k("acquisti_merci"), net, "D", cost_center_id=cc_ids.get("Produzione") or cc_ids.get("Logistica"),
                      description="Acquisti del mese")
                L.add(chart.k("iva_credito"), vat, "D")
                L.add(chart.k("anticipi_fornitori"), m["purchases"], "A", description="Pagamenti a fornitori del mese")
            if m["f24"]:
                L.add(chart.k("costi_oneri_sociali"), m["f24"], "D", description="Contributi e ritenute dalle paghe")
                L.add(chart.k("erario_tributi"), m["f24"], "A")
            y, mo = int(ym[:4]), int(ym[5:])
            last_day = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1))
            d = min(last_day, t - timedelta(days=1)).isoformat()
            entries.append(_entry(cid, d, "GEN", f"Riepilogo fatture e paghe {mo:02d}/{y} (storico dei dati di esempio)", L.items))

        # Fatture già incassate prima di usare il programma (nessun movimento in banca collegato)
        async for inv in db.invoices.find({"company_id": cid, "status": "pagata"}, {"_id": 0}):
            if await db.transactions.find_one({"allocations.id": inv["id"]}):
                continue
            L = Lines()
            group = bool(inv.get("intercompany_company_id"))
            if inv["direction"] == "attiva":
                L.add(bank_main, inv["paid_cents"], "D")
                L.add(chart.k("gruppo_crediti" if group else "clienti"), inv["paid_cents"], "A", party_of(inv))
            else:
                L.add(chart.k("gruppo_debiti" if group else "fornitori"), inv["paid_cents"], "D", party_of(inv))
                L.add(bank_main, inv["paid_cents"], "A")
            entries.append(_entry(cid, inv.get("paid_at") or inv["date"], "INC" if inv["direction"] == "attiva" else "PAG",
                                  f"{'Incasso' if inv['direction'] == 'attiva' else 'Pagamento'} fattura {inv['number']} "
                                  f"{inv.get('counterparty_name', '')}".strip(), L.items, inv["number"]))
        if entries:
            await db.entries.insert_many([dict(e) for e in entries])

        # Registrazioni automatiche da fatture e movimenti già sistemati
        await sync_company(db, cid)

        # Saldi iniziali al 1° gennaio: le banche quadrano con il saldo attuale meno i movimenti da riconciliare
        bal = await balances(db, cid)
        L = Lines()
        for bank in accounts_by_company[key]:
            b = await db.bank_accounts.find_one({"id": bank["id"]}, {"_id": 0})
            code = chart.k(f"banca:{bank['id']}")
            pending = 0
            async for tx in db.transactions.find({"account_id": bank["id"], "status": "da_riconciliare"}, {"amount_cents": 1}):
                pending += tx["amount_cents"]
            target = b["balance_cents"] - pending
            L.add(code, target - bal.get(code, {}).get("saldo", 0), "D", description="Saldo al 1° gennaio")
        for a in assets:
            if a["purchase_date"] >= year_start:
                continue
            _, _, imm, fondo, _ = ASSET_CATEGORIES[a["category"]]
            fund = sum(r["quota_cents"] for r in asset_schedule(a, t.year - 1) if r["year"] < t.year)
            L.add(chart.k(imm), a["cost_cents"], "D", description=a["name"])
            L.add(chart.k(fondo), fund, "A", description=a["name"])
        async for loan in db.loans.find({"company_id": cid, "kind": "mutuo"}, {"_id": 0}):
            rows = [r for r in schedule(loan) if r["date"] < t.isoformat()]
            residual = rows[-1]["residual_cents"] if rows else loan["principal_cents"]
            L.add(chart.k("debiti_finanziamenti"), residual, "A", description=f"{loan['lender']} · {loan['description']}")
        L.add(chart.k("capitale"), CAPITAL[key], "A")
        dare, avere = L.totals()
        L.add(chart.k("utili_a_nuovo"), dare - avere, "A", description="Riserve e utili degli anni precedenti")
        await db.entries.insert_one(_entry(cid, year_start, "APE", "Saldi iniziali (inizio uso del programma)", L.items))


async def seed_control(db, company_docs: dict, accounts_by_company: dict) -> None:
    """Dati di esempio per paghe, Centrale Rischi, commesse e riserva minima di liquidità."""
    from .services import payroll
    t = today()
    alfa, beta, gamma = company_docs["alfa"], company_docs["beta"], company_docs["gamma"]

    # Riserva minima di cassa per azienda (serve alla liquidità di gruppo)
    for c, buffer in ((alfa, 40_000_00), (beta, 15_000_00), (gamma, 25_000_00)):
        await db.companies.update_one({"id": c["id"]}, {"$set": {"cash_buffer_cents": buffer}})

    # Paghe del mese in corso di Alfa: il bonifico "Stipendi mese" da riconciliare chiude il netto
    company = await db.companies.find_one({"id": alfa["id"]}, {"_id": 0})
    month = t.strftime("%Y-%m")
    p = {"id": new_id(), "company_id": alfa["id"], "month": month, "employees": 12, "pay_date": f"{month}-27",
         "cost_center_id": None, "note": "", "lordo_cents": 38_650_00, "contributi_ditta_cents": 11_600_00,
         "contributi_dipendente_cents": 2_900_00, "irpef_cents": 7_150_00, "altre_trattenute_cents": 0,
         "netto_cents": 28_600_00, "tfr_cents": 2_860_00, "updated_at": now_iso(), "updated_by_name": "Dati di esempio"}
    await payroll.post(db, company, p)
    await db.payrolls.insert_one(dict(p))

    # Centrale Rischi di Alfa e Beta (ultimi due mesi disponibili: la Banca d'Italia pubblica con un mese di ritardo)
    def month_back(n):
        y, m = t.year, t.month - n
        while m <= 0:
            m += 12
            y -= 1
        return f"{y}-{m:02d}"
    rows = []
    for n in (2, 1):
        mk = month_back(n)
        for company_id, bank, cat, granted, used, over in (
            (alfa["id"], "Banca A", "revoca", 50_000_00, 0, 0),
            (alfa["id"], "Banca A", "scadenza", 112_000_00 + n * 2_400_00, 112_000_00 + n * 2_400_00, 0),
            (alfa["id"], "Banca B", "autoliquidanti", 40_000_00, 12_500_00, 0),
            (beta["id"], "Banca A", "autoliquidanti", 30_000_00, 8_000_00, 0),
            (beta["id"], "Banca A", "revoca", 10_000_00, 10_850_00 if n == 1 else 9_200_00, 850_00 if n == 1 else 0),
        ):
            rows.append({"id": new_id(), "company_id": company_id, "month": mk, "bank": bank, "category": cat,
                         "granted_cents": granted, "used_cents": used, "overdraft_cents": over, "past_due_cents": 0,
                         "updated_at": now_iso()})
    await db.central_risk.insert_many(rows)

    # Commessa di Alfa con fatture collegate
    pid = new_id()
    await db.cost_centers.insert_one({"id": pid, "company_id": alfa["id"], "kind": "commessa", "name": "Impianto Delta Spa",
                                      "description": "Fornitura e posa linea di imballaggio", "customer": "Delta Spa",
                                      "budget_revenue_cents": 40_000_00, "budget_cost_cents": 26_000_00,
                                      "start_date": f"{t.year}-09-01", "end_date": f"{t.year}-12-20", "status": "aperta",
                                      "created_at": now_iso()})
    from .services.accounting import sync_source
    for number in ("128/2026", "352", "2026-77"):
        inv = await db.invoices.find_one({"company_id": alfa["id"], "number": number})
        if inv:
            await db.invoices.update_one({"id": inv["id"]}, {"$set": {"cost_center_id": pid}})
            await sync_source(db, "invoice", inv["id"])

