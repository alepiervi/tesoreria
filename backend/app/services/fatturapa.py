"""Lettura delle fatture elettroniche in formato FatturaPA (XML dell'Agenzia delle Entrate).

Legge sia il file .xml sia la versione firmata .p7m (busta CAdES, anche codificata in base64).
"""
import base64
import binascii

from defusedxml import ElementTree as ET

from ..utils import to_cents


class FatturaPAError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _find(node, path: str):
    """Cerca un percorso tipo 'A/B/C' ignorando i namespace."""
    current = [node]
    for part in path.split("/"):
        nxt = []
        for n in current:
            nxt.extend(child for child in n if _local(child.tag) == part)
        if not nxt:
            return []
        current = nxt
    return current


def _text(node, path: str, default: str = "") -> str:
    found = _find(node, path)
    if not found or found[0].text is None:
        return default
    return found[0].text.strip()


def _party(node) -> dict:
    name = _text(node, "DatiAnagrafici/Anagrafica/Denominazione")
    if not name:
        name = " ".join(filter(None, [_text(node, "DatiAnagrafici/Anagrafica/Nome"),
                                      _text(node, "DatiAnagrafici/Anagrafica/Cognome")]))
    return {
        "name": name,
        "vat": _text(node, "DatiAnagrafici/IdFiscaleIVA/IdCodice"),
        "country": _text(node, "DatiAnagrafici/IdFiscaleIVA/IdPaese", "IT"),
        "tax_code": _text(node, "DatiAnagrafici/CodiceFiscale"),
    }


def unwrap_p7m(data: bytes) -> bytes:
    """Estrae l'XML da una fattura firmata .p7m. Se il file non è firmato lo restituisce invariato.

    La firma non viene verificata: serve solo a leggere il contenuto (come fa il cassetto fiscale).
    """
    raw = data.strip()
    if raw[:2] == b"MI":  # .p7m salvato in base64
        try:
            raw = base64.b64decode(b"".join(raw.split()), validate=False)
        except (binascii.Error, ValueError):
            return data
    if raw[:1] != b"\x30":
        return data
    from asn1crypto import cms
    try:
        info = cms.ContentInfo.load(raw)
        content = info["content"]["encap_content_info"]["content"].native
    except Exception:
        raise FatturaPAError("Il file .p7m non si apre: prova a scaricare la versione .xml della fattura.")
    if not content:
        raise FatturaPAError("Il file .p7m non contiene la fattura (firma senza contenuto).")
    return content


def parse_fatturapa(data: bytes) -> list[dict]:
    """Restituisce un elenco di documenti (un file può contenere più fatture)."""
    data = unwrap_p7m(data.lstrip(b"\xef\xbb\xbf \r\n\t"))
    data = data.lstrip(b"\xef\xbb\xbf \r\n\t")
    try:
        root = ET.fromstring(data)
    except Exception:
        raise FatturaPAError("Il file non è un XML valido.")
    if _local(root.tag) != "FatturaElettronica":
        raise FatturaPAError("Il file non è una fattura elettronica FatturaPA.")

    header = _find(root, "FatturaElettronicaHeader")
    if not header:
        raise FatturaPAError("Intestazione della fattura mancante.")
    seller_nodes = _find(header[0], "CedentePrestatore")
    buyer_nodes = _find(header[0], "CessionarioCommittente")
    if not seller_nodes or not buyer_nodes:
        raise FatturaPAError("Mancano i dati di chi emette o di chi riceve la fattura.")
    seller = _party(seller_nodes[0])
    buyer = _party(buyer_nodes[0])

    documents = []
    for body in _find(root, "FatturaElettronicaBody"):
        gen = _find(body, "DatiGenerali/DatiGeneraliDocumento")
        if not gen:
            continue
        gen = gen[0]
        vat_cents = taxable_cents = 0
        split_payment = False
        breakdown = []
        for r in _find(body, "DatiBeniServizi/DatiRiepilogo"):
            t_cents = to_cents(_text(r, "ImponibileImporto", "0"))
            v_cents = to_cents(_text(r, "Imposta", "0"))
            taxable_cents += t_cents
            vat_cents += v_cents
            split_payment = split_payment or _text(r, "EsigibilitaIVA") == "S"
            breakdown.append({"rate": float(_text(r, "AliquotaIVA", "0") or 0), "nature": _text(r, "Natura"),
                              "taxable_cents": t_cents, "vat_cents": v_cents})
        withholding = sum(to_cents(_text(w, "ImportoRitenuta", "0")) for w in _find(gen, "DatiRitenuta"))
        stamp = to_cents(_text(gen, "DatiBollo/ImportoBollo", "0"))
        total = _text(gen, "ImportoTotaleDocumento")
        if total:
            total_cents = to_cents(total)
        else:
            total_cents = 0
            for r in _find(body, "DatiBeniServizi/DatiRiepilogo"):
                total_cents += to_cents(_text(r, "ImponibileImporto", "0")) + to_cents(_text(r, "Imposta", "0"))
        installments = []
        iban = ""
        for p in _find(body, "DatiPagamento/DettaglioPagamento"):
            installments.append({
                "due_date": _text(p, "DataScadenzaPagamento"),
                "amount_cents": to_cents(_text(p, "ImportoPagamento", "0")),
            })
            iban = iban or _text(p, "IBAN")
        doc_type = _text(gen, "TipoDocumento", "TD01")
        # Le note di credito (TD04) riducono il dovuto
        sign = -1 if doc_type == "TD04" else 1
        documents.append({
            "number": _text(gen, "Numero"),
            "date": _text(gen, "Data"),
            "doc_type": doc_type,
            "total_cents": sign * total_cents,
            "taxable_cents": sign * taxable_cents,
            "vat_cents": sign * vat_cents,
            "split_payment": split_payment,
            "vat_breakdown": [{**b, "taxable_cents": sign * b["taxable_cents"], "vat_cents": sign * b["vat_cents"]}
                              for b in breakdown],
            "withholding_cents": sign * withholding,
            "stamp_cents": stamp,
            "installments": installments,
            "iban": iban,
            "description": _text(body, "DatiBeniServizi/DettaglioLinee/Descrizione"),
            "seller": seller,
            "buyer": buyer,
        })
    if not documents:
        raise FatturaPAError("Nessuna fattura trovata nel file.")
    return documents
