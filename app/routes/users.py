import time

from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash

from app.services.db_service import (
    append_user,
    get_user_by_line_user_id,
    get_materials_by_line_user_id,
    get_matching_history_by_user,
    get_contact_card_by_user,
    record_contact_share,
    upsert_contact_card,
    update_user,
)
from app.services.line_service import send_line_message
from app.services.line_auth_service import LineAuthError, require_verified_line_user_id
from app.validation import first_overlong_field

users_bp = Blueprint("users", __name__, url_prefix="/users")

ME_DATA_CACHE_SECONDS = 20
_me_data_cache = {}

USER_FIELD_LIMITS = {
    "display_name": 100,
    "address": 200,
    "transport_info": 2000,
    "contact_display_name": 100,
    "contact_method": 50,
    "contact_value": 300,
    "contact_available_time": 100,
    "contact_message": 1000,
}


def _reject_overlong_user_input(form):
    invalid = first_overlong_field(form, USER_FIELD_LIMITS)
    if not invalid:
        return False
    field, max_length = invalid
    flash(f"入力が長すぎます（{field}: 最大{max_length}文字）。")
    return True


def _get_cached_me_data(line_user_id):
    cached = _me_data_cache.get(line_user_id)
    if not cached:
        return None

    expires_at, payload = cached
    if expires_at <= time.time():
        _me_data_cache.pop(line_user_id, None)
        return None

    return payload


def _set_cached_me_data(line_user_id, payload):
    _me_data_cache[line_user_id] = (time.time() + ME_DATA_CACHE_SECONDS, payload)


def _clear_me_data_cache(line_user_id):
    if line_user_id:
        _me_data_cache.pop(line_user_id, None)


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


def _format_contact_share_message(share_result):
    card = share_result["card"]
    match = share_result["match"]
    entry_label = "材" if match.get("match_type") == "material" else "見学"
    lines = [
        "【えらぶ材すぽっと】",
        f"{entry_label}のマッチ相手が連絡先カードを共有しました。",
        "",
        f"表示名: {card.get('display_name', '')}",
        f"連絡方法: {card.get('contact_method', '')}",
        f"連絡先: {card.get('contact_value', '')}",
    ]
    if card.get("available_time"):
        lines.append(f"連絡しやすい時間: {card.get('available_time')}")
    if card.get("message"):
        lines.extend(["", card.get("message")])
    return "\n".join(lines)


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
    flash("ユーザー情報を登録しました。")
    return redirect(url_for("users.me"))


@users_bp.route("/check/<line_user_id>", methods=["GET"])
def check(line_user_id):
    try:
        verified_user_id = require_verified_line_user_id(line_user_id)
    except LineAuthError:
        return jsonify({"exists": False, "message": "LINE authentication failed"}), 401

    user = get_user_by_line_user_id(verified_user_id)
    return jsonify({"exists": user is not None})


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

    cached = _get_cached_me_data(user_id)
    if cached:
        return jsonify(cached)

    user = get_user_by_line_user_id(user_id)
    materials = get_materials_by_line_user_id(user_id)
    matching_history = get_matching_history_by_user(user_id)
    contact_card = get_contact_card_by_user(user_id) or {}
    if user:
        payload = {
            "ok": True,
            "exists": True,
            "user": user,
            "contact_card": contact_card,
            "materials": materials,
            "matching_history": matching_history,
        }
    else:
        payload = {
            "ok": True,
            "exists": False,
            "user": {
                "line_user_id": user_id,
                "display_name": "",
                "address": "",
                "transport_info": "",
            },
            "contact_card": contact_card,
            "materials": materials,
            "matching_history": matching_history,
        }

    _set_cached_me_data(user_id, payload)
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

    if result:
        flash("ユーザー情報を更新しました。" if exists else "ユーザー情報を登録しました。")
    else:
        flash("ユーザー情報の保存に失敗しました。")

    return redirect(url_for("users.me"))


@users_bp.route("/matches/<match_type>/<match_id>/share-contact", methods=["POST"])
def share_contact(match_type, match_id):
    if match_type not in ("material", "viewing"):
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

    share_result, error = record_contact_share(match_id, match_type, line_user_id)
    if error == "contact_card_missing":
        flash("連絡先カードを入力してから共有してください。")
        return redirect(url_for("users.me"))
    if error == "contact_card_inactive":
        flash("連絡先カードが共有停止中です。")
        return redirect(url_for("users.me"))
    if error:
        flash("連絡先カードの共有に失敗しました。")
        return redirect(url_for("users.me"))

    _clear_me_data_cache(line_user_id)

    to_user_id = share_result.get("to_user_id", "")
    if to_user_id and not to_user_id.startswith("anon_"):
        try:
            send_line_message(to_user_id, _format_contact_share_message(share_result))
        except Exception:
            pass

    flash("連絡先カードを共有しました。")
    return redirect(url_for("users.me"))
