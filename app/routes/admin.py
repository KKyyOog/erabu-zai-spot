from flask import Blueprint, abort, current_app, render_template, request, redirect, session, url_for, flash

from app.services.line_auth_service import session_identity_is_fresh
from app.services.admin_service import dashboard, change_post_status
from app.services import db_service as db
from sqlalchemy import select

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _is_admin():
    admin_user_id = current_app.config.get("ADMIN_LINE_USER_ID", "")
    return bool(
        admin_user_id and session.get("line_user_id") == admin_user_id
        and session_identity_is_fresh(current_app.config["ADMIN_SESSION_SECONDS"])
    )


@admin_bp.route("/", methods=["GET"])
def index():
    if not _is_admin():
        return render_template("admin/login.html"), 401

    kind = "demolition" if request.args.get("kind") == "demolition" else "material"
    query = request.args.get("q", "").strip()[:100]
    status = request.args.get("status", "")
    allowed = ("登録済み", "受付終了", "削除済み") if kind == "demolition" else ("active", "closed", "expired", "削除済み")
    if status not in allowed:
        status = ""
    page = max(1, min(request.args.get("page", 1, type=int), 100000))
    response = current_app.make_response(render_template("admin/operations.html", kind=kind, query=query, page=page, status=status,
        **dashboard(kind, query, page, status)))
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/materials/status", methods=["POST"])
def update_status():
    if not _is_admin():
        abort(403)

    material_id = request.form.get("material_id")
    status = request.form.get("status")

    if not material_id or status not in ("active", "closed"):
        flash("material_id または status が不足しています。")
        return redirect(url_for("admin.index"))

    updated = change_post_status("material", material_id, status, session["line_user_id"])
    flash("ステータスを更新しました。" if updated else "対象の投稿が見つかりません。")
    return redirect(url_for("admin.index"))


@admin_bp.route("/posts/status", methods=["POST"])
def post_status():
    if not _is_admin():
        abort(403)
    kind = request.form.get("kind")
    if kind not in ("material", "demolition"):
        abort(400)
    changed = change_post_status(kind, request.form.get("entry_id"), request.form.get("status"), session["line_user_id"])
    flash("掲載状態を更新しました。" if changed else "対象または状態を確認してください。")
    return redirect(url_for("admin.index", kind=kind))


@admin_bp.route("/reports/<report_id>/resolve", methods=["POST"])
def resolve_report(report_id):
    if not _is_admin():
        abort(403)
    with db._engine().begin() as conn:
        report = conn.execute(select(db.operations.c.event_id).where(
            db.operations.c.event_id == report_id, db.operations.c.kind == "report")).scalar()
        if not report:
            abort(404)
        db.record_operation(conn, "report_resolution", report_id, session["line_user_id"], "確認済み")
    flash("通報を確認済みにしました。")
    return redirect(url_for("admin.index"))
