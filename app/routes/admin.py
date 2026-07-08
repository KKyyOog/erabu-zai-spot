from flask import Blueprint, abort, current_app, render_template, request, redirect, session, url_for, flash

from app.services.db_service import get_materials, update_material_status

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _is_admin():
    admin_user_id = current_app.config.get("ADMIN_LINE_USER_ID", "")
    return bool(admin_user_id and session.get("line_user_id") == admin_user_id)


@admin_bp.route("/", methods=["GET"])
def index():
    if not _is_admin():
        return render_template("admin/login.html"), 401

    materials = get_materials(include_all=True)
    return render_template("admin/index.html", materials=materials)


@admin_bp.route("/materials/status", methods=["POST"])
def update_status():
    if not _is_admin():
        abort(403)

    material_id = request.form.get("material_id")
    status = request.form.get("status")

    if not material_id or not status:
        flash("material_id または status が不足しています。")
        return redirect(url_for("admin.index"))

    update_material_status(material_id, status)
    flash("ステータスを更新しました。")
    return redirect(url_for("admin.index"))
