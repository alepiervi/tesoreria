"""Rimanenze di magazzino di fine anno: valore finale al 31/12 e storno al 1° gennaio (diventano rimanenze iniziali)."""
from .accounting import AccountingError, Lines, load_chart, upsert_auto_entry


def total_of(doc: dict) -> int:
    if doc.get("items"):
        return sum(round(float(i.get("qty") or 0) * int(i.get("unit_cost_cents") or 0)) for i in doc["items"])
    return int(doc.get("value_cents") or 0)


async def post(db, company: dict, doc: dict) -> None:
    chart = await load_chart(db, company)
    value = total_of(doc)
    year = doc["year"]
    final = initial = None
    if value > 0:
        L = Lines()
        L.add(chart.k("rimanenze"), value, "D")
        L.add(chart.k("variazione_rimanenze"), value, "A")
        final = {"date": f"{year}-12-31", "causale": "GEN", "description": f"Rimanenze finali di magazzino {year}",
                 "doc_number": None, "doc_date": None, "lines": L.items}
        L2 = Lines()
        L2.add(chart.k("variazione_rimanenze"), value, "D")
        L2.add(chart.k("rimanenze"), value, "A")
        initial = {"date": f"{year + 1}-01-01", "causale": "STO", "description": f"Rimanenze iniziali {year + 1} (storno delle finali {year})",
                   "doc_number": None, "doc_date": None, "lines": L2.items}
    for key, entry in ((f"rim:{year}", final), (f"rim:{year}:storno", initial)):
        if await upsert_auto_entry(db, company, key, entry, source="rettifica") == "bloccata":
            raise AccountingError("L'esercizio è chiuso: riaprilo per cambiare le rimanenze.")
