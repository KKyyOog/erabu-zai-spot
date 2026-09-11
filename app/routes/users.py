import time

from flask import Blueprint, abort, jsonify, make_response, render_template, request, redirect, url_for, flash, session

from app.services.db_service import (
    append_user,
    get_demolition_properties_by_line_user_id,
    get_user_by_line_user_id,
    get_materials_by_line_user_id,
    get_matching_history_by_user,
    get_contact_card_by_user,
    get_me_profile_by_line_user_id,
    record_contact_share,
    get_matching_history_by_id,
    contact_card_version,
    upsert_contact_card,
    update_matching_status,
    update_user,
)
from app.services.line_service import send_line_message
from app.services.notification_service import deliver_notification
from app.services.line_auth_service import LineAuthError, require_verified_line_user_id
from app.services.user_cache_service import (
    get_user_profile_snapshot,
    refresh_user_profile_cache,
)
from app.validation import first_overlong_field

users_bp = Blueprint("users", __name__, url_prefix="/users")


@users_bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response

ME_DATA_CACHE_SECONDS = 20
_me_data_cache = {}

USER_FIELD_LIMITS = {
    "display_name": 100,
    "business_name": 200,
    "user_category": 100,
    "area": 100,
    "address": 200,
    "transport_info": 2000,
    "contact_display_name": 100,
    "contact_method": 50,
    "contact_value": 300,
    "contact_available_time": 100,
    "contact_message": 1000,
}

MATCH_STATUS_OPTIONS = ("未対応", "連絡・調整中", "成立", "辞退")


def _reject_overlong_user_input(form):
    invalid = first_overlong_field(form, USER_FIELD_LIMITS)
    if not invalid:
        return False
    field, max_length = invalid
    flash(f"入力が長すぎます（{field}: 最大{max_length}文字）。")
    return True


def _get_cached_me_data(line_user_id, scope):
    cached = _me_data_cache.get((line_user_id, scope))
    if not cached:
        return None

    expires_at, payload = cached
    if expires_at <= time.time():
        _me_data_cache.pop((line_user_id, scope), None)
        return None

    return payload


def _set_cached_me_data(line_user_id, scope, payload):
    _me_data_cache[(line_user_id, scope)] = (time.time() + ME_DATA_CACHE_SECONDS, payload)


def _clear_me_data_cache(line_user_id):
    if line_user_id:
        for cache_key in list(_me_data_cache):
            if isinstance(cache_key, tuple) and cache_key[0] == line_user_id:
                _me_data_cache.pop(cache_key, None)


def _resolve_user_id(form, route_user_id=""):
    for candidate in (
        form.get("line_user_id"),
        form.get("user_id"),
        form.get("userid"),
        route_user_id,
    ):
        if candidate and candidate.strip() and candidate.strip().lower() != "me":
            return candidate.strip()
    return route_user_id.strip()


def _save_contact_card_if_present(line_user_id, form):
    card_fields = (
        "contact_display_name",
        "contact_method",
        "contact_value",
        "contact_available_time",
        "contact_message",
    )
    if any(form.get(field) for field in card_fields):
        return upsert_contact_card(line_user_id, form)
    return None


@users_bp.route("/register", methods=["GET"])
def register():
    return redirect(url_for("users.me"))


@users_bp.route("/submit", methods=["POST"])
def submit():
    form = request.form.to_dict()
    if _reject_overlong_user_input(form):
        return redirect(url_for("users.me"))
    if not form.get("line_user_id") and form.get("user_id"):
        form["line_user_id"] = form["user_id"]
    if not form.get("line_user_id") and form.get("userid"):
        form["line_user_id"] = form["userid"]
    if not form.get("user_id") and form.get("line_user_id"):
        form["user_id"] = form["line_user_id"]
    if not form.get("userid") and form.get("line_user_id"):
        form["userid"] = form["line_user_id"]

    required_fields = ["display_name", "address", "transport_info"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("users.register"))

    try:
        line_user_id = require_verified_line_user_id(form.get("line_user_id", ""))
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    form["line_user_id"] = line_user_id
    form["user_id"] = line_user_id
    form["userid"] = line_user_id

    line_user_id = append_user(form)
    _save_contact_card_if_present(line_user_id, form)
    _clear_me_data_cache(line_user_id)
    refresh_user_profile_cache(line_user_id)
    flash("ユーザー情報を登録しました。")
    return redirect(url_for("users.me"))


@users_bp.route("/check/<line_user_id>", methods=["GET"])
def check(line_user_id):
    try:
        verified_user_id = require_verified_line_user_id(line_user_id)
    except LineAuthError:
        return jsonify({"exists": False, "message": "LINE authentication failed"}), 401

    user, _, cache_hit = get_user_profile_snapshot(verified_user_id)
    response = jsonify({"exists": user is not None, "cached": cache_hit})
    response.headers["Cache-Control"] = "no-store"
    return response


@users_bp.route("/<line_user_id>", methods=["GET"])
def detail(line_user_id):
    flash("Please use the LINE-authenticated my page.")
    return redirect(url_for("users.me"))

@users_bp.route("/<line_user_id>/edit", methods=["GET"])
def edit(line_user_id):
    flash("Please use the LINE-authenticated my page.")
    return redirect(url_for("users.me"))


@users_bp.route("/<line_user_id>/update", methods=["POST"])
def update_profile(line_user_id):
    form = request.form.to_dict()
    if _reject_overlong_user_input(form):
        return redirect(url_for("users.me"))
    resolved_user_id = _resolve_user_id(form, line_user_id)
    try:
        resolved_user_id = require_verified_line_user_id(resolved_user_id)
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))
    if not resolved_user_id or resolved_user_id.lower() == "me":
        flash("LINE user ID を取得できませんでした。画面を開き直してください。")
        return redirect(url_for("users.me"))

    form["line_user_id"] = resolved_user_id
    form["user_id"] = resolved_user_id
    form["userid"] = resolved_user_id

    required_fields = ["display_name", "address", "transport_info"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("users.me"))

    exists = get_user_by_line_user_id(resolved_user_id) is not None
    result = update_user(resolved_user_id, form)
    if result:
        _save_contact_card_if_present(resolved_user_id, form)
        _clear_me_data_cache(resolved_user_id)
        refresh_user_profile_cache(resolved_user_id)
    flash("ユーザー情報を更新しました。" if exists else "ユーザー情報を登録しました。")

    if result:
        return redirect(url_for("users.me"))

    flash("ユーザー情報の保存に失敗しました。")
    return redirect(url_for("users.me"))


@users_bp.route("/me", methods=["GET"])
def me():
    return render_template("users/me.html")


@users_bp.route("/me/data", methods=["POST"])
def me_data():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("userId") or data.get("line_user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "message": "userId is required"}), 400
    try:
        user_id = require_verified_line_user_id(user_id)
    except LineAuthError:
        return jsonify({
            "ok": False,
            "code": "line_token_invalid",
            "message": "LINE authentication failed",
        }), 401

    # A request carrying an ID token also bootstraps the authenticated session,
    # so the browser does not need a separate session-sync request first.
    session["line_user_id"] = user_id
    scope = (data.get("scope") or "all").strip().lower()
    if scope not in ("all", "profile", "activity"):
        return jsonify({"ok": False, "message": "invalid scope"}), 400

    force_refresh = data.get("refresh") is True
    if scope == "profile":
        user, contact_card, cache_hit = get_user_profile_snapshot(
            user_id,
            force_refresh=force_refresh,
        )
        payload = {
            "ok": True,
            "exists": user is not None,
            "user": user or {
                "line_user_id": user_id,
                "display_name": "",
                "business_name": "",
                "user_category": "",
                "area": "",
                "address": "",
                "transport_info": "",
            },
            "contact_card": contact_card or {},
            "cached": cache_hit,
        }
        return jsonify(payload)

    cached = None if force_refresh else _get_cached_me_data(user_id, scope)
    if cached:
        return jsonify(cached)

    if scope == "activity":
        payload = {
            "ok": True,
            "materials": get_materials_by_line_user_id(user_id),
            "demolition_properties": get_demolition_properties_by_line_user_id(user_id),
            "matching_history": get_matching_history_by_user(user_id),
        }
    else:
        user, contact_card = get_me_profile_by_line_user_id(user_id)
        payload = {
            "ok": True,
            "exists": user is not None,
            "user": user or {
                "line_user_id": user_id,
                "display_name": "",
                "business_name": "",
                "user_category": "",
                "area": "",
                "address": "",
                "transport_info": "",
            },
            "contact_card": contact_card or {},
        }
        if scope == "all":
            payload.update({
                "materials": get_materials_by_line_user_id(user_id),
                "demolition_properties": get_demolition_properties_by_line_user_id(user_id),
                "matching_history": get_matching_history_by_user(user_id),
            })

    _set_cached_me_data(user_id, scope, payload)
    return jsonify(payload)


@users_bp.route("/me/save", methods=["POST"])
def me_save():
    form = request.form.to_dict()
    if _reject_overlong_user_input(form):
        return redirect(url_for("users.me"))
    resolved_user_id = _resolve_user_id(form)
    try:
        resolved_user_id = require_verified_line_user_id(resolved_user_id)
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    if not resolved_user_id or resolved_user_id.lower() == "me":
        flash("LINE user ID を取得できませんでした。画面を開き直してください。")
        return redirect(url_for("users.me"))

    form["line_user_id"] = resolved_user_id
    form["user_id"] = resolved_user_id
    form["userid"] = resolved_user_id

    required_fields = ["display_name", "address", "transport_info"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("users.me"))

    exists = get_user_by_line_user_id(resolved_user_id) is not None
    result = update_user(resolved_user_id, form)
    if result:
        _save_contact_card_if_present(resolved_user_id, form)
        _clear_me_data_cache(resolved_user_id)
        refresh_user_profile_cache(resolved_user_id)

    if result:
        flash("ユーザー情報を更新しました。" if exists else "ユーザー情報を登録しました。")
    else:
        flash("ユーザー情報の保存に失敗しました。")

    return redirect(url_for("users.me", tab="profile"))


@users_bp.route("/matches/<match_type>/<match_id>/share-contact", methods=["GET", "POST"])
def share_contact(match_type, match_id):
    if match_type not in ("material", "request", "viewing"):
        flash("マッチ種別が不正です。")
        return redirect(url_for("users.me"))

    line_user_id = _resolve_user_id(request.form)
    try:
        line_user_id = require_verified_line_user_id(line_user_id)
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    if not line_user_id:
        flash("LINE user ID を取得できませんでした。")
        return redirect(url_for("users.me"))

    _, match = get_matching_history_by_id(match_id, match_type)
    if not match or line_user_id not in (match["provider_user_id"], match["requester_user_id"]):
        abort(404)
    target_id = match["requester_user_id"] if match["provider_user_id"] == line_user_id else match["provider_user_id"]
    card = get_contact_card_by_user(line_user_id)
    if request.method == "POST" and request.form.get("action") == "save_contact":
        if _reject_overlong_user_input(request.form) or not request.form.get("contact_value", "").strip():
            flash("連絡先を入力し、文字数をご確認ください。")
            return redirect(url_for("users.share_contact", match_type=match_type, match_id=match_id, edit="1"))
        upsert_contact_card(line_user_id, request.form)
        refresh_user_profile_cache(line_user_id)
        _clear_me_data_cache(line_user_id)
        return redirect(url_for("users.share_contact", match_type=match_type, match_id=match_id))
    if not card or not card.get("contact_value") or request.args.get("edit") == "1":
        target = get_user_by_line_user_id(target_id) or {}
        return render_template("users/share_contact.html", match=match, card=card or {}, editing=True,
            target_name=target.get("business_name") or target.get("display_name") or "相手")
    if request.method == "GET" or not request.form.get("contact_version"):
        target = get_user_by_line_user_id(target_id) or {}
        response = make_response(render_template("users/share_contact.html", match=match, card=card,
            target_name=target.get("business_name") or target.get("display_name") or "マッチ相手",
            contact_version=contact_card_version(card)))
        response.headers["Cache-Control"] = "no-store"
        return response

    share_result, error = record_contact_share(match_id, match_type, line_user_id, request.form["contact_version"])
    if error == "contact_card_changed":
        flash("連絡先が更新されています。内容をもう一度確認してください。")
        return redirect(url_for("users.share_contact", match_type=match_type, match_id=match_id))
    if error == "contact_card_missing":
        flash("連絡先カードを入力してから共有してください。")
        return redirect(url_for("users.me"))
    if error == "contact_card_inactive":
        flash("連絡先カードが共有停止中です。")
        return redirect(url_for("users.me"))
    if error:
        flash("連絡先カードの共有に失敗しました。")
        return redirect(url_for("users.me"))

    to_user_id = share_result.get("to_user_id", "")
    _clear_me_data_cache(line_user_id)
    _clear_me_data_cache(to_user_id)

    notification_sent = deliver_notification(share_result["contact_share_id"], sender=send_line_message)

    if notification_sent:
        flash("連絡先カードを共有し、相手へLINE通知を送信しました。")
    else:
        flash(
            "連絡先カードは共有履歴に保存しましたが、相手へのLINE通知に失敗しました。"
            "必要に応じて運営者へ連絡してください。"
        )
    return redirect(url_for("users.me", refresh="1", tab="matches", match=match_id))


@users_bp.route("/matches/<match_type>/<match_id>/status", methods=["POST"])
def update_match_status(match_type, match_id):
    if match_type not in ("material", "request", "viewing"):
        flash("マッチ種別が不正です。")
        return redirect(url_for("users.me", refresh="1", tab="matches"))

    status = (request.form.get("status") or "").strip()
    if status not in MATCH_STATUS_OPTIONS:
        flash("マッチング状態が不正です。")
        return redirect(url_for("users.me", refresh="1", tab="matches"))

    line_user_id = _resolve_user_id(request.form)
    try:
        line_user_id = require_verified_line_user_id(line_user_id)
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me", tab="matches"))

    updated_match = update_matching_status(
        match_id,
        match_type,
        line_user_id,
        status,
        expected_status=request.form.get("expected_status"),
        completion_action=request.form.get("completion_action", "keep"),
        expected_updated_at=request.form.get("expected_updated_at"),
    )
    if not updated_match:
        flash("状態が変更されたか、この操作を行えません。最新の内容を確認して、もう一度お試しください。")
        return redirect(url_for("users.me", refresh="1", tab="matches"))

    provider_user_id = updated_match.get("provider_user_id", "")
    requester_user_id = updated_match.get("requester_user_id", "")
    to_user_id = (
        requester_user_id
        if provider_user_id == line_user_id
        else provider_user_id
    )
    _clear_me_data_cache(provider_user_id)
    _clear_me_data_cache(requester_user_id)

    notification_sent = deliver_notification(updated_match["notification_id"], sender=send_line_message)

    status_label = {"成立": "完了", "辞退": "見送り", "連絡・調整中": "相談中", "未対応": "問い合わせ受付"}.get(status, status)
    if notification_sent:
        flash(f"問い合わせを「{status_label}」にして、相手へLINE通知を送信しました。")
    else:
        flash(
            f"問い合わせは「{status_label}」にしましたが、相手へのLINE通知に失敗しました。"
            "必要に応じて運営者へ連絡してください。"
        )
    return redirect(url_for("users.me", tab="matches", refresh="1", match=match_id))
