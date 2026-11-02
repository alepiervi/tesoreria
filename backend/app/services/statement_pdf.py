"""Lettura degli estratti conto in PDF (conti correnti e carte di credito).

I PDF delle banche non hanno un formato standard: qui si leggono le righe che iniziano con una data e
finiscono con un importo. Il segno si capisce, nell'ordine:
1. dal segno scritto nell'importo (-123,45 · 123,45- · 123,45 CR/DB);
2. dalla colonna in cui si trova l'importo, se la pagina ha le colonne Dare/Avere (Addebiti/Accrediti, Uscite/Entrate);
3. dalle parole della descrizione (accredito, bonifico a vostro favore, rimborso…).
Per le carte di credito gli importi sono spese, salvo rimborsi e pagamenti del saldo.
Le righe senza data che seguono un movimento ne completano la descrizione.
I PDF scansionati (immagini) non contengono testo: in quel caso, con l'assistente collegato a Claude, il file
viene letto dall'intelligenza artificiale; altrimenti si chiede il CSV/Excel all'home banking.
"""
import io
import re

from .statements import StatementError, _clean_desc, parse_amount_any, parse_date_any

DATE_RX = re.compile(r"^(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})$")
AMOUNT_RX = re.compile(r"^[-+(]?(?:\d{1,3}(?:[.']\d{3})+|\d+),\d{2}\)?-?$")
DEBIT_HEADERS = {"dare", "addebiti", "addebito", "uscite", "uscita", "importo addebiti", "pagamenti", "spese"}
CREDIT_HEADERS = {"avere", "accrediti", "accredito", "entrate", "entrata", "importo accrediti", "versamenti"}
BALANCE_HEADERS = {"saldo", "saldo progressivo", "saldo contabile"}
SKIP_WORDS = ("saldo iniziale", "saldo precedente", "saldo finale", "saldo contabile", "saldo disponibile", "totale",
              "riporto", "pagina", "segue", "a riportare", "nuovo saldo", "saldo a debito", "saldo al")
CLOSING_WORDS = ("saldo finale", "saldo contabile finale", "nuovo saldo", "saldo a debito", "saldo da addebitare",
                 "importo da addebitare", "totale da pagare", "saldo al")
CREDIT_WORDS = ("accredito", "accr.", "a vostro favore", "a vs favore", "a vs. favore", "bonifico da", "bonifico in entrata",
                "versamento", "giroconto da", "rimborso", "storno", "incasso", "stipendio da", "interessi creditori", "ricevuto")
CARD_CREDIT_WORDS = ("rimborso", "storno", "accredito", "pagamento saldo", "pagamento ricevuto", "addebito su c/c", "addebito in c/c",
                     "vostro pagamento", "saldo precedente pagato", "rid")


def _lines(page):
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=2)
    rows: list[list] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= 3:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def _header_columns(lines) -> dict:
    cols = {}
    for line in lines:
        texts = [w["text"].lower().strip(":") for w in line]
        joined = " ".join(texts)
        for i, t in enumerate(texts):
            has_next = i + 1 < len(texts)
            pair = f"{t} {texts[i + 1]}" if has_next else None
            for key, names in (("debit", DEBIT_HEADERS), ("credit", CREDIT_HEADERS), ("balance", BALANCE_HEADERS)):
                if key in cols:
                    continue
                if pair and pair in names:
                    cols[key] = (line[i]["x0"] + line[i + 1]["x1"]) / 2
                elif t in names:
                    cols[key] = (line[i]["x0"] + line[i]["x1"]) / 2
        if "debit" in cols and "credit" in cols:
            if "data" in joined or "descrizione" in joined or "operazione" in joined:
                return cols
    return cols if ("debit" in cols and "credit" in cols) else {}


def _amount_sign(text: str) -> int | None:
    t = text.strip()
    if t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")")):
        return -1
    return None


def parse_pdf_text(pages_lines: list[list[list[dict]]], card: bool = False) -> dict:
    movements, warnings = [], []
    closing = closing_date = None
    cols = {}
    guessed_signs = 0
    last = None
    last_date = None
    for lines in pages_lines:
        cols = _header_columns(lines) or cols
        for line in lines:
            texts = [w["text"] for w in line]
            low = " ".join(texts).lower()
            # importi in fondo alla riga (eventualmente seguiti da CR/DB/EUR)
            tail = list(line)
            suffix = ""
            while tail and tail[-1]["text"].upper() in {"CR", "DB", "EUR", "€", "D", "C", "+", "-"}:
                suffix = tail[-1]["text"].upper() if not suffix else suffix
                tail.pop()
            amounts = []
            while tail and AMOUNT_RX.match(tail[-1]["text"].replace("€", "")):
                amounts.insert(0, tail.pop())
            # saldo finale
            if amounts and any(w in low for w in CLOSING_WORDS):
                closing = parse_amount_any(amounts[-1]["text"])
                if closing is not None and _amount_sign(amounts[-1]["text"]) is None and (card or "debito" in low or suffix == "DB"):
                    closing = -abs(closing)
                d = next((parse_date_any(t) for t in texts if DATE_RX.match(t)), None)
                closing_date = d or last_date
                continue
            first = texts[0] if texts else ""
            if not DATE_RX.match(first):
                # continuazione della descrizione del movimento precedente
                if last is not None and not amounts and not any(w in low for w in SKIP_WORDS) and len(low) < 120:
                    last["description"] = _clean_desc(last["description"], " ".join(texts))
                continue
            if not amounts:
                last = None
                continue
            d = parse_date_any(first)
            if not d:
                continue
            rest = tail[1:]
            vd = None
            if rest and DATE_RX.match(rest[0]["text"]):
                vd = parse_date_any(rest[0]["text"])
                rest = rest[1:]
            desc = " ".join(w["text"] for w in rest).strip() or "Movimento"
            if desc.lower().startswith(("saldo", "totale", "riporto", "a riportare")):
                last = None  # riga di saldo o di totale, non un movimento
                continue
            # con più importi sulla riga il primo è il movimento, l'ultimo di solito è il saldo progressivo
            amt_word = amounts[0]
            value = parse_amount_any(amt_word["text"])
            if value is None or value == 0:
                continue
            value = abs(value)
            sign = _amount_sign(amt_word["text"])
            if card and sign is not None:
                sign = -sign  # sull'estratto della carta il "meno" indica un accredito (rimborso o pagamento del saldo)
            if sign is None and suffix in {"CR", "C", "+"}:
                sign = 1
            elif sign is None and suffix in {"DB", "D"}:
                sign = -1
            if sign is None and cols.get("debit") and cols.get("credit"):
                x = (amt_word["x0"] + amt_word["x1"]) / 2
                sign = -1 if abs(x - cols["debit"]) < abs(x - cols["credit"]) else 1
            if sign is None:
                d_low = desc.lower()
                if card:
                    sign = 1 if any(w in d_low for w in CARD_CREDIT_WORDS) else -1
                else:
                    guessed_signs += 1
                    sign = 1 if any(w in d_low for w in CREDIT_WORDS) else -1
            last = {"date": d, "value_date": vd or d, "description": desc, "amount_cents": sign * value, "reference": None}
            last_date = d
            movements.append(last)
    if guessed_signs:
        warnings.append(f"Per {guessed_signs} movimenti il segno (entrata o uscita) è stato dedotto dalla descrizione: "
                        "controlla l'anteprima e, se serve, usa «Inverti i segni».")
    return {"headers": None, "mapping": None, "detected_mapping": None, "movements": movements, "warnings": warnings,
            "closing_balance_cents": closing, "closing_balance_date": closing_date, "iban": _find_iban(pages_lines)}


def _find_iban(pages_lines) -> str | None:
    for lines in pages_lines[:1]:
        text = " ".join(w["text"] for line in lines for w in line)
        m = re.search(r"\bIT\s?\d{2}\s?[A-Z](?:\s?[0-9A-Z]){22}\b", text)
        if m:
            return re.sub(r"\s", "", m.group(0))
    return None


def parse_pdf(data: bytes, card: bool = False) -> dict:
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover
        raise StatementError("Lettura dei PDF non disponibile sul server: installa pdfplumber.")
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > 60:
                raise StatementError("Il PDF ha troppe pagine (massimo 60): caricalo un mese alla volta.")
            pages = [_lines(p) for p in pdf.pages]
    except StatementError:
        raise
    except Exception:
        raise StatementError("Il PDF non si apre: potrebbe essere protetto da password o danneggiato.")
    if not any(pages):
        raise StatementError("Il PDF non contiene testo (è una scansione).")
    return parse_pdf_text(pages, card)


AI_PROMPT = (
    "È l'estratto conto di {kind}. Rispondi SOLO con JSON: {{\"movimenti\": [{{\"data\": \"AAAA-MM-GG\", \"valuta\": \"AAAA-MM-GG\", "
    "\"descrizione\": \"testo\", \"importo\": numero}}], \"saldo_finale\": numero o null, \"data_saldo\": \"AAAA-MM-GG\" o null}}. "
    "importo negativo per le uscite (addebiti, spese) e positivo per le entrate (accrediti, rimborsi). {extra}"
    "Non includere saldi iniziali, finali, totali e riporti tra i movimenti."
)


async def parse_pdf_with_ai(data: bytes, card: bool) -> dict | None:
    from ..integrations.ai import get_ai
    ai = get_ai()
    if not ai:
        return None
    prompt = AI_PROMPT.format(kind="una carta di credito" if card else "un conto corrente",
                              extra="Per la carta il saldo finale è il debito da addebitare, con segno negativo. " if card else "")
    result = await ai.read_document(data, "application/pdf", prompt)
    if not result or not result.get("movimenti"):
        return None
    movements = []
    for m in result["movimenti"]:
        d = parse_date_any(m.get("data"))
        try:
            cents = int(round(float(m.get("importo")) * 100))
        except (TypeError, ValueError):
            continue
        if d and cents:
            movements.append({"date": d, "value_date": parse_date_any(m.get("valuta")) or d,
                              "description": str(m.get("descrizione") or "Movimento")[:300], "amount_cents": cents, "reference": None})
    bal = result.get("saldo_finale")
    return {"headers": None, "mapping": None, "detected_mapping": None, "movements": movements,
            "warnings": ["Letto con l'intelligenza artificiale: controlla con attenzione l'anteprima prima di importare."],
            "closing_balance_cents": int(round(float(bal) * 100)) if isinstance(bal, (int, float)) else None,
            "closing_balance_date": parse_date_any(result.get("data_saldo")), "iban": None}
