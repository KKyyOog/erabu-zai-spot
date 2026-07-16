import logging

from flask import Blueprint, abort, current_app, jsonify, request, session

from app.services.line_auth_service import LineAuthError, verify_id_token

link_bp = Blueprint("link", __name__, url_prefix="/link")
logger = logging.getLogger(__name__)


@link_bp.route("/liff", methods=["POST"])
def liff_link():
    data = request.get_json(silent=True) or {}

    user_id = (data.get("userId") or "").strip()
    id_token = (data.get("idToken") or data.get("id_token") or "").strip()

    logger.info(
        "[LIFF] auth received user_id_present=%s id_token_present=%s path=%s user_agent=%s",
        bool(user_id),
        bool(id_token),
        request.path,
        request.headers.get("User-Agent", ""),
    )

    if not user_id:
        logger.warning("[LIFF] auth rejected because userId is missing")
        return jsonify({"ok": False, "message": "userId is required"}), 400
    if not id_token:
        logger.warning("[LIFF] auth rejected because idToken is missing")
        return jsonify({"ok": False, "message": "idToken is required"}), 400

    try:
        claims = verify_id_token(id_token, expected_user_id=user_id)
    except LineAuthError as exc:
        logger.warning("[LIFF] auth rejected: %s", exc)
        return jsonify({"ok": False, "message": "LINE authentication failed"}), 401

    session["line_user_id"] = claims["sub"]
    logger.info("[LIFF] auth accepted")
    return jsonify({"ok": True})


@link_bp.route("/session", methods=["GET"])
def session_status():
    line_user_id = (session.get("line_user_id") or "").strip()
    return jsonify({"ok": bool(line_user_id), "line_user_id": line_user_id})


@link_bp.route("/liff-debug", methods=["POST"])
def liff_debug():
    if not current_app.config.get("LIFF_DEBUG_LOGGING", False):
        abort(404)

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", ""))[:500].replace("\r", " ").replace("\n", " ")
    timestamp = str(data.get("timestamp", ""))[:100].replace("\r", " ").replace("\n", " ")

    logger.info(
        "[LIFF DEBUG] timestamp=%s message=%s remote_addr=%s referer=%s user_agent=%s",
        timestamp,
        message,
        request.headers.get("X-Forwarded-For", request.remote_addr),
        request.headers.get("Referer", ""),
        request.headers.get("User-Agent", ""),
    )

    return jsonify({"ok": True})
