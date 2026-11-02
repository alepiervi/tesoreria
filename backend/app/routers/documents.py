"""Archivio documenti per azienda (F24, bilanci, dichiarazioni, contratti...)."""
import re

from bson import Binary
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require
from ..permissions import has_permission
from ..utils import new_id, now_iso
from .common import load

router = APIRouter(tags=["documents"])

DOC_CATEGORIES = ["F24", "Bilancio", "Dichiarazione", "Contratto", "Busta paga", "Estratto conto", "Scontrino", "Altro"]
ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "application/xml", "text/xml", "text/csv",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "application/zip", "application/pkcs7-mime", "application/octet-stream"}


@router.get("/document-categories")
async def categories():
    return DOC_CATEGORIES


@router.get("/companies/{company_id}/documents")
async def list_documents(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    return await get_db().documents.find({"company_id": company_id}, {"_id": 0, "data": 0}) \
        .sort("created_at", -1).to_list(2000)


@router.post("/companies/{company_id}/documents")
async def upload(company_id: str, file: UploadFile = File(...), category: str = Form("Altro"),
                 note: str = Form(""), period: str = Form(""), user: dict = Depends(get_current_user)):
    await require(user, company_id, "upload_documents")
    if category not in DOC_CATEGORIES:
        raise HTTPException(400, "Categoria non valida.")
    limit = settings.max_document_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Il file supera {settings.max_document_mb} MB.")
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Tipo di file non ammesso.")
    name = re.sub(r"[^\w .()-]", "_", file.filename or "documento")[:150]
    doc = {"id": new_id(), "company_id": company_id, "name": name, "category": category, "note": note.strip(),
           "period": period.strip(), "content_type": content_type, "size": len(data),
           "uploaded_by": user["id"], "uploaded_by_name": user.get("name", ""), "created_at": now_iso()}
    # Con file grandi o molti documenti conviene spostare l'archivio su uno storage (es. S3) e salvare qui solo il link
    await get_db().documents.insert_one({**doc, "data": Binary(data)})
    await audit.log(user, "documento_caricato", company_id, name)
    return doc


@router.get("/documents/{document_id}/download")
async def download(document_id: str, user: dict = Depends(get_current_user)):
    meta, _ = await load("documents", document_id, user, "view")
    doc = await get_db().documents.find_one({"id": document_id})
    await audit.log(user, "documento_scaricato", meta["company_id"], meta["name"])
    return Response(bytes(doc["data"]), media_type=meta["content_type"],
                    headers={"Content-Disposition": f'attachment; filename="{meta["name"]}"'})


@router.delete("/documents/{document_id}")
async def delete(document_id: str, user: dict = Depends(get_current_user)):
    meta, role = await load("documents", document_id, user, "view")
    if meta["uploaded_by"] != user["id"] and not has_permission(role, "manage_members"):
        raise HTTPException(403, "Puoi eliminare solo i documenti che hai caricato tu.")
    await get_db().documents.delete_one({"id": document_id})
    await audit.log(user, "documento_eliminato", meta["company_id"], meta["name"])
    return {"ok": True}
