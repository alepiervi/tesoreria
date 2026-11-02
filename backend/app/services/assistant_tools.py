"""Strumenti di sola lettura usati dall'assistente. Ognuno lavora solo sulle aziende che l'utente può vedere.

Restituiscono dati compatti (importi in euro come numeri) che l'assistente usa per rispondere.
"""
import re
from datetime import date, timedelta

from ..utils import parse_date, today
from .budget import budget_status
from .categories import CATEGORIES, NEUTRAL_CATEGORIES
from .forecast import weekly_forecast
from .receivables import aging
from .vat import compute as vat_compute


def _e(cents: int) -> float:
    return round(cents / 100, 2)


class Tools:
    def __init__(self, db, scope: dict[str, dict]):
        self.db = db
        self.scope = scope  # {company_id: {name, role, permissions}}
        self.names = {k: v["name"] for k, v in scope.items()}

    def companies(self, name: str | None) -> list[str]:
        if not name:
            return list(self.scope)
        q = name.lower()
        hits = [cid for cid, n in self.names.items() if q in n.lower() or any(
            t in n.lower().split() for t in re.findall(r"[a-zà-ù]{3,}", q) if t not in {"srl", "spa", "azienda"})]
        return hits or []

    async def elenco_aziende(self) -> dict:
        return {"aziende": [{"nome": n, "ruolo": self.scope[c]["role"]} for c, n in self.names.items()]}

    async def saldi(self, azienda: str | None = None) -> dict:
        ids = self.companies(azienda)
        rows = []
        async for a in self.db.bank_accounts.find({"company_id": {"$in": ids}, "status": {"$ne": "scollegato"}}):
            rows.append({"azienda": self.names[a["company_id"]], "banca": a["bank_name"], "conto": a["iban_masked"],
                         "saldo": _e(a.get("balance_cents", 0)), "aggiornato_al": a.get("balance_date")})
        return {"conti": rows, "totale": round(sum(r["saldo"] for r in rows), 2)}

    async def entrate_uscite(self, dal: str, al: str, azienda: str | None = None, categoria: str | None = None,
                             testo: str | None = None) -> dict:
        ids = self.companies(azienda)
        q = {"company_id": {"$in": ids}, "date": {"$gte": dal, "$lte": al}, "category": {"$nin": list(NEUTRAL_CATEGORIES)}}
        if categoria:
            match = [c for c in CATEGORIES if c.lower() == categoria.lower()]
            if match:
                q["category"] = match[0]
        if testo:
            q["description"] = {"$regex": re.escape(testo), "$options": "i"}
        by_cat: dict[str, dict] = {}
        by_company: dict[str, dict] = {}
        count = 0
        async for t in self.db.transactions.find(q, {"category": 1, "amount_cents": 1, "company_id": 1}):
            count += 1
            for key, store in ((t["category"], by_cat), (self.names[t["company_id"]], by_company)):
                r = store.setdefault(key, {"entrate": 0, "uscite": 0})
                r["entrate" if t["amount_cents"] > 0 else "uscite"] += abs(t["amount_cents"])
        conv = lambda d: {k: {"entrate": _e(v["entrate"]), "uscite": _e(v["uscite"])} for k, v in d.items()}
        return {"periodo": [dal, al], "movimenti": count, "per_categoria": conv(by_cat), "per_azienda": conv(by_company),
                "totale_entrate": _e(sum(v["entrate"] for v in by_cat.values())),
                "totale_uscite": _e(sum(v["uscite"] for v in by_cat.values()))}

    async def crediti(self, azienda: str | None = None, importo_minimo: float = 0, solo_scaduti: bool = False,
                      tipo: str = "clienti") -> dict:
        ids = self.companies(azienda)
        data = await aging(self.db, ids, self.names, "attiva" if tipo == "clienti" else "passiva")
        rows = []
        for p in data["parties"]:
            if not p["open_cents"] or p["open_cents"] < importo_minimo * 100:
                continue
            if solo_scaduti and p["max_overdue_days"] <= 0:
                continue
            rows.append({"nome": p["name"], "azienda": p["company_name"], "aperto": _e(p["open_cents"]),
                         "scaduto_da_giorni": max(0, p["max_overdue_days"]), "fatture": len(p["invoices"]),
                         "ritardo_medio_giorni": p["avg_delay_days"]})
        return {"tipo": tipo, "elenco": rows[:30], "totale_aperto": _e(data["total_cents"]),
                "totale_scaduto": _e(data["overdue_cents"])}

    async def scadenze(self, giorni: int = 30, azienda: str | None = None) -> dict:
        ids = self.companies(azienda)
        limit = (today() + timedelta(days=int(giorni))).isoformat()
        rows = []
        async for d in self.db.deadlines.find({"company_id": {"$in": ids}, "due_date": {"$lte": limit},
                                               "status": {"$in": ["aperta", "da_pagare", "in_attesa_autorizzazione"]}}).sort("due_date", 1):
            rows.append({"data": d["due_date"], "tipo": d["kind"], "descrizione": d["description"],
                         "importo": _e(d["amount_cents"]), "azienda": self.names[d["company_id"]],
                         "scaduta": d["due_date"] < today().isoformat()})
        return {"entro_giorni": giorni, "scadenze": rows[:40],
                "totale_da_pagare": round(sum(r["importo"] for r in rows if r["tipo"] != "incasso"), 2),
                "totale_da_incassare": round(sum(r["importo"] for r in rows if r["tipo"] == "incasso"), 2)}

    async def cerca_movimenti(self, testo: str | None = None, dal: str | None = None, al: str | None = None,
                              importo_minimo: float | None = None, azienda: str | None = None, limite: int = 15) -> dict:
        ids = self.companies(azienda)
        q: dict = {"company_id": {"$in": ids}}
        if testo:
            q["description"] = {"$regex": re.escape(testo), "$options": "i"}
        if dal or al:
            q["date"] = {**({"$gte": dal} if dal else {}), **({"$lte": al} if al else {})}
        rows = []
        async for t in self.db.transactions.find(q).sort("date", -1).limit(500):
            if importo_minimo and abs(t["amount_cents"]) < importo_minimo * 100:
                continue
            rows.append({"data": t["date"], "descrizione": t["description"], "importo": _e(t["amount_cents"]),
                         "categoria": t["category"], "azienda": self.names[t["company_id"]], "stato": t["status"]})
            if len(rows) >= min(int(limite), 40):
                break
        return {"movimenti": rows}

    async def previsione(self, azienda: str | None = None, settimane: int = 8) -> dict:
        ids = self.companies(azienda)
        fc = await weekly_forecast(self.db, ids, max(4, min(int(settimane), 26)))
        return {"saldo_iniziale": _e(fc["opening_balance_cents"]),
                "settimane": [{"dal": w["start"], "entrate": _e(w["inflow_cents"]), "uscite": _e(w["outflow_cents"]),
                               "saldo_fine": _e(w["balance_end_cents"])} for w in fc["weeks"]],
                "minimo": _e(fc["lowest"]["balance_cents"]), "settimana_minimo": fc["lowest"]["week"],
                "va_in_negativo": fc["goes_negative"], "fidi_disponibili": _e(fc["credit_available_cents"])}

    async def iva(self, azienda: str | None = None) -> dict:
        out = []
        for cid in self.companies(azienda):
            company = await self.db.companies.find_one({"id": cid}, {"_id": 0})
            data = await vat_compute(self.db, company, today().year)
            open_rows = [r for r in data["periods"] if r["state"] != "futuro"]
            out.append({"azienda": self.names[cid], "periodicita": data["mode"],
                        "periodi": [{"periodo": r["label"], "iva_vendite": _e(r["sales_vat_cents"]),
                                     "iva_acquisti": _e(r["purchases_vat_cents"]), "da_versare": _e(r["to_pay_cents"]),
                                     "scadenza": r["due_date"]} for r in open_rows[-4:]]})
        return {"stima_iva": out, "nota": data["note"] if out else ""}

    async def budget(self, azienda: str | None = None, mese: str | None = None) -> dict:
        t = today()
        y, m = (int(mese[:4]), int(mese[5:7])) if mese and re.fullmatch(r"\d{4}-\d{2}", mese) else (t.year, t.month)
        out = []
        for cid in self.companies(azienda):
            b = await budget_status(self.db, cid, y, m)
            out.append({"azienda": self.names[cid], "mese": f"{y}-{m:02d}", "ha_budget": b["has_budget"],
                        "righe": [{"categoria": r["category"], "budget": _e(r["budget_cents"]), "reale": _e(r["actual_cents"]),
                                   "sforato": r["over"]} for r in b["rows"]]})
        return {"budget": out}


    async def salute_azienda(self, azienda: str | None = None) -> dict:
        """Segnali di allerta del Codice della crisi, DSCR e principali indici (solo con accesso alla contabilità)."""
        from .analysis import ratios, warning_signals
        out = []
        for cid in self.companies(azienda):
            if "view_accounting" not in self.scope[cid]["permissions"]:
                continue
            company = await self.db.companies.find_one({"id": cid}, {"_id": 0})
            alerts = await warning_signals(self.db, company)
            r = await ratios(self.db, company)
            out.append({"azienda": self.names[cid], "stato_generale": alerts["overall"],
                        "segnali": [{"titolo": s["title"], "stato": s["status"], "dettaglio": s["detail"]} for s in alerts["signals"]],
                        "indici": [{"indice": i["label"], "valore": round(i["value"], 3) if isinstance(i["value"], float) else i["value"],
                                    "stato": i["status"]} for i in r["items"]]})
        return {"aziende": out, "nota": "Valutazione automatica: va confermata dal commercialista."}


TOOL_SPECS = [
    ("elenco_aziende", "Elenco delle aziende che l'utente può vedere.", {}),
    ("saldi", "Saldi attuali dei conti bancari.", {"azienda": "string"}),
    ("entrate_uscite", "Totali di entrate e uscite in un periodo, per categoria e per azienda. Date AAAA-MM-GG.",
     {"dal": "string!", "al": "string!", "azienda": "string", "categoria": "string",
      "testo": "string (parola da cercare nella descrizione, es. 'carburante')"}),
    ("crediti", "Crediti verso clienti (tipo='clienti') o debiti verso fornitori (tipo='fornitori') ancora aperti.",
     {"azienda": "string", "importo_minimo": "number", "solo_scaduti": "boolean", "tipo": "string"}),
    ("scadenze", "Incassi e pagamenti in scadenza nei prossimi giorni (incluse quelle già scadute).",
     {"giorni": "integer", "azienda": "string"}),
    ("cerca_movimenti", "Cerca singoli movimenti bancari.",
     {"testo": "string", "dal": "string", "al": "string", "importo_minimo": "number", "azienda": "string", "limite": "integer"}),
    ("previsione", "Previsione del saldo di cassa settimana per settimana.", {"azienda": "string", "settimane": "integer"}),
    ("iva", "Stima dell'IVA da versare negli ultimi periodi.", {"azienda": "string"}),
    ("budget", "Budget e spesa reale del mese (mese nel formato AAAA-MM).", {"azienda": "string", "mese": "string"}),
    ("salute_azienda", "Segnali di allerta del Codice della crisi (stipendi, fornitori, banche, IVA, INPS), DSCR e indici di "
     "bilancio con semaforo verde/giallo/rosso.", {"azienda": "string"}),
]


def anthropic_tools() -> list[dict]:
    out = []
    for name, desc, params in TOOL_SPECS:
        props, required = {}, []
        for p, t in params.items():
            base = t.split(" ")[0]
            req = base.endswith("!")
            props[p] = {"type": base.rstrip("!")}
            if " " in t:
                props[p]["description"] = t.split(" ", 1)[1].strip("()")
            if req:
                required.append(p)
        out.append({"name": name, "description": desc,
                    "input_schema": {"type": "object", "properties": props, "required": required}})
    return out


def period_from_text(text: str) -> tuple[str, str, str]:
    """Riconosce periodi come 'quest'anno', 'mese scorso', 'ottobre', 'ultimi 30 giorni'. Restituisce (dal, al, etichetta)."""
    t = today()
    s = text.lower()
    months = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
              "ottobre", "novembre", "dicembre"]
    m = re.search(r"ultimi (\d+) giorni", s)
    if m:
        return (t - timedelta(days=int(m.group(1)))).isoformat(), t.isoformat(), f"negli ultimi {m.group(1)} giorni"
    if "mese scorso" in s or "scorso mese" in s:
        end = t.replace(day=1) - timedelta(days=1)
        return end.replace(day=1).isoformat(), end.isoformat(), "il mese scorso"
    if "questo mese" in s or "mese corrente" in s:
        return t.replace(day=1).isoformat(), t.isoformat(), "questo mese"
    if "anno scorso" in s:
        return f"{t.year - 1}-01-01", f"{t.year - 1}-12-31", f"nel {t.year - 1}"
    for i, name in enumerate(months, start=1):
        if re.search(rf"\b{name}\b", s):
            y = t.year if i <= t.month else t.year - 1
            end = date(y + (i == 12), i % 12 + 1, 1) - timedelta(days=1)
            return date(y, i, 1).isoformat(), end.isoformat(), f"a {name} {y}"
    return f"{t.year}-01-01", t.isoformat(), f"dall'inizio del {t.year}"
