import time
from collections import OrderedDict
from threading import RLock

from flask import current_app

from app.services.db_service import get_me_profile_by_line_user_id


_profile_cache = OrderedDict()
_profile_cache_lock = RLock()


def _cache_ttl_seconds():
    return max(0, int(current_app.config.get("USER_INFO_CACHE_SECONDS", 600)))


def _cache_max_entries():
    return max(1, int(current_app.config.get("USER_INFO_CACHE_MAX_ENTRIES", 1000)))


def _copy_snapshot(snapshot):
    if not snapshot:
        return None, None
    user, contact_card = snapshot
    return dict(user) if user else None, dict(contact_card) if contact_card else None


def get_user_profile_snapshot(line_user_id, force_refresh=False):
    """Return (user, contact_card, cache_hit) without caching missing users."""
    if not line_user_id:
        return None, None, False

    now = time.monotonic()
    with _profile_cache_lock:
        cached = _profile_cache.get(line_user_id)
        if cached and not force_refresh:
            expires_at, snapshot = cached
            if expires_at > now:
                _profile_cache.move_to_end(line_user_id)
                user, contact_card = _copy_snapshot(snapshot)
                return user, contact_card, True
            _profile_cache.pop(line_user_id, None)

    user, contact_card = get_me_profile_by_line_user_id(line_user_id)
    if user:
        store_user_profile_snapshot(line_user_id, user, contact_card)
    else:
        invalidate_user_profile_cache(line_user_id)
    return user, contact_card, False


def store_user_profile_snapshot(line_user_id, user, contact_card=None):
    if not line_user_id or not user:
        invalidate_user_profile_cache(line_user_id)
        return

    ttl_seconds = _cache_ttl_seconds()
    if ttl_seconds <= 0:
        invalidate_user_profile_cache(line_user_id)
        return

    snapshot = (dict(user), dict(contact_card) if contact_card else None)
    with _profile_cache_lock:
        _profile_cache[line_user_id] = (time.monotonic() + ttl_seconds, snapshot)
        _profile_cache.move_to_end(line_user_id)
        while len(_profile_cache) > _cache_max_entries():
            _profile_cache.popitem(last=False)


def refresh_user_profile_cache(line_user_id):
    return get_user_profile_snapshot(line_user_id, force_refresh=True)


def invalidate_user_profile_cache(line_user_id):
    if not line_user_id:
        return
    with _profile_cache_lock:
        _profile_cache.pop(line_user_id, None)


def clear_user_profile_cache():
    """Clear process-local cache. Primarily used during tests and maintenance."""
    with _profile_cache_lock:
        _profile_cache.clear()
