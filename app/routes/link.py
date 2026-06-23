import logging

from flask import Blueprint, jsonify, request

link_bp = Blueprint("link", __name__, url_prefix="/link")
logger = logging.getLogger(__name__)


@link_bp.route("/liff", methods=["POST"])
def liff_link():
    data = request.get_json(silent=True) or {}

    user_id = data.get("userId")
    display_name = data.get("displayName", "")
    picture_url = data.get("pictureUrl", "")

    logger.info(
        "[LIFF] profile received userId=%s displayName=%s path=%s user_agent=%s",
        user_id,
        display_name,
        request.path,
        request.headers.get("User-Agent", ""),
    )

    if not user_id:
        logger.warning("[LIFF] profile rejected because userId is missing payload=%s", data)
        return jsonify({"ok": False, "message": "userId is required"}), 400

    logger.info(
        "[LIFF] profile accepted userId=%s displayName=%s pictureUrl=%s",
        user_id,
        display_name,
        picture_url,
    )
    return jsonify({"ok": True})


@link_bp.route("/liff-debug", methods=["POST"])
def liff_debug():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    timestamp = data.get("timestamp", "")
    details = data.get("details", {})

    logger.info(
        "[LIFF DEBUG] timestamp=%s message=%s details=%s remote_addr=%s referer=%s user_agent=%s",
        timestamp,
        message,
        details,
        request.headers.get("X-Forwarded-For", request.remote_addr),
        request.headers.get("Referer", ""),
        request.headers.get("User-Agent", ""),
    )

    return jsonify({"ok": True})
