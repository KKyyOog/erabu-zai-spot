from flask import Blueprint, request, jsonify
import logging

from app.services.sheets_service import upsert_user

link_bp = Blueprint("link", __name__, url_prefix="/link")
logger = logging.getLogger(__name__)


@link_bp.route("/liff", methods=["POST"])
def liff_link():
    data = request.get_json(silent=True) or {}

    user_id = data.get("userId")
    display_name = data.get("displayName", "")
    picture_url = data.get("pictureUrl", "")

    logger.info(f"[LIFF] Received data: userId={user_id}, displayName={display_name}")

    if not user_id:
        return jsonify({"ok": False, "message": "userId is required"}), 400

    upsert_user(
        {
            "line_user_id": user_id,
            "user_id": user_id,
            "display_name": display_name,
            "picture_url": picture_url,
        }
    )

    logger.info(f"[LIFF] User data saved: userId={user_id}")
    return jsonify({"ok": True})


@link_bp.route("/liff-debug", methods=["POST"])
def liff_debug():
    """LIFF デバッグログをサーバーログに出力"""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    timestamp = data.get("timestamp", "")
    
    logger.info(f"[LIFF DEBUG] {timestamp} - {message}")
    
    return jsonify({"ok": True})
