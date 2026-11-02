"""Registro errori tecnici per lo sviluppatore: mai dati delle aziende, solo dove e che tipo di errore."""
import hashlib
import os
import re
import traceback

from ..db import get_db
from ..utils import new_id, now_iso

MAX_ERRORS = 500
# Solo questi errori hanno messaggi "di codice" (nomi di campi, tipi); gli altri potrebbero contenere dati
SAFE_MESSAGE_TYPES = {
    "KeyError", "AttributeError", "TypeError", "NameError", "ImportError", "ModuleNotFoundError",
    "ZeroDivisionError", "IndexError", "AssertionError", "NotImplementedError", "RecursionError", "UnboundLocalError",
}
_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}|\d{3,}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
HIDDEN = "(messaggio nascosto: potrebbe contenere dati)"


def clean_path(path: str) -> str:
    return _ID.sub(":id", path or "")[:200]


def clean_text(text: str, limit: int) -> str:
    return _ID.sub(":n", _EMAIL.sub("<email>", text or ""))[:limit]


def _frames(exc: BaseException) -> list[str]:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = []
    for f in traceback.extract_tb(exc.__traceback__)[-8:]:
        name = os.path.relpath(f.filename, root) if f.filename.startswith(root) else os.path.basename(f.filename)
        out.append(f"{name}:{f.lineno} in {f.name}")
    return out


async def _store(source: str, kind: str, message: str, where: str, frames: list[str], method: str = ""):
    db = get_db()
    fp = hashlib.sha1(f"{source}|{kind}|{where}|{frames[-1] if frames else ''}".encode()).hexdigest()[:16]
    now = now_iso()
    res = await db.system_errors.update_one(
        {"fingerprint": fp},
        {"$set": {"last_at": now, "message": message, "frames": frames, "resolved": False},
         "$inc": {"count": 1},
         "$setOnInsert": {"id": new_id(), "fingerprint": fp, "source": source, "kind": kind,
                          "where": where, "method": method, "first_at": now}},
        upsert=True,
    )
    if res.upserted_id is not None and await db.system_errors.count_documents({}) > MAX_ERRORS:
        old = await db.system_errors.find({}, {"_id": 1}).sort("last_at", 1).limit(50).to_list(50)
        await db.system_errors.delete_many({"_id": {"$in": [o["_id"] for o in old]}})


async def record_server_error(request, exc: BaseException):
    route = request.scope.get("route")
    where = getattr(route, "path", None) or clean_path(request.url.path)
    kind = type(exc).__name__
    message = clean_text(str(exc), 300) if kind in SAFE_MESSAGE_TYPES else HIDDEN
    try:
        await _store("server", kind, message, where, _frames(exc), request.method)
    except Exception:  # noqa: BLE001 - il registro errori non deve mai rompere la risposta
        pass


async def record_client_error(message: str, stack: str, path: str):
    lines = [clean_text(line.strip(), 200) for line in (stack or "").splitlines()[1:9] if line.strip()]
    await _store("browser", "Errore pagina", clean_text(message, 300), clean_path(path), lines)
