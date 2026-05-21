import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
    LIFF_ID = os.getenv("LIFF_ID", "")
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")
    GOOGLE_SERVICE_ACCOUNT_JSON_TEXT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_TEXT", "")
    ADMIN_LINE_USER_ID = os.getenv("ADMIN_LINE_USER_ID", "")
