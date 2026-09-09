import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request, session

from app.services.db_service import (
    create_line_notification_link_code,
    get_line_friendship,
    get_line_notification_link,
    migrate_guest_identity,
    set_line_friendship,
)
from app.services.line_auth_service import LineAuthError, verify_id_token
from app.services.line_service import (
    build_line_official_account_message_url,
    get_line_user_profile,
)
from app.services.user_cache_service import (
    invalidate_user_profile_cache,
    refresh_user_profile_cache,
)

link_bp = Blueprint("link", __name__, url_prefix="/link")
logger = logging.getLogger(__name__)

NOTIFICATION_LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
NOTIFICATION_LINK_CODE_LENGTH = 10
LIFF_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LIFF_LOG_SENSITIVE_KEY_PARTS = (
    "authorization",
    "code",
    "email",
    "href",
    "idtoken",
    "lineuserid",
    "phone",
    "search",
    "token",
    "userid",
)


def _notification_link_code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _safe_log_text(value, limit=300):
    return str(value or "")[:limit].replace("\r", " ").replace("\n", " ")


def _session_user_log_key():
    line_user_id = (session.get("line_user_id") or "").strip()
    if not line_user_id:
        return "none"
    return hashlib.sha256(line_user_id.encode("utf-8")).hexdigest()[:12]


def _liff_trace_id(data=None):
    candidates = [
        request.headers.get("X-LIFF-Trace-ID", ""),
        (data or {}).get("traceId", "") if isinstance(data, dict) else "",
    ]
    for candidate in candidates:
        candidate = _safe_log_text(candidate, 64)
        if LIFF_TRACE_ID_PATTERN.fullmatch(candidate):
            return candidate
    return "none"


def _sanitize_liff_log_details(value, depth=0):
    if depth > 3:
        return "[depth-limited]"
    if isinstance(value, dict):
        result = {}
        for raw_key, raw_value in list(value.items())[:30]:
            key = _safe_log_text(raw_key, 80)
            normalized_key = key.lower().replace("-", "").replace("_", "")
            is_sensitive = (
                normalized_key in LIFF_LOG_SENSITIVE_KEY_PARTS
                or normalized_key.endswith(("email", "phone", "token", "userid"))
            )
            if is_sensitive and not isinstance(raw_value, bool):
                result[key] = "[redacted]"
            else:
                result[key] = _sanitize_liff_log_details(raw_value, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize_liff_log_details(item, depth + 1) for item in value[:10]]
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    return _safe_log_text(value)


@link_bp.route("/liff", methods=["POST"])
def liff_link():
    started_at = time.perf_counter()
    if not current_app.config.get("LINE_LOGIN_ENABLED", False):
        logger.warning(
            "[LIFF AUTH] rejected reason=disabled trace=%s duration_ms=%d",
            _liff_trace_id(),
            round((time.perf_counter() - started_at) * 1000),
        )
        return jsonify({
            "ok": False,
            "code": "line_login_disabled",
            "message": "LINE login is temporarily disabled",
        }), 503

    data = request.get_json(silent=True) or {}

    user_id = (data.get("userId") or "").strip()
    id_token = (data.get("idToken") or data.get("id_token") or "").strip()
    trace_id = _liff_trace_id(data)

    logger.info(
        "[LIFF AUTH] received trace=%s session_user=%s user_id_present=%s "
        "id_token_present=%s path=%s user_agent=%s",
        trace_id,
        _session_user_log_key(),
        bool(user_id),
        bool(id_token),
        request.path,
        request.headers.get("User-Agent", ""),
    )

    if not id_token:
        logger.warning(
            "[LIFF AUTH] rejected reason=missing_id_token trace=%s duration_ms=%d",
            trace_id,
            round((time.perf_counter() - started_at) * 1000),
        )
        return jsonify({"ok": False, "message": "idToken is required"}), 400

    try:
        claims = verify_id_token(id_token, expected_user_id=user_id)
    except LineAuthError as exc:
        session.pop("line_user_id", None)
        logger.warning(
            "[LIFF AUTH] rejected reason=invalid_token trace=%s error=%s duration_ms=%d",
            trace_id,
            _safe_log_text(exc),
            round((time.perf_counter() - started_at) * 1000),
        )
        return jsonify({
            "ok": False,
            "code": "line_token_invalid",
            "message": "LINE authentication failed",
        }), 401

    verified_user_id = (claims.get("sub") or "").strip()
    if not verified_user_id or (user_id and user_id != verified_user_id):
        session.pop("line_user_id", None)
        logger.warning(
            "[LIFF AUTH] rejected reason=user_mismatch trace=%s duration_ms=%d",
            trace_id,
            round((time.perf_counter() - started_at) * 1000),
        )
        return jsonify({
            "ok": False,
            "code": "line_user_mismatch",
            "message": "LINE authentication failed",
        }), 401

    legacy_guest_user_id = (session.get("legacy_guest_user_id") or session.get("line_user_id") or "").strip()
    migrated = False
    if legacy_guest_user_id.startswith("anon_"):
        migrated = migrate_guest_identity(
            legacy_guest_user_id,
            verified_user_id,
        )
        invalidate_user_profile_cache(legacy_guest_user_id)
        invalidate_user_profile_cache(verified_user_id)
        if migrated:
            refresh_user_profile_cache(verified_user_id)

    session.pop("legacy_guest_user_id", None)
    session["line_user_id"] = verified_user_id
    session["line_authenticated_at"] = int(time.time())
    session.permanent = False
    logger.info(
        "[LIFF AUTH] accepted trace=%s session_user=%s migrated_guest_data=%s duration_ms=%d",
        trace_id,
        _session_user_log_key(),
        migrated,
        round((time.perf_counter() - started_at) * 1000),
    )
    return jsonify({
        "ok": True,
        "line_user_id": verified_user_id,
        "migrated_guest_data": migrated,
    })


@link_bp.route("/guest", methods=["POST"])
def guest_link():
    if current_app.config.get("LINE_LOGIN_ENABLED", True):
        return jsonify({
            "ok": False,
            "code": "line_login_required",
            "message": "LINE login is required",
        }), 503

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
    session["line_authenticated_at"] = int(time.time())
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
        friendship = get_line_friendship(app_user_id)
        return jsonify({
            "ok": True,
            "linked": bool(friendship and friendship.get("is_friend")),
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


@link_bp.route("/friendship", methods=["GET", "POST"])
def friendship_status():
    started_at = time.perf_counter()
    trace_id = _liff_trace_id(request.get_json(silent=True) if request.is_json else None)
    line_user_id = (session.get("line_user_id") or "").strip()
    if not line_user_id or line_user_id.startswith("anon_"):
        logger.warning(
            "[LIFF FRIENDSHIP] rejected reason=authentication_required trace=%s "
            "session_user=%s duration_ms=%d",
            trace_id,
            _session_user_log_key(),
            round((time.perf_counter() - started_at) * 1000),
        )
        return jsonify({
            "ok": False,
            "message": "LINE authentication is required",
        }), 401

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("friendFlag"), bool):
            logger.warning(
                "[LIFF FRIENDSHIP] rejected reason=invalid_friend_flag trace=%s "
                "session_user=%s duration_ms=%d",
                trace_id,
                _session_user_log_key(),
                round((time.perf_counter() - started_at) * 1000),
            )
            return jsonify({
                "ok": False,
                "message": "friendFlag must be a boolean",
            }), 400
        set_line_friendship(line_user_id, data["friendFlag"])

    friendship = get_line_friendship(line_user_id)
    is_friend = bool(friendship and friendship.get("is_friend"))
    logger.info(
        "[LIFF FRIENDSHIP] completed method=%s trace=%s session_user=%s friend=%s duration_ms=%d",
        request.method,
        trace_id,
        _session_user_log_key(),
        is_friend,
        round((time.perf_counter() - started_at) * 1000),
    )
    return jsonify({
        "ok": True,
        "line_user_id": line_user_id,
        "friend": is_friend,
        "updated_at": friendship.get("updated_at", "") if friendship else "",
    })


@link_bp.route("/session", methods=["GET"])
def session_status():
    line_user_id = (session.get("line_user_id") or "").strip()
    authenticated_at = session.get("line_authenticated_at", 0)
    try:
        authenticated_at = int(authenticated_at)
    except (TypeError, ValueError):
        authenticated_at = 0
    cache_seconds = max(
        0,
        int(current_app.config.get("USER_INFO_CACHE_SECONDS", 600)),
    )
    cache_age_seconds = max(0, int(time.time()) - authenticated_at) if authenticated_at else None
    cache_valid = bool(
        line_user_id
        and authenticated_at
        and cache_age_seconds is not None
        and cache_age_seconds <= cache_seconds
    )
    response = jsonify({
        "ok": bool(line_user_id),
        "line_user_id": line_user_id,
        "auth_mode": (
            "guest" if line_user_id.startswith("anon_") else "line"
        ) if line_user_id else "",
        "cache_valid": cache_valid,
        "cache_expires_in": max(0, cache_seconds - cache_age_seconds)
        if cache_age_seconds is not None
        else 0,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@link_bp.route("/liff-debug", methods=["POST"])
def liff_debug():
    if not current_app.config.get("LIFF_DEBUG_LOGGING", False):
        return "", 204

    if request.content_length and request.content_length > 16 * 1024:
        return jsonify({"ok": False, "message": "log payload is too large"}), 413

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "message": "JSON object is required"}), 400
    event = _safe_log_text(data.get("event") or data.get("message") or "unknown", 120)
    level = _safe_log_text(data.get("level") or "info", 10).lower()
    if level not in ("debug", "info", "warning", "error"):
        level = "info"
    timestamp = _safe_log_text(data.get("timestamp"), 100)
    trace_id = _liff_trace_id(data)
    details = _sanitize_liff_log_details(data.get("details") or {})
    try:
        referer_path = urlsplit(request.headers.get("Referer", "")).path
    except ValueError:
        referer_path = ""

    log_method = logger.warning if level in ("warning", "error") else logger.info
    log_method(
        "[LIFF CLIENT] event=%s level=%s trace=%s client_timestamp=%s "
        "session_user=%s referer_path=%s details=%s user_agent=%s",
        event,
        level,
        trace_id,
        timestamp,
        _session_user_log_key(),
        _safe_log_text(referer_path, 200),
        json.dumps(details, ensure_ascii=False, separators=(",", ":")),
        _safe_log_text(request.headers.get("User-Agent", ""), 300),
    )

    return "", 204
