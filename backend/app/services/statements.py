"""Lettura degli estratti conto scaricati dall'home banking.

Formati supportati:
- CSV ed Excel (.xlsx): le colonne vengono riconosciute dai nomi (Data, Descrizione, Importo,
  oppure Dare/Avere, Entrate/Uscite...). Se il riconoscimento sbaglia si può indicare a mano
  quale colonna è quale.
- CAMT.053 / CAMT.052 (XML ISO 20022): formato standard europeo dei movimenti.
- CBI "RH" (rendicontazione movimenti): formato a larghezza fissa delle banche italiane.

Il risultato è sempre lo stesso: un elenco di movimenti {date, value_date, description,
amount_cents, reference} più, se presente nel file, il saldo finale.
"""
import csv
import io
import re
import unicodedata
from datetime import date, datetime

from defusedxml import ElementTree as ET

MAX_ROWS = 20000


class StatementError(ValueError):
    pass


# ---------------------------------------------------------------- utilità

def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.strip().lower())


def parse_date_any(value) -> str | None:
    """Accetta 31/12/2026, 31-12-26, 31.12.2026, 2026-12-31, date di Excel. Restituisce YYYY-MM-DD."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$", text.split(" ")[0])
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_amount_any(value) -> int | None:
    """Accetta 1.234,56 · -1234.56 · € 1.234,56 · (1.234,56) · 1234,5-. Restituisce centesimi."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value) * 100))
    text = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):
        negative, text = True, text[:-1]
    if text.startswith("-"):
        negative, text = True, text[1:]
    elif text.startswith("+"):
        text = text[1:]
    if not re.fullmatch(r"[\d.,']+", text):
        return None
    text = text.replace("'", "")
    if "," in text and "." in text:
        # l'ultimo separatore è quello dei decimali
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".") if len(text.split(",")[-1]) <= 2 else text.replace(",", "")
    elif text.count(".") > 1 or (text.count(".") == 1 and len(text.split(".")[-1]) == 3 and len(text) > 4):
        # 1.234 o 1.234.567: punti delle migliaia
        text = text.replace(".", "")
    try:
        cents = int(round(float(text) * 100))
    except ValueError:
        return None
    return -cents if negative else cents


def _clean_desc(*parts) -> str:
    text = " ".join(str(p).strip() for p in parts if p not in (None, "") and str(p).strip())
    return re.sub(r"\s+", " ", text)[:500]


# ---------------------------------------------------------------- CSV / Excel

HEADER_KEYS = {
    "date": ["data contabile", "data operazione", "data registrazione", "data movimento", "data op", "data"],
    "value_date": ["data valuta", "valuta"],
    "amount": ["importo", "importo eur", "importo in euro", "ammontare", "amount"],
    "debit": ["dare", "addebiti", "addebito", "uscite", "uscita", "importo dare", "debit"],
    "credit": ["avere", "accrediti", "accredito", "entrate", "entrata", "importo avere", "credit"],
    "description": ["descrizione operazione", "descrizione", "causale", "dettagli", "dettaglio",
                    "operazione", "motivazione", "beneficiario", "ordinante", "description"],
    "balance": ["saldo", "saldo contabile", "saldo progressivo", "balance"],
    "reference": ["riferimento", "id operazione", "codice operazione", "cro", "trn"],
}


def _match(header: str, keys: list[str]) -> int:
    """Punteggio di corrispondenza di un'intestazione: più alto se il nome è più specifico."""
    h = _norm(header)
    best = 0
    for i, k in enumerate(keys):
        if h == k:
            best = max(best, 100 - i)
        elif h.startswith(k) or k in h:
            best = max(best, 50 - i)
    return best


def detect_mapping(headers: list[str]) -> dict:
    mapping: dict = {}
    used: set[int] = set()
    for field in ["value_date", "date", "debit", "credit", "amount", "balance", "reference"]:
        scores = [(i, _match(h, HEADER_KEYS[field])) for i, h in enumerate(headers) if i not in used]
        scores = [s for s in scores if s[1] > 0]
        if field == "date":
            scores = [s for s in scores if "valuta" not in _norm(headers[s[0]])]
        if field == "amount":
            scores = [s for s in scores if not any(k in _norm(headers[s[0]]) for k in ("dare", "avere", "saldo"))]
        if scores:
            idx = max(scores, key=lambda s: s[1])[0]
            mapping[field] = idx
            used.add(idx)
    descs = [i for i, h in enumerate(headers) if i not in used and _match(h, HEADER_KEYS["description"]) > 0]
    mapping["description"] = descs
    if "debit" in mapping and "credit" in mapping:
        # Colonne separate Dare/Avere: hanno la precedenza su un eventuale "Importo"
        mapping.pop("amount", None)
    elif "amount" in mapping:
        mapping.pop("debit", None)
        mapping.pop("credit", None)
    return mapping


def _find_header_row(rows: list[list]) -> int:
    """Molte banche mettono righe di intestazione prima della tabella: cerca la riga con i nomi delle colonne."""
    for i, row in enumerate(rows[:40]):
        cells = [_norm(c) for c in row]
        has_date = any(c.startswith("data") or c == "valuta" for c in cells)
        has_amount = any(any(k in c for k in ("importo", "dare", "avere", "entrate", "uscite", "addebit", "accredit", "amount"))
                         for c in cells)
        if has_date and has_amount:
            return i
    raise StatementError("Non trovo l'intestazione delle colonne (Data, Descrizione, Importo…). "
                         "Controlla che il file sia l'elenco dei movimenti.")


def _rows_to_movements(headers: list[str], data_rows: list[list], mapping: dict) -> tuple[list[dict], list[str], int | None, str | None]:
    if "date" not in mapping:
        raise StatementError("Non trovo la colonna con la data del movimento.")
    if "amount" not in mapping and not ("debit" in mapping or "credit" in mapping):
        raise StatementError("Non trovo la colonna con l'importo (o le colonne Dare/Avere).")
    movements, warnings = [], []
    balance_cents, balance_date = None, None
    skipped = 0

    def cell(row, idx):
        return row[idx] if idx is not None and idx < len(row) else None

    for row in data_rows:
        if not any(str(c).strip() for c in row if c is not None):
            continue
        d = parse_date_any(cell(row, mapping["date"]))
        if not d:
            skipped += 1
            continue
        if "amount" in mapping:
            amount = parse_amount_any(cell(row, mapping["amount"]))
        else:
            debit = parse_amount_any(cell(row, mapping.get("debit")))
            credit = parse_amount_any(cell(row, mapping.get("credit")))
            amount = (abs(credit) if credit else 0) - (abs(debit) if debit else 0)
            if not debit and not credit:
                amount = None
        if amount is None or amount == 0:
            skipped += 1
            continue
        desc = _clean_desc(*[cell(row, i) for i in mapping.get("description", [])]) or "Movimento"
        movements.append({
            "date": d,
            "value_date": parse_date_any(cell(row, mapping.get("value_date"))) or d,
            "description": desc,
            "amount_cents": amount,
            "reference": str(cell(row, mapping.get("reference")) or "").strip(),
        })
        if "balance" in mapping:
            b = parse_amount_any(cell(row, mapping["balance"]))
            if b is not None and (balance_date is None or d >= balance_date):
                balance_cents, balance_date = b, d
        if len(movements) > MAX_ROWS:
            raise StatementError(f"Il file ha più di {MAX_ROWS} movimenti: dividilo in più parti.")
    if skipped:
        warnings.append(f"{skipped} {'riga ignorata' if skipped == 1 else 'righe ignorate'} perché senza data "
                        "o importo validi (es. totali o righe di intestazione).")
    return movements, warnings, balance_cents, balance_date


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise StatementError("Codifica del file non riconosciuta.")


def _table_from_csv(data: bytes) -> list[list]:
    text = _decode(data)
    sample = "\n".join(text.splitlines()[:50])
    counts = {d: sample.count(d) for d in (";", "\t", ",", "|")}
    delimiter = max(counts, key=counts.get)
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _table_from_xlsx(data: bytes) -> list[list]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise StatementError("Il file Excel non si apre. Se è un vecchio .xls, salvalo come .xlsx o CSV.")
    best = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        try:
            _find_header_row(rows)
            return rows
        except StatementError:
            best = best or rows
    return best


def _guess_header_row(rows: list[list], mapping: dict | None) -> int:
    """Quando i nomi delle colonne non sono riconoscibili: -1 significa 'nessuna riga di intestazione'."""
    if mapping and "date" in mapping:
        for i, row in enumerate(rows[:60]):
            if mapping["date"] < len(row) and parse_date_any(row[mapping["date"]]):
                return i - 1
    for i, row in enumerate(rows[:40]):
        if sum(1 for c in row if c not in (None, "") and str(c).strip()) >= 3:
            # se la riga contiene già una data, è un movimento e non un'intestazione
            return i - 1 if any(parse_date_any(c) for c in row) else i
    raise StatementError("Non trovo una tabella di movimenti nel file.")


def parse_table(rows: list[list], mapping: dict | None = None) -> dict:
    try:
        h = _find_header_row(rows)
    except StatementError:
        h = _guess_header_row(rows, mapping)
    width = max((len(r) for r in rows[max(h, 0):max(h, 0) + 50]), default=0)
    if h >= 0:
        headers = [str(c or "").strip() or f"Colonna {n + 1}" for n, c in enumerate(rows[h])]
        headers += [f"Colonna {n + 1}" for n in range(len(headers), width)]
    else:
        headers = [f"Colonna {n + 1}" for n in range(width)]
    detected = detect_mapping(headers)
    use = mapping or detected
    base = {"headers": headers, "mapping": use, "detected_mapping": detected, "iban": None}
    try:
        movements, warnings, bal, bal_date = _rows_to_movements(headers, rows[h + 1:], use)
    except StatementError as e:
        if mapping:
            raise
        # Colonne non riconosciute: si restituiscono le intestazioni per farle scegliere all'utente
        preview_rows = [[("" if c is None else str(c)) for c in r] for r in rows[h + 1:h + 6]]
        return {**base, "movements": [], "warnings": [], "needs_mapping": True, "error": str(e),
                "raw_rows": preview_rows, "closing_balance_cents": None, "closing_balance_date": None}
    return {**base, "movements": movements, "warnings": warnings, "needs_mapping": False,
            "closing_balance_cents": bal, "closing_balance_date": bal_date}


# ---------------------------------------------------------------- CAMT.053 / .052

def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _children(node, name):
    return [c for c in node if _local(c.tag) == name]


def _path(node, path: str):
    cur = [node]
    for part in path.split("/"):
        cur = [c for n in cur for c in _children(n, part)]
        if not cur:
            return []
    return cur


def _ptext(node, path: str) -> str:
    found = _path(node, path)
    return (found[0].text or "").strip() if found else ""


def parse_camt(data: bytes) -> dict:
    try:
        root = ET.fromstring(data)
    except Exception:
        raise StatementError("Il file XML non è valido.")
    containers = [c for c in root if _local(c.tag) in {"BkToCstmrStmt", "BkToCstmrAcctRpt", "BkToCstmrDbtCdtNtfctn"}]
    if not containers:
        raise StatementError("Il file XML non è un estratto conto CAMT (053, 052 o 054).")
    movements, iban = [], None
    bal_cents, bal_date = None, None
    for cont in containers:
        for stmt in [c for c in cont if _local(c.tag) in {"Stmt", "Rpt", "Ntfctn"}]:
            iban = iban or _ptext(stmt, "Acct/Id/IBAN") or None
            for bal in _children(stmt, "Bal"):
                code = _ptext(bal, "Tp/CdOrPrtry/Cd")
                if code in {"CLBD", "CLAV", "ITBD"}:
                    amt = parse_amount_any(_ptext(bal, "Amt"))
                    if amt is None:
                        continue
                    if _ptext(bal, "CdtDbtInd") == "DBIT":
                        amt = -amt
                    d = parse_date_any(_ptext(bal, "Dt/Dt") or _ptext(bal, "Dt/DtTm")[:10])
                    # il saldo contabile di chiusura ha la precedenza
                    if d and (bal_date is None or d > bal_date or (d == bal_date and code == "CLBD")):
                        bal_cents, bal_date = amt, d
            for ntry in _children(stmt, "Ntry"):
                if _ptext(ntry, "Sts") in {"PDNG", "INFO"} or _ptext(ntry, "Sts/Cd") in {"PDNG", "INFO"}:
                    continue
                amt = parse_amount_any(_ptext(ntry, "Amt"))
                if not amt:
                    continue
                credit = _ptext(ntry, "CdtDbtInd") == "CRDT"
                d = parse_date_any(_ptext(ntry, "BookgDt/Dt") or _ptext(ntry, "BookgDt/DtTm")[:10])
                vd = parse_date_any(_ptext(ntry, "ValDt/Dt") or _ptext(ntry, "ValDt/DtTm")[:10])
                if not d:
                    d = vd
                if not d:
                    continue
                tx = _path(ntry, "NtryDtls/TxDtls")
                party = ""
                remittance = ""
                if tx:
                    party = _ptext(tx[0], "RltdPties/Dbtr/Nm" if credit else "RltdPties/Cdtr/Nm") \
                        or _ptext(tx[0], "RltdPties/Dbtr/Pty/Nm" if credit else "RltdPties/Cdtr/Pty/Nm")
                    remittance = " ".join(u.text.strip() for u in _path(tx[0], "RmtInf/Ustrd") if u.text)
                info = _ptext(ntry, "AddtlNtryInf")
                desc = _clean_desc(info, ("da " if credit else "a ") + party if party else "", remittance) or "Movimento"
                movements.append({
                    "date": d, "value_date": vd or d, "description": desc,
                    "amount_cents": abs(amt) if credit else -abs(amt),
                    "reference": _ptext(ntry, "AcctSvcrRef") or _ptext(ntry, "NtryRef"),
                })
    return {"headers": None, "mapping": None, "detected_mapping": None, "movements": movements, "warnings": [],
            "closing_balance_cents": bal_cents, "closing_balance_date": bal_date, "iban": iban}


# ---------------------------------------------------------------- CBI RH

def _cbi_date(text: str) -> str | None:
    text = text.strip()
    if len(text) != 6 or not text.isdigit():
        return None
    try:
        return date(2000 + int(text[4:6]), int(text[2:4]), int(text[0:2])).isoformat()
    except ValueError:
        return None


def _cbi_amount(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    if "," in text:
        return parse_amount_any(text)
    if text.isdigit():
        return int(text)  # 2 decimali impliciti
    return None


def parse_cbi(data: bytes) -> dict:
    """Rendicontazione movimenti CBI (record 61 saldo iniziale, 62 movimento, 63 dettaglio, 64 saldo finale).

    Il tracciato a larghezza fissa può variare leggermente da banca a banca: se un file non viene
    letto correttamente, controlla le posizioni qui sotto con il tracciato fornito dalla tua banca.
    """
    text = _decode(data)
    lines = [l.rstrip("\r\n") for l in text.splitlines() if l.strip()]
    movements, warnings = [], []
    bal_cents, bal_date = None, None
    current = None
    for line in lines:
        line = line.ljust(120)
        rec = line[1:3]
        if rec == "62":
            if current:
                movements.append(current)
            value_date = _cbi_date(line[13:19])
            book_date = _cbi_date(line[19:25])
            sign = line[25:26]
            amount = _cbi_amount(line[26:41])
            if amount is None or not (book_date or value_date):
                current = None
                warnings.append("Una riga movimento CBI non è stata letta: controlla il tracciato.")
                continue
            current = {
                "date": book_date or value_date, "value_date": value_date or book_date,
                "description": _clean_desc(line[86:120]),
                "amount_cents": -abs(amount) if sign == "D" else abs(amount),
                "reference": line[61:77].strip(),
                "abi_code": line[41:43].strip(),
            }
        elif rec == "63" and current:
            current["description"] = _clean_desc(current["description"], line[13:120])
        elif rec == "64":
            if current:
                movements.append(current)
                current = None
            d = _cbi_date(line[16:22])
            amount = _cbi_amount(line[23:38])
            if d and amount is not None:
                bal_cents = -abs(amount) if line[22:23] == "D" else abs(amount)
                bal_date = d
    if current:
        movements.append(current)
    for m in movements:
        m["description"] = m["description"] or f"Movimento causale ABI {m.pop('abi_code', '')}".strip()
        m.pop("abi_code", None)
    if not movements:
        raise StatementError("Nessun movimento trovato nel file CBI (record 62).")
    return {"headers": None, "mapping": None, "detected_mapping": None, "movements": movements,
            "warnings": warnings, "closing_balance_cents": bal_cents, "closing_balance_date": bal_date, "iban": None}


# ---------------------------------------------------------------- ingresso unico

def detect_format(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    head = data[:4000].lstrip(b"\xef\xbb\xbf \r\n\t")
    if data[:5] == b"%PDF-" or name.endswith(".pdf"):
        return "pdf"
    if data[:2] == b"PK" or name.endswith(".xlsx"):
        return "xlsx"
    if name.endswith(".xls") and data[:4] == b"\xd0\xcf\x11\xe0":
        raise StatementError("Il formato .xls (Excel vecchio) non è supportato: salvalo come .xlsx o CSV.")
    if head.startswith(b"<") or b"<Document" in head:
        return "camt"
    first = _decode(data[:2000]).splitlines()[:3]
    if first and any(len(l) >= 100 and l[1:3] in {"RH", "61", "62"} for l in first):
        return "cbi"
    return "csv"


FORMAT_LABELS = {"csv": "CSV", "xlsx": "Excel", "camt": "CAMT.053 (XML)", "cbi": "CBI", "pdf": "PDF"}


def parse_statement(filename: str, data: bytes, mapping: dict | None = None, card: bool = False) -> dict:
    if not data:
        raise StatementError("Il file è vuoto.")
    fmt = detect_format(filename, data)
    if fmt == "pdf":
        from .statement_pdf import parse_pdf
        result = parse_pdf(data, card)
    elif fmt == "xlsx":
        result = parse_table(_table_from_xlsx(data), mapping)
    elif fmt == "camt":
        result = parse_camt(data)
    elif fmt == "cbi":
        result = parse_cbi(data)
    else:
        result = parse_table(_table_from_csv(data), mapping)
    return finish(result, fmt)


def finish(result: dict, fmt: str) -> dict:
    result["format"] = fmt
    result["format_label"] = FORMAT_LABELS[fmt]
    result.setdefault("needs_mapping", False)
    if not result["movements"]:
        if result["needs_mapping"]:
            result["date_from"] = result["date_to"] = None
            return result
        raise StatementError("Nel file non ci sono movimenti da importare." if fmt != "pdf" else
                             "Nel PDF non ho trovato righe di movimenti (data … importo). Prova con il CSV o l'Excel dell'home banking.")
    dates = [m["date"] for m in result["movements"]]
    result["date_from"], result["date_to"] = min(dates), max(dates)
    return result
