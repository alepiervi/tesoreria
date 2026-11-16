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


DESC_HEADERS = {"descrizione", "causale", "dettaglio", "dettagli", "operazione", "operazioni", "descrizione operazione",
                "descrizione operazioni", "causale descrizione", "descrizione movimento"}
OPENING_WORDS = ("saldo iniziale", "saldo precedente", "saldo contabile iniziale", "saldo al", "saldo a credito", "saldo a debito",
                 "saldo inizio", "saldo contabile al", "saldo riportato")
MARKERS = {"CR", "DB", "EUR", "€", "D", "C", "+", "-"}


def _header_line(line) -> dict:
    """Colonne lette da una riga di intestazione (centro e bordi di Dare, Avere, Saldo, Descrizione)."""
    texts = [w["text"].lower().strip(":.") for w in line]
    if any(t in ("totale", "totali", "iniziale", "finale") for t in texts):
        return {}  # riquadro dei saldi o riga dei totali, non l'intestazione dei movimenti
    cols = {}
    i = 0
    while i < len(texts):
        pair = f"{texts[i]} {texts[i + 1]}" if i + 1 < len(texts) else None
        matched = False
        for key, names in (("debit", DEBIT_HEADERS), ("credit", CREDIT_HEADERS), ("balance", BALANCE_HEADERS), ("desc", DESC_HEADERS)):
            if key in cols:
                continue
            if pair and pair in names:
                cols[key] = (line[i]["x0"], line[i + 1]["x1"])
                i += 1
                matched = True
                break
            if texts[i] in names:
                cols[key] = (line[i]["x0"], line[i]["x1"])
                matched = True
                break
        i += 1
    return cols if ("debit" in cols and "credit" in cols) else {}


def _header_columns(lines) -> dict:
    for line in lines:
        cols = _header_line(line)
        if cols:
            return cols
    return {}


def _amount_sign(text: str) -> int | None:
    t = text.strip()
    if t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")")):
        return -1
    return None


def _center(c):
    return (c["x0"] + c["x1"]) / 2 if isinstance(c, dict) else (c[0] + c[1]) / 2


def _amount_zone(cols: dict) -> tuple[float, float] | None:
    if not cols:
        return None
    keys = [cols[k] for k in ("debit", "credit", "balance") if k in cols]
    left, right = min(k[0] for k in keys) - 12, max(k[1] for k in keys) + 70
    if "desc" in cols:
        d0 = cols["desc"][0]
        if d0 > max(cols["debit"][1], cols["credit"][1]):
            right = min(right, d0 - 2)  # descrizione a destra degli importi (es. Dare | Avere | Descrizione)
    return left, right


def _is_amount(w) -> bool:
    return bool(AMOUNT_RX.match(w["text"].replace("€", "")))


def _split_line(line, cols: dict):
    """Separa una riga in: importi (nelle colonne degli importi), marcatori CR/DB e testo."""
    zone = _amount_zone(cols)
    if zone:
        amounts = [w for w in line if _is_amount(w) and w["x1"] >= zone[0] and w["x0"] <= zone[1]]
        ids = {id(w) for w in amounts}
        suffix = ""
        text = []
        for w in line:
            if id(w) in ids:
                continue
            if w["text"].upper() in MARKERS and zone[0] <= w["x0"] <= zone[1] + 20:
                suffix = suffix or w["text"].upper()
                continue
            text.append(w)
        return amounts, suffix, text
    # senza intestazione: importi in fondo alla riga, oppure subito dopo le date
    tail = list(line)
    suffix = ""
    while tail and tail[-1]["text"].upper() in MARKERS:
        suffix = suffix or tail[-1]["text"].upper()
        tail.pop()
    amounts = []
    while tail and _is_amount(tail[-1]):
        amounts.insert(0, tail.pop())
    if amounts:
        return amounts, suffix, tail
    head = []
    rest = list(line)
    while rest and DATE_RX.match(rest[0]["text"]):
        head.append(rest.pop(0))
    while head and rest and _is_amount(rest[0]):
        amounts.append(rest.pop(0))
        while rest and rest[0]["text"].upper() in MARKERS:
            suffix = suffix or rest.pop(0)["text"].upper()
    return (amounts, suffix, head + rest) if amounts else ([], "", list(line))


def _column_sign(w, cols: dict) -> int | None:
    if not cols:
        return None
    x = _center(w)
    dist = {k: min(abs(x - _center(cols[k])), abs(w["x1"] - cols[k][1])) for k in ("debit", "credit") if k in cols}
    return -1 if dist["debit"] < dist["credit"] else 1


def _movement_amount(amounts, cols: dict):
    if cols.get("balance"):
        bx = cols["balance"]
        others = [a for a in amounts if min(abs(_center(a) - _center(bx)), abs(a["x1"] - bx[1])) >
                  min(abs(_center(a) - _center(cols[k])) for k in ("debit", "credit"))]
        if others:
            return others[0]
    return amounts[0]


def _balance_value(amt_word, low: str, suffix: str, cols: dict, card: bool) -> int | None:
    value = parse_amount_any(amt_word["text"])
    if value is None:
        return None
    if _amount_sign(amt_word["text"]) is not None:
        return value
    if card or "debito" in low or suffix in {"DB", "D"}:
        return -abs(value)
    if cols and not cols.get("balance") and _column_sign(amt_word, cols) == -1:
        return -abs(value)
    return abs(value)


def parse_pdf_text(pages_lines: list[list[list[dict]]], card: bool = False) -> dict:
    movements, warnings = [], []
    opening = closing = closing_date = None
    cols = {}
    guessed_signs = 0
    closing_locked = False
    last = None
    last_top = None
    last_date = None
    has_header = any(_header_line(line) for lines in pages_lines for line in lines)
    in_table = not has_header
    pending_labels = None
    for lines in pages_lines:
        last = None  # una nuova pagina non continua la descrizione (intestazioni e piè di pagina)
        cols = _header_columns(lines) or cols
        for line in lines:
            texts = [w["text"] for w in line]
            low = " ".join(texts).lower()
            if _header_line(line):
                last, in_table = None, True
                continue
            first = texts[0] if texts else ""
            all_amounts = [w for w in line if _is_amount(w)]
            # riquadro dei saldi su due righe: etichette sopra, importi sotto
            if pending_labels and all_amounts and not _has_words(line, all_amounts):
                for label, amt in _match_labels(pending_labels, all_amounts):
                    opening, closing, closing_locked = _apply_balance(
                        label, _balance_value(amt, label, "", {}, card), bool(movements), opening, closing, closing_locked)
                pending_labels = None
                continue
            pending_labels = None
            if not all_amounts and "saldo" in low and not DATE_RX.match(first):
                labels = _labels_only(line)
                if labels:
                    pending_labels = labels
                    continue
            if not DATE_RX.match(first) and _section_end(low):
                last, in_table = None, False  # riassunto scalare, prospetti e documenti di sintesi: non sono movimenti
                continue
            body = " ".join(t for t in texts if not DATE_RX.match(t)).lower().lstrip("*-. ")
            is_balance = all_amounts and (body.startswith(("saldo", "nuovo saldo", "totale da pagare", "importo da addebitare"))
                                          or (not DATE_RX.match(first) and "saldo" in low))
            if is_balance:
                if in_table or any(w in low for w in ("iniziale", "finale", "precedente")):
                    d = next((parse_date_any(t) for t in texts if DATE_RX.match(t)), None)
                    for label, amt in _labelled_amounts(line):
                        before = closing
                        opening, closing, closing_locked = _apply_balance(
                            label, _balance_value(amt, label, "", cols, card), bool(movements), opening, closing, closing_locked)
                        if closing != before:
                            closing_date = d or last_date
                last = None
                continue
            if not in_table:
                continue
            amounts, suffix, text_words = _split_line(line, cols)
            if not DATE_RX.match(first):
                # continuazione della descrizione del movimento precedente (righe vicine, senza importi)
                near = last_top is not None and line[0]["top"] - last_top < 22
                if last is not None and near and not amounts and not any(w in low for w in SKIP_WORDS) and len(low) < 200:
                    last["description"] = _clean_desc(last["description"], " ".join(w["text"] for w in text_words))
                    last_top = line[0]["top"]
                else:
                    last = None
                continue
            if not amounts:
                last = None
                continue
            d = parse_date_any(first)
            if not d:
                continue
            rest = [w for w in text_words if w is not line[0]]
            vd = None
            if rest and DATE_RX.match(rest[0]["text"]):
                vd = parse_date_any(rest[0]["text"])
                rest = rest[1:]
            desc = " ".join(w["text"] for w in rest).strip()
            if desc.lower().startswith(("saldo", "totale", "riporto", "a riportare")) or len(re.findall(r"[A-Za-zÀ-ÿ]", desc)) < 3:
                last = None  # saldo, totale o riga di soli numeri (es. riassunto scalare): non è un movimento
                continue
            amt_word = _movement_amount(amounts, cols) if cols else amounts[0]
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
            if sign is None:
                sign = _column_sign(amt_word, cols)
            if sign is None:
                d_low = desc.lower()
                if card:
                    sign = 1 if any(w in d_low for w in CARD_CREDIT_WORDS) else -1
                else:
                    guessed_signs += 1
                    sign = 1 if any(w in d_low for w in CREDIT_WORDS) else -1
            last = {"date": d, "value_date": vd or d, "description": desc, "amount_cents": sign * value, "reference": None}
            last_top = line[0]["top"]
            last_date = d
            movements.append(last)
    if guessed_signs:
        warnings.append(f"Per {guessed_signs} movimenti il segno (entrata o uscita) è stato dedotto dalla descrizione: "
                        "controlla l'anteprima e, se serve, usa «Inverti i segni».")
    result = {"headers": None, "mapping": None, "detected_mapping": None, "movements": movements, "warnings": warnings,
              "opening_balance_cents": opening, "closing_balance_cents": closing, "closing_balance_date": closing_date,
              "iban": _find_iban(pages_lines)}
    result["balance_check"] = balance_check(result)
    return result


SECTION_END = ("scalare", "riassunto", "documento di sintesi", "prospetto", "numeri debitori", "numeri creditori",
               "calcolo degli interessi", "conteggio interessi")
OPEN_LABELS = ("iniziale", "precedente", "riportato", "inizio")
CLOSE_LABELS = ("finale", "nuovo saldo", "saldo contabile", "saldo a debito", "saldo da addebitare", "da addebitare", "da pagare")


def _section_end(low: str) -> bool:
    return any(w in low for w in SECTION_END) or ("giorni" in low and "numeri" in low) or low.startswith("riepilogo")


def _has_words(line, amounts) -> bool:
    ids = {id(a) for a in amounts}
    return any(re.search(r"[A-Za-zÀ-ÿ]{3}", w["text"]) for w in line if id(w) not in ids)


def _labelled_amounts(line) -> list[tuple[str, dict]]:
    """Ogni importo della riga con il testo che lo precede (es. «saldo iniziale» 1.000,00 «saldo finale» 2.000,00)."""
    out, label = [], []
    for w in line:
        if _is_amount(w):
            out.append((" ".join(label).lower(), w))
            label = []
        elif not DATE_RX.match(w["text"]):
            label.append(w["text"])
    if len(out) > 1 and not out[-1][0]:
        out = out[:-1] + [(out[0][0], out[-1][1])]  # «saldo al 31/03 … 1.000,00 CR»: un solo importo con il suo testo
    return [(lbl or " ".join(w["text"] for w in line).lower(), w) for lbl, w in out]


def _labels_only(line) -> list[tuple[str, float]]:
    """Etichette di un riquadro dei saldi (senza importi): testo e posizione orizzontale."""
    groups, cur = [], []
    for w in line:
        if cur and w["x0"] - cur[-1]["x1"] > 12:
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    labels = [(" ".join(w["text"] for w in g).lower(), (g[0]["x0"] + g[-1]["x1"]) / 2) for g in groups]
    return labels if sum(1 for t, _ in labels if "saldo" in t) and len(labels) >= 2 else []


def _match_labels(labels, amounts) -> list[tuple[str, dict]]:
    return [(min(labels, key=lambda l: abs(l[1] - _center(a)))[0], a) for a in amounts]


def _apply_balance(label: str, value, has_movements: bool, opening, closing, locked: bool):
    if value is None or any(w in label for w in ("liquido", "disponibile", "per valuta", "medio")):
        return opening, closing, locked
    if any(w in label for w in OPEN_LABELS) and "finale" not in label:
        return (value if opening is None else opening), closing, locked
    if any(w in label for w in CLOSE_LABELS) or ("saldo al" in label and has_movements):
        return opening, value, True
    if "saldo al" in label and not has_movements and opening is None:
        return value, closing, locked
    if "saldo" in label and has_movements and not locked and not any(w in label for w in ("riportare", "riporto")):
        return opening, value, locked
    return opening, closing, locked


def balance_check(result: dict) -> str | None:
    """'ok' se saldo iniziale + movimenti = saldo finale, 'mismatch' se non torna, None se mancano i saldi."""
    o, c = result.get("opening_balance_cents"), result.get("closing_balance_cents")
    if o is None or c is None or not result.get("movements"):
        return None
    return "ok" if o + sum(m["amount_cents"] for m in result["movements"]) == c else "mismatch"


def weak_descriptions(result: dict) -> bool:
    ms = result.get("movements") or []
    return bool(ms) and sum(1 for m in ms if len(m["description"]) < 4 or m["description"] == "Movimento") > len(ms) * 0.3


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
    "\"descrizione\": \"testo completo della riga\", \"importo\": numero}}], \"saldo_iniziale\": numero o null, \"saldo_finale\": numero o null, "
    "\"data_saldo\": \"AAAA-MM-GG\" o null}}. La descrizione è tutto il testo del movimento, anche se va a capo su più righe. "
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
    def cents(v):
        return int(round(float(v) * 100)) if isinstance(v, (int, float)) else None
    out = {"headers": None, "mapping": None, "detected_mapping": None, "movements": movements,
           "warnings": ["Letto con l'intelligenza artificiale: controlla con attenzione l'anteprima prima di importare."],
           "opening_balance_cents": cents(result.get("saldo_iniziale")), "closing_balance_cents": cents(result.get("saldo_finale")),
           "closing_balance_date": parse_date_any(result.get("data_saldo")), "iban": None}
    out["balance_check"] = balance_check(out)
    return out
