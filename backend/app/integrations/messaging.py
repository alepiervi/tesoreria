"""Invio di email e messaggi WhatsApp.

- "demo": i messaggi non partono, vengono salvati nella collezione `outbox` e si vedono
  nel programma (Impostazioni → Casella di prova). Utile per provare senza spedire nulla.
- "smtp": email vere tramite il server di posta (Aruba, Gmail/Workspace, Microsoft 365, ...).
- "meta": WhatsApp Business Cloud API. Per i messaggi che partono dall'azienda Meta richiede
  un "modello" approvato (WHATSAPP_TEMPLATE) con un parametro di testo.
"""
import asyncio
import json
import logging
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage

from ..config import settings
from ..db import get_db
from ..utils import new_id, now_iso

logger = logging.getLogger("tesoreria.messaging")


async def _store(channel: str, to: str, subject: str, body: str, status: str, error: str | None = None,
                 attachments: list | None = None, meta: dict | None = None):
    await get_db().outbox.insert_one({
        "id": new_id(), "channel": channel, "to": to, "subject": subject, "body": body,
        "attachments": [a[0] for a in attachments or []], "status": status, "error": error,
        "meta": meta or {}, "created_at": now_iso(),
    })


def _send_smtp(to: str, subject: str, text: str, html: str | None, attachments: list):
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments:
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    context = ssl.create_default_context()
    if settings.smtp_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=30) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.starttls(context=context)
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)


async def send_email(to: str, subject: str, text: str, html: str | None = None,
                     attachments: list | None = None, meta: dict | None = None) -> dict:
    """attachments: lista di (nome_file, bytes, tipo_mime). Restituisce {'status': 'inviato'|'demo'|'errore'}."""
    attachments = attachments or []
    if not to or "@" not in to:
        return {"status": "errore", "error": "Indirizzo email mancante o non valido."}
    if settings.email_provider == "smtp":
        try:
            await asyncio.to_thread(_send_smtp, to, subject, text, html, attachments)
            await _store("email", to, subject, text, "inviato", attachments=attachments, meta=meta)
            return {"status": "inviato"}
        except Exception as e:  # noqa: BLE001 - l'errore va mostrato all'utente, non deve bloccare il programma
            logger.warning("Invio email fallito: %s", e)
            await _store("email", to, subject, text, "errore", str(e), attachments, meta)
            return {"status": "errore", "error": "Invio non riuscito: controlla le impostazioni email del server."}
    await _store("email", to, subject, text, "demo", attachments=attachments, meta=meta)
    return {"status": "demo"}


def _send_whatsapp_meta(to: str, text: str):
    url = f"https://graph.facebook.com/v20.0/{settings.whatsapp_phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp", "to": to.lstrip("+").replace(" ", ""), "type": "template",
        "template": {"name": settings.whatsapp_template, "language": {"code": "it"},
                     "components": [{"type": "body", "parameters": [{"type": "text", "text": text[:1000]}]}]},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {settings.whatsapp_token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - URL fisso del servizio Meta
        r.read()


async def send_whatsapp(to: str, text: str, meta: dict | None = None) -> dict:
    if not to:
        return {"status": "errore", "error": "Numero WhatsApp mancante."}
    if settings.whatsapp_provider == "meta":
        try:
            await asyncio.to_thread(_send_whatsapp_meta, to, text)
            await _store("whatsapp", to, "", text, "inviato", meta=meta)
            return {"status": "inviato"}
        except Exception as e:  # noqa: BLE001
            logger.warning("Invio WhatsApp fallito: %s", e)
            await _store("whatsapp", to, "", text, "errore", str(e), meta=meta)
            return {"status": "errore", "error": "Invio WhatsApp non riuscito."}
    await _store("whatsapp", to, "", text, "demo", meta=meta)
    return {"status": "demo"}


def html_page(title: str, paragraphs: list[str], rows: list[tuple[str, str]] | None = None,
              link: str | None = None, link_label: str = "Apri il programma") -> str:
    """Email HTML semplice e leggibile anche sul telefono."""
    from html import escape
    body = "".join(f"<p style='margin:0 0 12px'>{escape(p)}</p>" for p in paragraphs)
    if rows:
        body += "<table style='border-collapse:collapse;width:100%;margin:8px 0 16px'>" + "".join(
            f"<tr><td style='padding:6px 8px;border-bottom:1px solid #E3E5E8'>{escape(a)}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #E3E5E8;text-align:right;white-space:nowrap'>{escape(b)}</td></tr>"
            for a, b in rows) + "</table>"
    if link:
        body += (f"<p><a href='{escape(link)}' style='display:inline-block;background:#2346D8;color:#fff;"
                 f"padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:600'>{escape(link_label)}</a></p>")
    return (f"<div style='font-family:system-ui,Segoe UI,sans-serif;color:#15171C;max-width:600px;margin:0 auto;padding:16px'>"
            f"<h2 style='font-size:18px;margin:0 0 16px'>{escape(title)}</h2>{body}"
            f"<p style='color:#5B6170;font-size:12px;margin-top:24px'>Tesoreria di gruppo</p></div>")
