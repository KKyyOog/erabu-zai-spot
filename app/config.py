import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    ALLOW_INSECURE_DEV_CONFIG = os.getenv("ALLOW_INSECURE_DEV_CONFIG", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///erabu_zai_spot.db")
    DATABASE_SSLMODE = os.getenv("DATABASE_SSLMODE", "require")
    AUTO_CREATE_TABLES = os.getenv("AUTO_CREATE_TABLES", "true").lower() not in ("0", "false", "no")
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
    LINE_CHANNEL_ID = os.getenv("LINE_CHANNEL_ID", "")
    LIFF_ID = os.getenv("LIFF_ID", "")
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")
    GOOGLE_SERVICE_ACCOUNT_JSON_TEXT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_TEXT", "")
    ADMIN_LINE_USER_ID = os.getenv("ADMIN_LINE_USER_ID", "")
    SECURITY_REQUIRE_LINE_ID_TOKEN = os.getenv("SECURITY_REQUIRE_LINE_ID_TOKEN", "true").lower() not in (
        "0",
        "false",
        "no",
    )
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(10 * 1024 * 1024)))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    LIFF_DEBUG_LOGGING = os.getenv("LIFF_DEBUG_LOGGING", "false").lower() in ("1", "true", "yes")
