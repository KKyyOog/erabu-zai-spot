import hashlib
import re

from flask import Blueprint, request, abort, current_app  # type: ignore[import]

from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import (
    FollowEvent,
    MessageEvent,
    TextMessageContent,
    UnfollowEvent,
)

from app.services.db_service import (
    consume_line_notification_link_code,
    set_line_friendship,
)
from app.services.line_service import reply_line_message

callback_bp = Blueprint("callback", __name__)

NOTIFICATION_LINK_MESSAGE_PATTERN = re.compile(
    r"^通知連携\s+([A-HJ-NP-Z2-9]{10})$"
)


def _notification_link_reply(status):
    return {
        "linked": (
            "LINE通知の連携が完了しました。"
            "今後、えらぶ材すぽっとからの通知をこのトークへお届けします。"
            "継続して受け取るため、この公式アカウントを友だち追加してください。"
        ),
        "already_linked": "LINE通知はすでに連携済みです。",
        "expired": (
            "通知連携コードの期限が切れています。"
            "マイページで新しいコードを発行してください。"
        ),
        "used": (
            "この通知連携コードは使用済みです。"
            "マイページで連携状態をご確認ください。"
        ),
        "line_already_linked": (
            "このLINEアカウントは別の利用情報と連携済みです。"
            "運営者へお問い合わせください。"
        ),
        "invalid": (
            "通知連携コードを確認できませんでした。"
            "マイページから発行したメッセージをそのまま送信してください。"
        ),
    }.get(status, "通知連携を完了できませんでした。")


@callback_bp.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    handler = WebhookHandler(current_app.config["LINE_CHANNEL_SECRET"])

    @handler.add(FollowEvent)
    def handle_follow(event):
        source_user_id = (
            getattr(event.source, "user_id", "") or ""
        ).strip()
        if source_user_id:
            set_line_friendship(source_user_id, True)
            current_app.logger.info(
                "[LINE CALLBACK] friendship enabled"
            )

    @handler.add(UnfollowEvent)
    def handle_unfollow(event):
        source_user_id = (
            getattr(event.source, "user_id", "") or ""
        ).strip()
        if source_user_id:
            set_line_friendship(source_user_id, False)
            current_app.logger.info(
                "[LINE CALLBACK] friendship disabled"
            )

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        text = (getattr(event.message, "text", "") or "").strip().upper()
        if not text.startswith("通知連携"):
            return

        match = NOTIFICATION_LINK_MESSAGE_PATTERN.fullmatch(text)
        status = "invalid"
        if match:
            code_hash = hashlib.sha256(
                match.group(1).encode("utf-8")
            ).hexdigest()
            source_user_id = (
                getattr(event.source, "user_id", "") or ""
            ).strip()
            _, status = consume_line_notification_link_code(
                code_hash,
                source_user_id,
            )

        try:
            reply_line_message(
                getattr(event, "reply_token", ""),
                _notification_link_reply(status),
            )
        except Exception:
            current_app.logger.exception(
                "[LINE CALLBACK] failed to reply to notification link message"
            )

        current_app.logger.info(
            "[LINE CALLBACK] notification link status=%s",
            status,
        )

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        current_app.logger.warning(
            "[LINE CALLBACK] invalid signature path=%s signature_present=%s body_length=%s remote_addr=%s user_agent=%s",
            request.path,
            bool(signature),
            len(body or ""),
            request.headers.get("X-Forwarded-For", request.remote_addr),
            request.headers.get("User-Agent", ""),
        )
        abort(400)

    current_app.logger.info(
        "[LINE CALLBACK] accepted path=%s body_length=%s remote_addr=%s",
        request.path,
        len(body or ""),
        request.headers.get("X-Forwarded-For", request.remote_addr),
    )
    return "OK"
