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
        "exp": now_utc() + timedelta(hours=settings.jwt_expire_hours),
        "iat": now_utc(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Tesoreria di gruppo")


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
