"""Categorie dei movimenti, regole predefinite e regole personali.

Le regole personali (create dall'utente correggendo una categoria) hanno la precedenza
su quelle predefinite. Vince la regola con il testo più lungo, cioè la più specifica.
"""
import re

CATEGORIES = [
    "Incassi clienti", "Fornitori", "Personale", "Imposte e tasse", "Affitti", "Utenze",
    "Leasing e finanziamenti", "Oneri bancari", "Carburante e trasporti", "Software e servizi",
    "Giroconti", "Intercompany", "Altre entrate", "Altre uscite", "Da classificare",
]

# Categorie che non sono né ricavi né costi: escluse dai grafici, dal budget e dal consolidato di gruppo
NEUTRAL_CATEGORIES = {"Giroconti", "Intercompany"}

# (parole chiave, categoria). La prima regola che corrisponde vince.
RULES = [
    (("stipend", "cedolin", "emolument"), "Personale"),
    (("f24", "agenzia entrate", "iva ", "inps", "inail", "ritenut"), "Imposte e tasse"),
    (("affitto", "locazione", "canone sede"), "Affitti"),
    (("energia", "enel", "gas", "acqua", "telefon", "fibra"), "Utenze"),
    (("leasing", "rata mutuo", "finanziamento", "rata prestito"), "Leasing e finanziamenti"),
    (("commission", "spese tenuta", "canone conto", "bollo"), "Oneri bancari"),
    (("carburante", "autostrad", "telepass", "trasport"), "Carburante e trasporti"),
    (("software", "abbonamento", "cloud", "licenza"), "Software e servizi"),
    (("giroconto", "trasferimento tra conti", "saldo carta", "carta di credito", "e/c carta", "estratto conto carta",
      "addebito carta", "american express", "amex", "cartasi", "nexi payments", "diners club"), "Giroconti"),
    (("pos", "incasso", "bonifico da"), "Incassi clienti"),
    (("bonifico a", "fornitor"), "Fornitori"),
]

MONTHS = {"gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
          "ottobre", "novembre", "dicembre", "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set",
          "ott", "nov", "dic"}
STOP = {"del", "della", "dei", "per", "con", "rif", "ns", "vs", "fattura", "ft", "saldo", "n", "nr"}


def _apply_rules(text: str, amount_cents: int, rules: list[dict]) -> str | None:
    for r in sorted(rules, key=lambda r: -len(r["pattern"])):
        if r.get("direction") == "in" and amount_cents < 0:
            continue
        if r.get("direction") == "out" and amount_cents > 0:
            continue
        if r["pattern"].lower() in text:
            return r["category"]
    return None


def categorize(description: str, amount_cents: int, rules: list[dict] | None = None) -> str:
    text = f" {description.lower()} "
    if rules:
        custom = _apply_rules(text, amount_cents, rules)
        if custom:
            return custom
    for keywords, category in RULES:
        if any(k in text for k in keywords):
            # Una parola da entrata su un'uscita (o viceversa) non basta: "Rho Trasporti" che paga è un incasso
            if category == "Incassi clienti" and amount_cents < 0:
                continue
            if category not in {"Incassi clienti", "Giroconti"} and amount_cents > 0:
                continue
            return category
    return "Altre entrate" if amount_cents > 0 else "Da classificare"


# Sull'estratto della carta: il pagamento del saldo addebitato in conto corrente è un giroconto, non un'entrata
CARD_PAYMENT_WORDS = ("pagamento saldo", "pagamento ricevuto", "addebito su c/c", "addebito in c/c", "addebito c/c",
                      "vostro pagamento", "saldo precedente", "pagamento estratto", "addebito rid", "addebito sdd", "grazie per il pagamento")


def categorize_card(description: str, amount_cents: int, rules: list[dict] | None = None) -> str:
    text = f" {description.lower()} "
    if amount_cents > 0 and any(k in text for k in CARD_PAYMENT_WORDS):
        return "Giroconti"
    cat = categorize(description, amount_cents, rules)
    return "Altre entrate" if cat == "Giroconti" else cat


def suggest_pattern(description: str) -> str:
    """Propone il testo per una regola: le prime parole significative, senza numeri, date e mesi."""
    words = []
    for w in re.findall(r"[A-Za-zÀ-ÿ*]+(?:[.'][A-Za-zÀ-ÿ]+)*", description):
        lw = w.lower()
        if len(lw) < 3 or lw in MONTHS or lw in STOP or "*" in lw:
            continue
        if lw in (x.lower() for x in words):
            continue
        words.append(w)
        if len(words) == 3:
            break
    return " ".join(words).lower()


async def load_rules(db, company_id: str) -> list[dict]:
    return await db.category_rules.find({"company_id": {"$in": [company_id, None]}}, {"_id": 0}).to_list(2000)
