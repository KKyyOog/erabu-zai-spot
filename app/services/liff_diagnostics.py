"""Shared allowlist for client diagnostics; arbitrary strings never reach logs."""

import math


DIAGNOSTIC_SCHEMA = {
    "events": """
        browser.resource_load_failed browser.javascript_error browser.unhandled_rejection
        liff.sdk_loaded liff.sdk_load_failed liff.sdk_load_timeout
        page.head_initialized page.dom_ready page.skeleton_timeout
        page.initialization_started page.initialization_succeeded page.initialization_failed
        auth.restart_requested auth.session_cache_miss auth.session_cache_hit
        auth.session_cache_failed auth.flow_started auth.login_required
        auth.id_token_unavailable auth.profile_resolved auth.server_link_failed
        auth.server_link_succeeded auth.flow_succeeded
        liff.initialization_started liff.initialization_skipped liff.initialization_reused
        liff.initialization_succeeded liff.initialization_failed liff.profile_retrieved
        liff.server_auth_failed liff.server_auth_succeeded liff.unhandled_initialization_failure
        friendship.api_unavailable friendship.check_started friendship.api_succeeded
        friendship.sync_succeeded friendship.check_failed friendship.server_cache_loaded
        friendship.server_cache_failed friendship.request_started friendship.request_closed
        friendship.request_failed user_registration.cache_hit user_registration.loaded
        profile.load_started profile.load_response
    """.split(),
    "booleans": """
        loginEnabled requireLogin hasLiff inClient isLoggedIn initialized online
        liffIdPresent userIdPresent displayNamePresent idTokenPresent friendFlag
        registered serverCacheHit sessionPresent cacheValid migratedGuestData
        forceRefresh redirectIfLoggedOut cached exists ok
    """.split(),
    "numbers": """
        durationMs timeoutMs httpStatus expiresInSeconds liffIdLength line column
    """.split(),
    "enums": {
        "authMode": ["line", "guest"],
        "visibilityState": ["visible", "hidden", "prerender"],
        "errorName": ["Error", "TypeError", "SyntaxError", "ReferenceError", "AbortError", "TimeoutError"],
        "errorCode": ["INIT_FAILED", "INVALID_CONFIG", "INVALID_ARGUMENT", "UNAUTHORIZED", "FORBIDDEN"]
            + [str(code) for code in (400, 401, 403, 404, 429, 500, 502, 503, 504)]
            + [f"HTTP_{code}" for code in (400, 401, 403, 404, 429, 500, 502, 503, 504)],
        "reason": ["login_disabled", "liff_id_missing", "sdk_unavailable"],
        "element": ["SCRIPT", "LINK", "IMG"],
    },
}


def sanitize_details(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in DIAGNOSTIC_SCHEMA["booleans"]:
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key in DIAGNOSTIC_SCHEMA["numbers"]:
        number = value.get(key)
        if type(number) in (int, float) and 0 <= number <= 86400000 and math.isfinite(number):
            result[key] = number
    for key, allowed in DIAGNOSTIC_SCHEMA["enums"].items():
        if key in value:
            result[key] = value[key] if isinstance(value[key], str) and value[key] in allowed else "[redacted]"
    if "errorMessage" in value:
        result["errorMessage"] = "[redacted]"
    return result
