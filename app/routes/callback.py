from flask import Blueprint, request, abort, current_app  # type: ignore[import]

from linebot import WebhookHandler
from linebot.exceptions import InvalidSignatureError

callback_bp = Blueprint("callback", __name__)


@callback_bp.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    handler = WebhookHandler(current_app.config["LINE_CHANNEL_SECRET"])

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
