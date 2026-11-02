import hashlib
import secrets
from datetime import timedelta

import bcrypt
import jwt
import pyotp

from .config import settings
from .utils import now_utc

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def validate_password_strength(password: str) -> str | None:
    """Restituisce un messaggio di errore se la password è debole, altrimenti None."""
    if len(password) < 10:
        return "La password deve avere almeno 10 caratteri."
    if not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        return "La password deve contenere lettere e numeri."
    return None


def create_access_token(user_id: str, token_version: int) -> str:
    payload = {
        "sub": user_id,
        "ver": token_version,
        "typ": "access",
        "exp": now_utc() + timedelta(hours=settings.jwt_expire_hours),
        "iat": now_utc(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def create_setup_token(user_id: str, token_version: int) -> str:
    """Token breve, valido solo per attivare la verifica in due passaggi dopo la password."""
    payload = {"sub": user_id, "ver": token_version, "typ": "2fa_setup",
               "exp": now_utc() + timedelta(minutes=10), "iat": now_utc()}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, typ: str = "access") -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    if payload.get("typ") != typ:
        raise jwt.InvalidTokenError("tipo di token non valido")
    return payload


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Nureal-Amministrazione")


def totp_step(secret: str, code: str) -> int | None:
    """Restituisce il passo temporale del codice se valido (±30 s), altrimenti None."""
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = int(now_utc().timestamp())
    for offset in (0, -1, 1):
        step = now // 30 + offset
        if secrets.compare_digest(totp.at(step * 30), code):
            return step
    return None


def verify_totp(secret: str, code: str) -> bool:
    return totp_step(secret, code) is not None


def new_recovery_codes(n: int = 10) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)) for _ in range(n)]


def normalize_recovery_code(code: str) -> str:
    c = (code or "").strip().upper().replace(" ", "").replace("-", "")
    return f"{c[:4]}-{c[4:]}" if len(c) == 8 else c


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
