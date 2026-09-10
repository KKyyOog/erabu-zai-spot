import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app, has_request_context, request, session


VERIFY_ID_TOKEN_URL = "https://api.line.me/oauth2/v2.1/verify"


class LineAuthError(Exception):
    pass


class LineAuthUnavailable(Exception):
    """Temporary verification failure; must not be treated as invalid credentials."""


def _log_auth_event(event, started_at=None, warning=False):
    trace = request.headers.get("X-LIFF-Trace-ID", "") if has_request_context() else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", trace):
        trace = "none"
    log = current_app.logger.warning if warning else current_app.logger.info
    if warning or current_app.config.get("LIFF_DEBUG_LOGGING", False):
        log("[LINE AUTH] event=%s trace=%s duration_ms=%d", event, trace,
            round((time.perf_counter() - started_at) * 1000) if started_at is not None else 0)


def _log_verification_http_error(exc):
    # Upstream descriptions may echo credentials. Record only the HTTP status.
    current_app.logger.warning(
        "[LINE AUTH] verification_http_error status=%s",
        exc.code,
    )


def extract_id_token(req=None):
    req = req or request

    token = req.headers.get("X-Line-ID-Token", "").strip()
    if token:
        return token

    auth_header = req.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    if req.form:
        token = (req.form.get("id_token") or req.form.get("idToken") or "").strip()
        if token:
            return token

    data = req.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise LineAuthError("JSON object is required")
    token = data.get("idToken") or data.get("id_token") or ""
    if not isinstance(token, str):
        raise LineAuthError("LINE ID token must be a string")
    return token.strip()


def verify_id_token(id_token, expected_user_id=""):
    started_at = time.perf_counter()
    if not id_token:
        raise LineAuthError("LINE ID token is required")

    channel_id = current_app.config.get("LINE_CHANNEL_ID", "")
    if not channel_id:
        _log_auth_event("verification_not_configured", started_at, warning=True)
        raise LineAuthUnavailable("LINE_CHANNEL_ID is not configured")

    payload = {
        "id_token": id_token,
        "client_id": channel_id,
    }
    if expected_user_id:
        payload["user_id"] = expected_user_id

    request_body = urlencode(payload).encode("utf-8")
    verify_request = Request(
        VERIFY_ID_TOKEN_URL,
        data=request_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(verify_request, timeout=5) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        _log_verification_http_error(exc)
        if exc.code == 429 or exc.code >= 500:
            _log_auth_event("verification_unavailable", started_at, warning=True)
            raise LineAuthUnavailable("LINE verification is temporarily unavailable") from exc
        _log_auth_event("verification_rejected", started_at, warning=True)
        raise LineAuthError("LINE ID token verification failed") from exc
    except (URLError, OSError) as exc:
        _log_auth_event("verification_unavailable", started_at, warning=True)
        raise LineAuthUnavailable("LINE ID token verification unavailable") from exc
    except UnicodeDecodeError as exc:
        _log_auth_event("verification_invalid_json", started_at, warning=True)
        raise LineAuthUnavailable("LINE verification returned invalid encoding") from exc

    try:
        claims = json.loads(response_body)
    except json.JSONDecodeError as exc:
        _log_auth_event("verification_invalid_json", started_at, warning=True)
        raise LineAuthUnavailable("LINE ID token verification returned invalid JSON") from exc

    if not isinstance(claims, dict):
        _log_auth_event("verification_invalid_claims", started_at, warning=True)
        raise LineAuthUnavailable("LINE ID token verification returned invalid claims")
    user_id = claims.get("sub", "")
    if not isinstance(user_id, str) or not user_id.strip():
        _log_auth_event("verification_missing_subject", started_at, warning=True)
        raise LineAuthError("LINE ID token did not include a user ID")
    if expected_user_id and user_id != expected_user_id:
        _log_auth_event("verification_user_mismatch", started_at, warning=True)
        raise LineAuthError("LINE ID token user mismatch")

    _log_auth_event("verification_succeeded", started_at)
    return claims


def session_identity_is_fresh(max_age=None):
    user_id = session.get("line_user_id", "")
    if not user_id:
        return False
    if user_id.startswith("anon_"):
        return not current_app.config.get("LINE_LOGIN_ENABLED", True)
    try:
        age = time.time() - int(session.get("line_authenticated_at", 0))
    except (TypeError, ValueError):
        return False
    limit = max_age if max_age is not None else current_app.config["LINE_SESSION_SECONDS"]
    return 0 <= age < max(1, int(limit))


def require_verified_line_user_id(expected_user_id=""):
    session_user_id = (session.get("line_user_id") or "").strip()
    if session_identity_is_fresh() and (not expected_user_id or session_user_id == expected_user_id):
        _log_auth_event("session_reused")
        return session_user_id

    token = extract_id_token()
    if token:
        claims = verify_id_token(token, expected_user_id=expected_user_id)
        session["line_user_id"] = claims["sub"]
        session["line_authenticated_at"] = int(time.time())
        session.permanent = False
        return claims["sub"]

    _log_auth_event("credentials_missing", warning=True)
    raise LineAuthError("LINE ID token is required")


def resolve_verified_line_user_id(expected_user_id="", allow_anonymous=False):
    token = extract_id_token()
    if token:
        claims = verify_id_token(token, expected_user_id=expected_user_id)
        return claims["sub"]

    if allow_anonymous and not expected_user_id:
        return ""

    if allow_anonymous and not current_app.config.get("SECURITY_REQUIRE_LINE_ID_TOKEN", True):
        return expected_user_id

    raise LineAuthError("LINE ID token is required")
