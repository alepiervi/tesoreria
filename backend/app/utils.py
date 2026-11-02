import re
import uuid
from datetime import date, datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def today() -> date:
    return now_utc().date()


def parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def to_cents(value) -> int:
    """Converte un importo in euro (stringa o numero) in centesimi interi."""
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return value * 100
    text = str(value).strip().replace("€", "").replace(" ", "")
    # Formato italiano 1.234,56 -> 1234.56
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        # "2.400" o "1.250.000": il punto separa le migliaia (nessun decimale a tre cifre negli importi in euro)
        text = text.replace(".", "")
    return int(round(float(text) * 100))


def clean(doc: dict | None) -> dict | None:
    """Rimuove il campo interno _id di MongoDB prima di restituire un documento."""
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def mask_iban(iban: str) -> str:
    compact = iban.replace(" ", "").upper()
    if len(compact) < 8:
        return compact
    return f"{compact[:2]}•• •••• •••• {compact[-4:]}"
