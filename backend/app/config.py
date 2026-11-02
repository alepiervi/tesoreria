import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sì"}


class Settings:
    mongo_url: str = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name: str = os.environ.get("DB_NAME", "tesoreria")
    jwt_secret: str = os.environ.get("JWT_SECRET", "dev-secret-change-me")
    jwt_expire_hours: int = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))
    cors_origins: list[str] = [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
    ]
    frontend_url: str = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    seed_demo: bool = _bool("SEED_DEMO", True)
    developer_email: str = os.environ.get("DEVELOPER_EMAIL", "")
    developer_password: str = os.environ.get("DEVELOPER_PASSWORD", "")
    developer_name: str = os.environ.get("DEVELOPER_NAME", "Sviluppatore")
    banking_provider: str = os.environ.get("BANKING_PROVIDER", "demo")
    sdi_provider: str = os.environ.get("SDI_PROVIDER", "demo")
    payments_provider: str = os.environ.get("PAYMENTS_PROVIDER", "demo")
    max_document_mb: int = int(os.environ.get("MAX_DOCUMENT_MB", "10"))
    timezone: str = os.environ.get("TIMEZONE", "Europe/Rome")

    # Invii: "demo" salva i messaggi nella casella interna (visibile in Impostazioni) senza spedirli
    email_provider: str = os.environ.get("EMAIL_PROVIDER", "demo")
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("SMTP_FROM", "")
    smtp_ssl: bool = _bool("SMTP_SSL", False)
    whatsapp_provider: str = os.environ.get("WHATSAPP_PROVIDER", "demo")
    whatsapp_token: str = os.environ.get("WHATSAPP_TOKEN", "")
    whatsapp_phone_id: str = os.environ.get("WHATSAPP_PHONE_ID", "")
    whatsapp_template: str = os.environ.get("WHATSAPP_TEMPLATE", "avviso_tesoreria")

    # Attività automatiche (avvisi, riepilogo settimanale, report mensile, backup)
    scheduler_enabled: bool = _bool("SCHEDULER_ENABLED", True)
    alerts_hour: int = int(os.environ.get("ALERTS_HOUR", "8"))

    # Sicurezza
    require_2fa_for_payments: bool = _bool("REQUIRE_2FA_FOR_PAYMENTS", True)

    # Assistente: "demo" risponde alle domande più comuni senza servizi esterni,
    # "anthropic" usa Claude (serve ANTHROPIC_API_KEY), "none" lo disattiva
    ai_provider: str = os.environ.get("AI_PROVIDER", "demo")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    ai_model: str = os.environ.get("AI_MODEL", "claude-sonnet-5-5")

    # Backup automatico del database (cartella sul server; vuoto = disattivato)
    backup_dir: str = os.environ.get("BACKUP_DIR", "")
    backup_keep_days: int = int(os.environ.get("BACKUP_KEEP_DAYS", "30"))
    max_failed_logins: int = 5
    lockout_minutes: int = 15


settings = Settings()
