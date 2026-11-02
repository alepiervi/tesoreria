"""Crediti verso clienti e debiti verso fornitori, per anzianità, con ritardo medio di pagamento."""
from ..utils import parse_date, today
from .invoices import norm_vat, payable

BUCKETS = [
    ("non_scaduto", "Non ancora scaduto"),
    ("d0_30", "Scaduto da 1-30 giorni"),
    ("d31_60", "31-60 giorni"),
    ("d61_90", "61-90 giorni"),
    ("oltre_90", "Oltre 90 giorni"),
]


def bucket_of(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "non_scaduto"
    if days_overdue <= 30:
        return "d0_30"
    if days_overdue <= 60:
        return "d31_60"
    if days_overdue <= 90:
        return "d61_90"
    return "oltre_90"


def party_key(company_id: str, inv: dict) -> str:
    return f"{company_id}|{norm_vat(inv.get('counterparty_vat')) or inv.get('counterparty_name', '').lower()}"


async def aging(db, company_ids: list[str], names: dict, direction: str = "attiva",
                include_intercompany: bool = False) -> dict:
    t = today()
    q = {"company_id": {"$in": company_ids}, "direction": direction, "total_cents": {"$gt": 0}}
    if not include_intercompany:
        q["intercompany_company_id"] = None
    invoices = await db.invoices.find(q, {"_id": 0}).to_list(50000)
    contacts = {f"{c['company_id']}|{c['vat_key']}": c
                async for c in db.contacts.find({"company_id": {"$in": company_ids}}, {"_id": 0})}

    parties: dict[str, dict] = {}
    totals = {b: 0 for b, _ in BUCKETS}
    for inv in invoices:
        key = party_key(inv["company_id"], inv)
        p = parties.setdefault(key, {
            "key": key, "company_id": inv["company_id"], "company_name": names.get(inv["company_id"], ""),
            "name": inv.get("counterparty_name", ""), "vat": inv.get("counterparty_vat", ""),
            "open_cents": 0, "buckets": {b: 0 for b, _ in BUCKETS}, "invoices": [],
            "delays": [], "paid_count": 0, "max_overdue_days": 0,
        })
        if inv["status"] == "pagata":
            p["paid_count"] += 1
            if inv.get("paid_at") and inv.get("due_date"):
                p["delays"].append((parse_date(inv["paid_at"]) - parse_date(inv["due_date"])).days)
            continue
        residual = payable(inv) - inv.get("paid_cents", 0)
        if residual <= 0:
            continue
        overdue = (t - parse_date(inv["due_date"])).days
        b = bucket_of(overdue)
        p["buckets"][b] += residual
        p["open_cents"] += residual
        p["max_overdue_days"] = max(p["max_overdue_days"], overdue)
        totals[b] += residual
        reminders = inv.get("reminders") or []
        p["invoices"].append({
            "id": inv["id"], "number": inv["number"], "date": inv["date"], "due_date": inv["due_date"],
            "total_cents": inv["total_cents"], "residual_cents": residual, "days_overdue": max(0, overdue),
            "bucket": b, "reminders_count": len(reminders),
            "last_reminder_at": reminders[-1]["at"] if reminders else None,
            "last_reminder_level": reminders[-1]["level"] if reminders else 0,
            "has_xml": inv.get("has_xml", False),
        })

    result = []
    for p in parties.values():
        delays = p.pop("delays")
        p["avg_delay_days"] = round(sum(delays) / len(delays)) if delays else None
        p["late_payer"] = bool(delays) and sum(delays) / len(delays) > 15
        c = contacts.get(f"{p['company_id']}|{norm_vat(p['vat']) or p['name'].lower()}")
        p["email"] = (c or {}).get("email", "")
        p["phone"] = (c or {}).get("phone", "")
        p["invoices"].sort(key=lambda i: i["due_date"])
        if p["open_cents"] > 0 or p["late_payer"]:
            result.append(p)
    result.sort(key=lambda p: (-p["max_overdue_days"] if p["open_cents"] else 1, -p["open_cents"]))
    return {"buckets": [{"id": b, "label": l, "amount_cents": totals[b]} for b, l in BUCKETS],
            "total_cents": sum(totals.values()),
            "overdue_cents": sum(v for k, v in totals.items() if k != "non_scaduto"),
            "parties": result}


LEVELS = {
    1: ("Promemoria", "le ricordiamo che risulta ancora da saldare"),
    2: ("Sollecito di pagamento", "nonostante il nostro precedente promemoria, risulta ancora da saldare"),
    3: ("Ultimo sollecito", "nonostante i precedenti solleciti, risulta ancora da saldare"),
}


def reminder_draft(company: dict, inv: dict, level: int, iban: str = "") -> tuple[str, str]:
    from ..utils import parse_date as pd
    level = max(1, min(3, level))
    label, phrase = LEVELS[level]
    residual = payable(inv) - inv.get("paid_cents", 0)
    amount = f"{residual / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    subject = f"{label}: fattura n. {inv['number']} del {pd(inv['date']).strftime('%d/%m/%Y')}"
    lines = [
        "Gentile cliente,",
        "",
        f"{phrase} la fattura n. {inv['number']} del {pd(inv['date']).strftime('%d/%m/%Y')}, "
        f"scaduta il {pd(inv['due_date']).strftime('%d/%m/%Y')}, per un importo di {amount} €.",
        "",
    ]
    if iban:
        lines += [f"Può effettuare il pagamento con bonifico sull'IBAN {iban}, indicando il numero della fattura.", ""]
    if level == 3:
        lines += ["In mancanza di pagamento entro 10 giorni dal ricevimento di questa comunicazione, "
                  "saremo costretti a tutelare i nostri interessi nelle sedi opportune.", ""]
    lines += ["Se il pagamento è già stato effettuato, la preghiamo di non tenere conto di questo messaggio "
              "e di inviarci la contabile.", "", "Cordiali saluti", company["name"]]
    return subject, "\n".join(lines)
