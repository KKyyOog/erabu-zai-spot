from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash

from app.services.sheets_service import (
    append_user,
    get_user_by_line_user_id,
    get_materials_by_line_user_id,
    get_matching_history_by_user,
    update_user,
)

users_bp = Blueprint("users", __name__, url_prefix="/users")


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


@users_bp.route("/register", methods=["GET"])
def register():
    return render_template("users/register.html")


@users_bp.route("/submit", methods=["POST"])
def submit():
    form = request.form.to_dict()
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

    line_user_id = append_user(form)
    flash("ユーザー情報を登録しました。")
    return redirect(url_for("users.detail", line_user_id=line_user_id))


@users_bp.route("/check/<line_user_id>", methods=["GET"])
def check(line_user_id):
    user = get_user_by_line_user_id(line_user_id)
    return jsonify({"exists": user is not None})


@users_bp.route("/<line_user_id>", methods=["GET"])
def detail(line_user_id):
    user = get_user_by_line_user_id(line_user_id)
    user_exists = user is not None

    if not user:
        user = {
            "line_user_id": line_user_id,
            "display_name": "",
            "address": "",
            "transport_info": "",
            "created_at": "",
        }

    materials = get_materials_by_line_user_id(line_user_id)
    matching_history = get_matching_history_by_user(line_user_id)

    return render_template(
        "users/detail.html",
        user=user,
        user_exists=user_exists,
        materials=materials,
        matching_history=matching_history,
    )


@users_bp.route("/<line_user_id>/edit", methods=["GET"])
def edit(line_user_id):
    user = get_user_by_line_user_id(line_user_id)
    if not user:
        return "指定されたユーザーが見つかりません。", 404
    return render_template("users/edit.html", user=user)


@users_bp.route("/<line_user_id>/update", methods=["POST"])
def update_profile(line_user_id):
    form = request.form.to_dict()
    resolved_user_id = _resolve_user_id(form, line_user_id)
    if not resolved_user_id or resolved_user_id.lower() == "me":
        flash("LINE user ID を取得できませんでした。画面を開き直してください。")
        return redirect(url_for("users.detail", line_user_id=line_user_id))

    form["line_user_id"] = resolved_user_id
    form["user_id"] = resolved_user_id

    required_fields = ["display_name", "address", "transport_info"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("users.detail", line_user_id=resolved_user_id))


@users_bp.route("/me", methods=["GET"])
def me():
    # Render a page that will obtain LINE profile and then request server-side
    # whether a record exists; the page will render the form inline.
    return render_template("users/me.html")


@users_bp.route("/me/data", methods=["POST"])
def me_data():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("userId") or data.get("line_user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "message": "userId is required"}), 400

    user = get_user_by_line_user_id(user_id)
    if user:
        return jsonify({"ok": True, "exists": True, "user": user})
    else:
        return jsonify({"ok": True, "exists": False})

    result = update_user(resolved_user_id, form)
    flash_message = "ユーザー情報を更新しました。"

    if result:
        flash(flash_message)
        return redirect(url_for("users.detail", line_user_id=resolved_user_id))
    else:
        flash("ユーザー情報の保存に失敗しました。")
        return redirect(url_for("users.detail", line_user_id=resolved_user_id))
