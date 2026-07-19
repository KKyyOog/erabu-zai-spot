import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app, request, session


VERIFY_ID_TOKEN_URL = "https://api.line.me/oauth2/v2.1/verify"


class LineAuthError(Exception):
    pass


def _safe_line_error_text(value, max_length=300):
    return " ".join(str(value or "").split())[:max_length]


def _log_verification_http_error(exc):
    line_error = ""
    description = ""

    try:
        response_body = exc.read().decode("utf-8", errors="replace")
        error_payload = json.loads(response_body)
        if isinstance(error_payload, dict):
            line_error = _safe_line_error_text(error_payload.get("error"))
            description = _safe_line_error_text(
                error_payload.get("error_description")
            )
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    request_id = ""
    if exc.headers:
        request_id = _safe_line_error_text(
            exc.headers.get("x-line-request-id", ""), max_length=100
        )

    current_app.logger.warning(
        "[LINE AUTH] ID token rejected status=%s error=%s description=%s request_id=%s",
        exc.code,
        line_error or "unknown",
        description or "not_provided",
        request_id or "not_provided",
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
    return (data.get("idToken") or data.get("id_token") or "").strip()


def verify_id_token(id_token, expected_user_id=""):
    if not id_token:
        raise LineAuthError("LINE ID token is required")

    channel_id = current_app.config.get("LINE_CHANNEL_ID", "")
    if not channel_id:
        raise LineAuthError("LINE_CHANNEL_ID is not configured")

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
        raise LineAuthError("LINE ID token verification failed") from exc
    except URLError as exc:
        current_app.logger.warning("[LINE AUTH] ID token verification unavailable: %s", exc.reason)
        raise LineAuthError("LINE ID token verification unavailable") from exc

    try:
        claims = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LineAuthError("LINE ID token verification returned invalid JSON") from exc

    user_id = claims.get("sub", "")
    if not user_id:
        raise LineAuthError("LINE ID token did not include a user ID")

    return claims


def require_verified_line_user_id(expected_user_id=""):
    token = extract_id_token()
    if token:
        claims = verify_id_token(token, expected_user_id=expected_user_id)
        return claims["sub"]

    session_user_id = (session.get("line_user_id") or "").strip()
    if session_user_id and (not expected_user_id or session_user_id == expected_user_id):
        return session_user_id

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
