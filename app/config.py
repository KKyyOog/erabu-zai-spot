import os
from datetime import timedelta

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
    LINE_LOGIN_ENABLED = os.getenv("LINE_LOGIN_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    LINE_OFFICIAL_ACCOUNT_ID = os.getenv("LINE_OFFICIAL_ACCOUNT_ID", "")
    LINE_NOTIFICATION_LINK_TTL_MINUTES = int(
        os.getenv("LINE_NOTIFICATION_LINK_TTL_MINUTES", "10")
    )
    LIFF_ID = os.getenv("LIFF_ID", "").strip()
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
    PERMANENT_SESSION_LIFETIME = timedelta(
        days=int(os.getenv("GUEST_SESSION_DAYS", "365"))
    )
    LIFF_DEBUG_LOGGING = os.getenv("LIFF_DEBUG_LOGGING", "true").lower() in ("1", "true", "yes")
    USER_INFO_CACHE_SECONDS = int(os.getenv("USER_INFO_CACHE_SECONDS", "600"))
    USER_INFO_CACHE_MAX_ENTRIES = int(os.getenv("USER_INFO_CACHE_MAX_ENTRIES", "1000"))
