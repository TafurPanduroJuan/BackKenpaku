import secrets
from typing import List, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SECRETOS_PUBLICADOS = {
    "super-secret-jwt-key-change-in-production-min-32-chars",
    "super-secret-jwt-key-min-32-chars",
    "kenpaku-cron-secret-key-2026",
    "AdminKenpaku2026!",
}


class Settings(BaseSettings):
    PROJECT_NAME: str = "Comercial Kenpaku S.A.C. API"
    ENV: str = "development"
    PORT: int = 8000

    DATABASE_URL: str = "sqlite:///./test.db"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_FALLBACK_MODEL: str = "gemini-3.1-flash-lite"  # vacío = sin respaldo
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 120

    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ]

    WHATSAPP_NUMBER: str = "51987654321"
    STOCK_LOW_THRESHOLD: int = 10
    RAG_MAX_DISTANCE: float = 0.5

    # Notificaciones (Fase 3: Brevo, Telegram y Enlaces Públicos)
    BREVO_API_KEY: Union[str, None] = None
    SENDER_EMAIL: str = "ventas@kenpaku.pe"
    SENDER_NAME: str = "Comercial Kenpaku S.A.C."
    TELEGRAM_BOT_TOKEN: Union[str, None] = None
    TELEGRAM_CHAT_ID: Union[str, None] = None
    FRONTEND_URL: str = "http://localhost:3000"

    # SMTP alternativo (Gmail, Outlook o hosting)
    SMTP_HOST: Union[str, None] = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Union[str, None] = None
    SMTP_PASSWORD: Union[str, None] = None
    SMTP_USE_TLS: bool = True

    # Almacenamiento de Comprobantes / Vouchers (Fase 4: Supabase Storage + Fallback Local)
    SUPABASE_URL: Union[str, None] = None
    SUPABASE_KEY: Union[str, None] = None
    SUPABASE_BUCKET_VOUCHERS: str = "vouchers"
    UPLOAD_DIR: str = "uploads/vouchers"
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB

    # Automatización y Tareas Programadas (Fase 5: Cron)
    CRON_SECRET: str = ""
    CRON_REMINDER_HOURS: int = 24
    CRON_EXPIRATION_HOURS: int = 48

    ADMIN_EMAIL: str = "admin@kenpaku.pe"
    ADMIN_PASSWORD: str = ""

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().strip('"').strip("'")
            if v.startswith("postgres://"):
                v = "postgresql+psycopg2://" + v[len("postgres://"):]
            elif v.startswith("postgresql://"):
                v = "postgresql+psycopg2://" + v[len("postgresql://"):]
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if not v.strip():
                return ["*"]
            if not v.startswith("["):
                return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["*"]

    @model_validator(mode="after")
    def validate_secrets(self):
        if self.ENV.lower() == "production":
            errores = []
            if len(self.JWT_SECRET) < 32 or self.JWT_SECRET in _SECRETOS_PUBLICADOS:
                errores.append("JWT_SECRET (mínimo 32 caracteres y distinto al de ejemplo)")
            if len(self.CRON_SECRET) < 16 or self.CRON_SECRET in _SECRETOS_PUBLICADOS:
                errores.append("CRON_SECRET (mínimo 16 caracteres y distinto al de ejemplo)")
            if len(self.ADMIN_PASSWORD) < 12 or self.ADMIN_PASSWORD in _SECRETOS_PUBLICADOS:
                errores.append("ADMIN_PASSWORD (mínimo 12 caracteres y distinta a la de ejemplo)")
            if errores:
                raise ValueError(
                    "Variables inseguras o ausentes en producción: " + "; ".join(errores)
                )
        else:
            if not self.JWT_SECRET:
                self.JWT_SECRET = secrets.token_urlsafe(48)
            if not self.CRON_SECRET:
                self.CRON_SECRET = secrets.token_urlsafe(32)
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()