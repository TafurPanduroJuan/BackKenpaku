from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Comercial Kenpaku S.A.C. API"
    ENV: str = "development"
    PORT: int = 8000

    DATABASE_URL: str = "sqlite:///./test.db"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    JWT_SECRET: str = "super-secret-jwt-key-change-in-production-min-32-chars"
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
    FRONTEND_URL: str = "http://localhost:5173"

    # Almacenamiento de Comprobantes / Vouchers (Fase 4: Supabase Storage + Fallback Local)
    SUPABASE_URL: Union[str, None] = None
    SUPABASE_KEY: Union[str, None] = None
    SUPABASE_BUCKET_VOUCHERS: str = "vouchers"
    UPLOAD_DIR: str = "uploads/vouchers"
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB

    # Automatización y Tareas Programadas (Fase 5: Cron)
    CRON_SECRET: str = "kenpaku-cron-secret-key-2026"
    CRON_REMINDER_HOURS: int = 24
    CRON_EXPIRATION_HOURS: int = 48

    ADMIN_EMAIL: str = "admin@kenpaku.pe"
    ADMIN_PASSWORD: str = "AdminKenpaku2026!"
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
