import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, abort, current_app, jsonify, request, session

from app.services.db_service import (
    create_line_notification_link_code,
    get_line_notification_link,
)
from app.services.line_auth_service import LineAuthError, verify_id_token
from app.services.line_service import (
    build_line_official_account_message_url,
    get_line_user_profile,
)

link_bp = Blueprint("link", __name__, url_prefix="/link")
logger = logging.getLogger(__name__)

NOTIFICATION_LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
NOTIFICATION_LINK_CODE_LENGTH = 10


def _notification_link_code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@link_bp.route("/liff", methods=["POST"])
def liff_link():
    if not current_app.config.get("LINE_LOGIN_ENABLED", False):
        return jsonify({
            "ok": False,
            "code": "line_login_disabled",
            "message": "LINE login is temporarily disabled",
        }), 503

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
        session.pop("line_user_id", None)
        logger.warning("[LIFF] auth rejected: %s", exc)
        return jsonify({
            "ok": False,
            "code": "line_token_invalid",
            "message": "LINE authentication failed",
        }), 401

    session["line_user_id"] = claims["sub"]
    session.permanent = False
    logger.info("[LIFF] auth accepted")
    return jsonify({"ok": True})


@link_bp.route("/guest", methods=["POST"])
def guest_link():
    current_user_id = (session.get("line_user_id") or "").strip()
    if current_user_id:
        return jsonify({
            "ok": True,
            "line_user_id": current_user_id,
            "auth_mode": (
                "guest" if current_user_id.startswith("anon_") else "line"
            ),
        })

    guest_user_id = f"anon_{secrets.token_urlsafe(24)}"
    session["line_user_id"] = guest_user_id
    session.permanent = True
    logger.info("[GUEST AUTH] guest session created")
    return jsonify({
        "ok": True,
        "line_user_id": guest_user_id,
        "auth_mode": "guest",
    })


@link_bp.route("/notification-code", methods=["POST"])
def notification_code():
    app_user_id = (session.get("line_user_id") or "").strip()
    if not app_user_id:
        return jsonify({
            "ok": False,
            "message": "利用者情報を確認できませんでした。",
        }), 401
    if not app_user_id.startswith("anon_"):
        return jsonify({
            "ok": False,
            "message": "LINE連携済みのため、通知連携コードは不要です。",
        }), 400

    code = "".join(
        secrets.choice(NOTIFICATION_LINK_CODE_ALPHABET)
        for _ in range(NOTIFICATION_LINK_CODE_LENGTH)
    )
    ttl_minutes = max(
        1,
        min(
            int(
                current_app.config.get(
                    "LINE_NOTIFICATION_LINK_TTL_MINUTES",
                    10,
                )
            ),
            60,
        ),
    )
    expires_at = (
        datetime.now() + timedelta(minutes=ttl_minutes)
    ).strftime("%Y-%m-%d %H:%M:%S")
    create_line_notification_link_code(
        app_user_id,
        _notification_link_code_hash(code),
        expires_at,
    )

    message = f"通知連携 {code}"
    return jsonify({
        "ok": True,
        "message": message,
        "deep_link": build_line_official_account_message_url(message),
        "expires_in_minutes": ttl_minutes,
    })


@link_bp.route("/notification-status", methods=["GET"])
def notification_status():
    app_user_id = (session.get("line_user_id") or "").strip()
    if not app_user_id:
        return jsonify({
            "ok": False,
            "linked": False,
            "message": "利用者情報を確認できませんでした。",
        }), 401
    if not app_user_id.startswith("anon_"):
        return jsonify({
            "ok": True,
            "linked": True,
            "auth_mode": "line",
        })

    link = get_line_notification_link(app_user_id)
    profile = {}
    if link and request.args.get("include_profile", "") == "1":
        profile = get_line_user_profile(
            link.get("line_user_id", "")
        ) or {}

    return jsonify({
        "ok": True,
        "linked": link is not None,
        "auth_mode": "guest",
        "profile": profile,
    })


@link_bp.route("/session", methods=["GET"])
def session_status():
    line_user_id = (session.get("line_user_id") or "").strip()
    return jsonify({
        "ok": bool(line_user_id),
        "line_user_id": line_user_id,
        "auth_mode": (
            "guest" if line_user_id.startswith("anon_") else "line"
        ) if line_user_id else "",
    })


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
