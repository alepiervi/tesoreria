"""Assistente: risponde alle domande sui dati, legge gli scontrini, aiuta nella riconciliazione.

Provider:
- "demo": nessun servizio esterno. Riconosce le domande più comuni (saldi, spese per categoria,
  crediti, scadenze, previsione, IVA) e risponde con i dati veri del programma.
- "anthropic": usa Claude tramite API (ANTHROPIC_API_KEY). Capisce qualsiasi domanda e legge
  le foto degli scontrini. I dati necessari alla risposta vengono inviati al servizio: va indicato
  nell'informativa privacy.
- "none": assistente disattivato.

L'assistente usa solo strumenti di SOLA LETTURA e vede solo le aziende dell'utente.
"""
import base64
import json
import logging
import re

import httpx

from ..config import settings
from ..services.assistant_tools import TOOL_SPECS, Tools, anthropic_tools, period_from_text
from ..services.categories import CATEGORIES
from ..utils import new_id, today

logger = logging.getLogger("tesoreria.ai")
API_URL = "https://api.anthropic.com/v1/messages"


def _fmt(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}{s} €"


SYSTEM = """Sei l'assistente di tesoreria di un gruppo di aziende italiane. Oggi è {today}.
Rispondi in italiano, in modo breve e concreto, con gli importi in euro nel formato 1.234,56 €.
Usa SEMPRE gli strumenti per leggere i dati: non inventare numeri. Se i dati non bastano, dillo.
Se la domanda riguarda una sola azienda, passa il suo nome nel parametro "azienda".
Non dare consulenza fiscale definitiva: per IVA e imposte ricorda che sono stime da verificare con il commercialista.
Aziende visibili: {companies}."""


class AIProvider:
    name = "base"

    async def ask(self, tools: Tools, question: str, history: list[dict]) -> dict:
        raise NotImplementedError

    async def read_receipt(self, data: bytes, mime: str) -> dict | None:
        return None

    async def read_document(self, data: bytes, mime: str, prompt: str) -> dict | None:
        """Legge un PDF o una foto e restituisce il JSON richiesto dal prompt (None se non disponibile)."""
        return None

    async def suggest_match(self, tx: dict, items: list[dict]) -> dict | None:
        return None


# ---------------------------------------------------------------- demo

CATEGORY_WORDS = {
    "carburante": "Carburante e trasporti", "benzina": "Carburante e trasporti", "gasolio": "Carburante e trasporti",
    "trasport": "Carburante e trasporti", "stipend": "Personale", "personale": "Personale", "dipendent": "Personale",
    "affitt": "Affitti", "utenz": "Utenze", "energia": "Utenze", "luce": "Utenze", "telefon": "Utenze",
    "fornitor": "Fornitori", "commission": "Oneri bancari", "banca": "Oneri bancari", "software": "Software e servizi",
    "tasse": "Imposte e tasse", "imposte": "Imposte e tasse", "f24": "Imposte e tasse", "leasing": "Leasing e finanziamenti",
    "rate": "Leasing e finanziamenti", "incass": "Incassi clienti", "fatturato": "Incassi clienti",
}


class DemoAI(AIProvider):
    name = "demo"

    async def ask(self, tools: Tools, question: str, history: list[dict]) -> dict:
        q = question.lower()
        company = next((n for n in tools.names.values()
                        if any(tok in q for tok in re.findall(r"[a-zà-ù]{4,}", n.lower()) if tok not in {"azienda"})), None)
        used = []

        def num(text):
            m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?\s*(?:€|euro|mila|k)?", text)
            if not m:
                return 0
            v = float(m.group(1).replace(".", ""))
            return v * 1000 if re.search(r"\d\s*(mila|k)\b", text) else v

        if re.search(r"devono|credit|non (mi )?hanno pagato|da incassare|insolut", q):
            used.append("crediti")
            r = await tools.crediti(company, num(q) if re.search(r"più di|oltre|sopra", q) else 0,
                                    "scadut" in q or "ritard" in q)
            if not r["elenco"]:
                return {"answer": "Non risultano crediti aperti con questi criteri.", "tools": used}
            lines = [f"- {x['nome']} ({x['azienda']}): {_fmt(x['aperto'])}"
                     + (f", scaduto da {x['scaduto_da_giorni']} giorni" if x["scaduto_da_giorni"] else "") for x in r["elenco"][:10]]
            return {"answer": f"Crediti aperti per {_fmt(r['totale_aperto'])}, di cui scaduti {_fmt(r['totale_scaduto'])}:\n"
                              + "\n".join(lines), "tools": used}
        if re.search(r"debit|fornitor", q) and not re.search(r"scadenz|prossim|giorni|settiman", q):
            used.append("crediti")
            r = await tools.crediti(company, 0, "scadut" in q, "fornitori")
            lines = [f"- {x['nome']} ({x['azienda']}): {_fmt(x['aperto'])}" for x in r["elenco"][:10]]
            return {"answer": f"Debiti verso fornitori aperti: {_fmt(r['totale_aperto'])}.\n" + "\n".join(lines), "tools": used}
        if re.search(r"scadenz|pagare|da pagare|pagament", q):
            m = re.search(r"(\d+)\s*giorni", q)
            days = int(m.group(1)) if m else (7 if "settimana" in q else 30)
            used.append("scadenze")
            r = await tools.scadenze(days, company)
            if not r["scadenze"]:
                return {"answer": f"Nessuna scadenza nei prossimi {days} giorni.", "tools": used}
            lines = [f"- {x['data'][8:10]}/{x['data'][5:7]} · {x['azienda']} · {x['descrizione']}: "
                     f"{'+' if x['tipo'] == 'incasso' else '-'}{_fmt(x['importo'])}" + (" (scaduta)" if x["scaduta"] else "")
                     for x in r["scadenze"][:12]]
            return {"answer": f"Nei prossimi {days} giorni: da pagare {_fmt(r['totale_da_pagare'])}, da incassare "
                              f"{_fmt(r['totale_da_incassare'])}.\n" + "\n".join(lines), "tools": used}
        if re.search(r"previsio|cassa.*(prossim|settiman)|andrò in rosso|resterà|liquidità futura", q):
            used.append("previsione")
            r = await tools.previsione(company)
            return {"answer": f"Saldo attuale {_fmt(r['saldo_iniziale'])}. Il punto più basso nelle prossime 8 settimane è "
                              f"{_fmt(r['minimo'])} (settimana {r['settimana_minimo'] or 1})."
                              + (" Attenzione: il saldo va in negativo." if r["va_in_negativo"] else "")
                              + (f" Fidi ancora disponibili: {_fmt(r['fidi_disponibili'])}." if r["fidi_disponibili"] else ""),
                    "tools": used}
        if re.search(r"salute|allerta|crisi|indic|dscr|sostenibil|semafor|come sta", q):
            used.append("salute_azienda")
            r = await tools.salute_azienda(company)
            if not r["aziende"]:
                return {"answer": "Per vedere la salute dell'azienda serve l'accesso alla contabilità.", "tools": used}
            icon = {"verde": "🟢", "giallo": "🟡", "rosso": "🔴", "grigio": "⚪"}
            parts = []
            for a in r["aziende"]:
                bad = [s for s in a["segnali"] if s["stato"] != "verde"]
                parts.append(f"{icon[a['stato_generale']]} {a['azienda']}: " + ("nessun segnale di allerta." if not bad else
                             "; ".join(f"{s['titolo'].lower()} ({s['dettaglio']})" for s in bad)))
            return {"answer": "\n".join(parts) + "\nDettagli e indici nella pagina «Salute dell'azienda».", "tools": used}
        if re.search(r"\biva\b", q):
            used.append("iva")
            r = await tools.iva(company)
            lines = []
            for a in r["stima_iva"]:
                for p in a["periodi"]:
                    if p["da_versare"]:
                        lines.append(f"- {a['azienda']}, {p['periodo']}: {_fmt(p['da_versare'])} entro il "
                                     f"{p['scadenza'][8:10]}/{p['scadenza'][5:7]}")
            return {"answer": ("IVA stimata da versare:\n" + "\n".join(lines) if lines else "Al momento non risulta IVA da versare.")
                              + "\nÈ una stima dalle fatture registrate: verificala con il commercialista.", "tools": used}
        if re.search(r"saldo|saldi|liquidit|quanti soldi|in banca|disponibil", q):
            used.append("saldi")
            r = await tools.saldi(company)
            lines = [f"- {x['azienda']} · {x['banca']} {x['conto']}: {_fmt(x['saldo'])}" for x in r["conti"]]
            return {"answer": f"Liquidità totale: {_fmt(r['totale'])}.\n" + "\n".join(lines), "tools": used}
        if re.search(r"spes|speso|costi|uscit|incassat|entrat|fatturat|guadagn", q):
            cat = next((c for c in CATEGORIES if c.lower() in q), None) or \
                next((c for k, c in CATEGORY_WORDS.items() if k in q), None)
            dal, al, label = period_from_text(q)
            used.append("entrate_uscite")
            r = await tools.entrate_uscite(dal, al, company, cat)
            who = f" per {company}" if company else ""
            if cat:
                v = r["per_categoria"].get(cat, {"entrate": 0, "uscite": 0})
                kind = "entrate" if cat == "Incassi clienti" or re.search(r"incass|entrat|fatturat", q) else "uscite"
                return {"answer": f"{cat}{who} {label}: {kind} {_fmt(v[kind])}.", "tools": used}
            top = sorted(r["per_categoria"].items(), key=lambda kv: -kv[1]["uscite"])[:6]
            lines = [f"- {k}: uscite {_fmt(v['uscite'])}" + (f", entrate {_fmt(v['entrate'])}" if v["entrate"] else "") for k, v in top]
            return {"answer": f"{label.capitalize()}{who}: entrate {_fmt(r['totale_entrate'])}, uscite {_fmt(r['totale_uscite'])}.\n"
                              + "\n".join(lines), "tools": used}
        if re.search(r"budget", q):
            used.append("budget")
            r = await tools.budget(company)
            lines = [f"- {b['azienda']} · {x['categoria']}: {_fmt(x['reale'])} su {_fmt(x['budget'])}" + (" (sforato)" if x["sforato"] else "")
                     for b in r["budget"] for x in b["righe"] if x["budget"]]
            return {"answer": "\n".join(lines) or "Non è ancora impostato un budget.", "tools": used}
        m = re.search(r"(?:cerca|trova|movimenti? (?:di|da|a|con))\s+(.+)", q)
        if m:
            used.append("cerca_movimenti")
            r = await tools.cerca_movimenti(m.group(1).strip(" ?."), azienda=company)
            lines = [f"- {x['data']} · {x['azienda']} · {x['descrizione']}: {_fmt(x['importo'])}" for x in r["movimenti"][:12]]
            return {"answer": ("\n".join(lines) or "Nessun movimento trovato."), "tools": used}
        return {"answer": "In modalità di base capisco domande su: saldi, spese o incassi per categoria e periodo, "
                          "crediti verso clienti, debiti verso fornitori, scadenze, previsione di cassa, IVA, budget e ricerca "
                          "di movimenti. Prova per esempio: \"Quanto ha speso Alfa di carburante quest'anno?\". "
                          "Con il collegamento a Claude (AI_PROVIDER=anthropic) capisco qualsiasi domanda.", "tools": used}

    async def suggest_match(self, tx: dict, items: list[dict]) -> dict | None:
        amount = abs(tx["amount_cents"])
        words = set(re.findall(r"[a-zà-ù]{4,}", tx["description"].lower()))
        best, best_score = None, 0
        for it in items:
            diff = abs(it["amount_cents"] - amount) / max(amount, 1)
            score = max(0, 50 - diff * 500)
            common = words & set(re.findall(r"[a-zà-ù]{4,}", it["label"].lower()))
            score += 15 * len(common)
            if score > best_score:
                best, best_score = it, score
        if not best or best_score < 30:
            return {"targets": [], "explanation": "Non trovo una fattura o scadenza abbastanza simile. "
                                                  "Potrebbe essere una spesa senza fattura (es. scontrino) o un acconto.",
                    "confidence": "bassa"}
        diff = best["amount_cents"] - amount
        why = []
        if diff:
            why.append(f"l'importo differisce di {_fmt(diff / 100)} (forse commissioni, sconto o pagamento parziale)")
        else:
            why.append("l'importo coincide")
        if words & set(re.findall(r"[a-zà-ù]{4,}", best["label"].lower())):
            why.append("la causale contiene il nome della controparte")
        return {"targets": [{"type": best["type"], "id": best["id"], "label": best["label"], "amount_cents": best["amount_cents"]}],
                "explanation": "Probabile abbinamento: " + best["label"] + ". " + "; ".join(why).capitalize() + ".",
                "confidence": "media" if best_score >= 45 else "bassa"}


# ---------------------------------------------------------------- Claude

class AnthropicAI(AIProvider):
    name = "anthropic"

    async def _call(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(API_URL, json=payload, headers={
                "x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        if r.status_code >= 400:
            logger.warning("Errore AI %s: %s", r.status_code, r.text[:300])
            raise RuntimeError("Il servizio dell'assistente non ha risposto correttamente.")
        return r.json()

    async def ask(self, tools: Tools, question: str, history: list[dict]) -> dict:
        system = SYSTEM.format(today=today().strftime("%d/%m/%Y"), companies=", ".join(tools.names.values()))
        messages = [{"role": h["role"], "content": h["content"]} for h in history[-8:]
                    if h.get("role") in {"user", "assistant"} and isinstance(h.get("content"), str)]
        messages.append({"role": "user", "content": question})
        used = []
        names = {n for n, _, _ in TOOL_SPECS}
        for _ in range(6):
            resp = await self._call({"model": settings.ai_model, "max_tokens": 1200, "system": system,
                                     "tools": anthropic_tools(), "messages": messages})
            messages.append({"role": "assistant", "content": resp["content"]})
            calls = [b for b in resp["content"] if b.get("type") == "tool_use"]
            if not calls:
                text = "\n".join(b["text"] for b in resp["content"] if b.get("type") == "text").strip()
                return {"answer": text or "Non ho una risposta.", "tools": used}
            results = []
            for c in calls:
                used.append(c["name"])
                try:
                    if c["name"] not in names:
                        raise ValueError("strumento sconosciuto")
                    data = await getattr(tools, c["name"])(**(c.get("input") or {}))
                    content = json.dumps(data, ensure_ascii=False, default=str)[:20000]
                except Exception as e:  # noqa: BLE001 - l'errore torna al modello come risultato
                    content = json.dumps({"errore": str(e)})
                results.append({"type": "tool_result", "tool_use_id": c["id"], "content": content})
            messages.append({"role": "user", "content": results})
        return {"answer": "La domanda richiede troppi passaggi: prova a renderla più precisa.", "tools": used}

    async def read_receipt(self, data: bytes, mime: str) -> dict | None:
        block_type = "document" if mime == "application/pdf" else "image"
        prompt = ("Leggi questo scontrino o ricevuta e rispondi SOLO con un JSON: "
                  '{"data": "AAAA-MM-GG", "totale": numero, "esercente": "testo", "iva": numero o null}. '
                  "Se un dato non si legge usa null.")
        resp = await self._call({"model": settings.ai_model, "max_tokens": 300, "messages": [{"role": "user", "content": [
            {"type": block_type, "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": prompt}]}]})
        text = "".join(b.get("text", "") for b in resp["content"])
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    async def read_document(self, data: bytes, mime: str, prompt: str) -> dict | None:
        block_type = "document" if mime == "application/pdf" else "image"
        resp = await self._call({"model": settings.ai_model, "max_tokens": 800, "messages": [{"role": "user", "content": [
            {"type": block_type, "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": prompt}]}]})
        text = "".join(b.get("text", "") for b in resp["content"])
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    async def suggest_match(self, tx: dict, items: list[dict]) -> dict | None:
        listing = "\n".join(f"{i['id']} | {i['label']} | {i['amount_cents'] / 100:.2f} | scad. {i.get('due_date')}" for i in items[:40])
        prompt = (f"Movimento bancario: {tx['date']} | {tx['description']} | {tx['amount_cents'] / 100:.2f} EUR.\n"
                  f"Fatture e scadenze aperte (id | descrizione | importo | scadenza):\n{listing}\n\n"
                  "Quale (o quali) saldano questo movimento? Rispondi SOLO con JSON: "
                  '{"ids": ["..."], "spiegazione": "breve, in italiano", "affidabilita": "alta|media|bassa"}. '
                  "Se nessuna corrisponde usa ids vuoto e spiega cosa potrebbe essere.")
        resp = await self._call({"model": settings.ai_model, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]})
        text = "".join(b.get("text", "") for b in resp["content"])
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        by_id = {i["id"]: i for i in items}
        targets = [{"type": by_id[i]["type"], "id": i, "label": by_id[i]["label"], "amount_cents": by_id[i]["amount_cents"]}
                   for i in data.get("ids", []) if i in by_id]
        return {"targets": targets, "explanation": data.get("spiegazione", ""), "confidence": data.get("affidabilita", "bassa")}


class EmergentClaudeAI(AnthropicAI):
    """Claude tramite la chiave universale Emergent (EMERGENT_LLM_KEY)."""
    name = "claude"

    def _chat(self, system: str = "Rispondi in italiano."):
        from emergentintegrations.llm.chat import LlmChat
        return LlmChat(api_key=settings.emergent_llm_key, session_id=new_id(), system_message=system) \
            .with_model("anthropic", settings.ai_model)

    async def _ask_text(self, prompt: str, data: bytes | None = None, mime: str | None = None) -> str:
        from emergentintegrations.llm.chat import FileContent, ImageContent, UserMessage
        files = []
        if data is not None:
            b64 = base64.b64encode(data).decode()
            files = [ImageContent(b64)] if (mime or "").startswith("image/") else [FileContent(mime or "application/pdf", b64)]
        try:
            return await self._chat().send_message(UserMessage(text=prompt, file_contents=files)) or ""
        except Exception as e:  # noqa: BLE001
            logger.warning("Errore AI: %s", type(e).__name__)
            raise RuntimeError("Il servizio dell'assistente non ha risposto correttamente.") from e

    async def _call(self, payload: dict) -> dict:
        # Usato dai metodi ereditati: un solo messaggio utente con testo ed eventuale file
        content = payload["messages"][-1]["content"]
        if isinstance(content, str):
            text = await self._ask_text(content)
        else:
            prompt = next(b["text"] for b in content if b["type"] == "text")
            src = next((b["source"] for b in content if b["type"] in {"image", "document"}), None)
            text = await self._ask_text(prompt, base64.b64decode(src["data"]) if src else None, src and src["media_type"])
        return {"content": [{"type": "text", "text": text}]}

    async def ask(self, tools: Tools, question: str, history: list[dict]) -> dict:
        from emergentintegrations.llm.chat import UserMessage
        system = SYSTEM.format(today=today().strftime("%d/%m/%Y"), companies=", ".join(tools.names.values()))
        past = [f"{'Utente' if h['role'] == 'user' else 'Assistente'}: {h['content']}" for h in history[-8:]
                if h.get("role") in {"user", "assistant"} and isinstance(h.get("content"), str)]
        system += ("\n\nScrivi in testo semplice: niente asterischi, tabelle, titoli o altri simboli di formattazione. "
                   "Per gli elenchi usa righe che iniziano con un trattino.")
        if past:
            system += "\n\nConversazione precedente:\n" + "\n".join(past)[-6000:]
        functions = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                         "parameters": t["input_schema"]}} for t in anthropic_tools()]
        chat = self._chat(system).with_tools(functions, tool_choice="auto")
        names = {n for n, _, _ in TOOL_SPECS}
        used = []
        try:
            resp = await chat.send_message_with_tools(UserMessage(text=question))
            for _ in range(6):
                if not resp.tool_calls:
                    return {"answer": (resp.content or "").strip() or "Non ho una risposta.", "tools": used}
                for tc in resp.tool_calls:
                    used.append(tc.name)
                    try:
                        if tc.name not in names:
                            raise ValueError("strumento sconosciuto")
                        args = tc.arguments if isinstance(tc.arguments, dict) else json.loads(tc.arguments or "{}")
                        result = json.dumps(await getattr(tools, tc.name)(**args), ensure_ascii=False, default=str)[:20000]
                    except Exception as e:  # noqa: BLE001 - l'errore torna al modello come risultato
                        result = json.dumps({"errore": str(e)})
                    chat.add_tool_result(tc.id, result)
                resp = await chat.send_message_with_tools()
        except Exception as e:  # noqa: BLE001
            logger.warning("Errore AI: %s", type(e).__name__)
            raise RuntimeError("Il servizio dell'assistente non ha risposto correttamente.") from e
        return {"answer": "La domanda richiede troppi passaggi: prova a renderla più precisa.", "tools": used}


def get_ai() -> AIProvider | None:
    if settings.ai_provider == "none":
        return None
    if settings.ai_provider == "claude":
        if not settings.emergent_llm_key:
            logger.warning("AI_PROVIDER=claude ma EMERGENT_LLM_KEY è vuota: uso la modalità di base")
            return DemoAI()
        return EmergentClaudeAI()
    if settings.ai_provider == "anthropic":
        if not settings.anthropic_api_key:
            logger.warning("AI_PROVIDER=anthropic ma ANTHROPIC_API_KEY è vuota: uso la modalità di base")
            return DemoAI()
        return AnthropicAI()
    return DemoAI()
