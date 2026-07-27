import time
from urllib.parse import quote

from flask import current_app
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)

LINE_PROFILE_CACHE_SECONDS = 300
_line_profile_cache = {}


def send_line_message(user_id, text):
    if not user_id:
        return False

    token = current_app.config["LINE_CHANNEL_ACCESS_TOKEN"]
    if not token:
        current_app.logger.warning("LINE_CHANNEL_ACCESS_TOKEN is not set.")
        return False

    configuration = Configuration(access_token=token)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text)],
            )
        )

    return True


def reply_line_message(reply_token, text):
    if not reply_token:
        return False

    token = current_app.config["LINE_CHANNEL_ACCESS_TOKEN"]
    if not token:
        current_app.logger.warning("LINE_CHANNEL_ACCESS_TOKEN is not set.")
        return False

    configuration = Configuration(access_token=token)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
    return True


def get_line_user_profile(user_id):
    if not user_id:
        return None

    now = time.monotonic()
    cached = _line_profile_cache.get(user_id)
    if cached and cached[0] > now:
        return dict(cached[1])

    token = current_app.config.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        current_app.logger.warning("LINE_CHANNEL_ACCESS_TOKEN is not set.")
        return None

    try:
        configuration = Configuration(access_token=token)
        with ApiClient(configuration) as api_client:
            profile = MessagingApi(api_client).get_profile(user_id)
        result = {
            "display_name": (
                getattr(profile, "display_name", "") or ""
            ).strip(),
            "picture_url": (
                getattr(profile, "picture_url", "") or ""
            ).strip(),
        }
        _line_profile_cache[user_id] = (
            now + LINE_PROFILE_CACHE_SECONDS,
            result,
        )
        return dict(result)
    except Exception:
        current_app.logger.exception(
            "[LINE] failed to load linked user profile"
        )
        return None


def get_line_official_account_id():
    configured_id = (
        current_app.config.get("LINE_OFFICIAL_ACCOUNT_ID", "") or ""
    ).strip()
    if configured_id:
        return configured_id

    cached_id = current_app.extensions.get("line_official_account_id", "")
    if cached_id:
        return cached_id

    token = current_app.config.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return ""

    try:
        configuration = Configuration(access_token=token)
        with ApiClient(configuration) as api_client:
            bot_info = MessagingApi(api_client).get_bot_info()
        basic_id = (getattr(bot_info, "basic_id", "") or "").strip()
        if basic_id:
            current_app.extensions["line_official_account_id"] = basic_id
        return basic_id
    except Exception:
        current_app.logger.exception(
            "[LINE] failed to load official account basic ID"
        )
        return ""


def build_line_official_account_message_url(text):
    official_account_id = get_line_official_account_id()
    if not official_account_id:
        return ""
    return (
        "https://line.me/R/oaMessage/"
        f"{quote(official_account_id, safe='')}/?{quote(text, safe='')}"
    )
