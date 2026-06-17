import os
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.services.sheets_service import (
    append_material,
    get_materials,
    get_material_by_id,
    append_matching_history,
)
from app.services.line_service import send_line_message

materials_bp = Blueprint("materials", __name__, url_prefix="/materials")


@materials_bp.route("/register", methods=["GET"])
def register():
    return render_template("materials/register.html")


@materials_bp.route("/submit", methods=["POST"])
def submit():
    form = request.form.to_dict()
    image_file = request.files.get("image_file")

    required_fields = ["title", "material_type", "location"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register"))

    if image_file and image_file.filename:
        allowed_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        ext = os.path.splitext(image_file.filename)[1].lower()
        if ext not in allowed_extensions:
            flash("画像は png, jpg, jpeg, gif, webp 形式のみアップロードできます。")
            return redirect(url_for("materials.register"))

        filename = secure_filename(f"{uuid4().hex}{ext}")
        save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
        image_file.save(save_path)
        form["image_url"] = url_for(
            "static", filename=f"uploads/{filename}", _external=True
        )

    if not form.get("line_user_id"):
        form["line_user_id"] = ""
        form["display_name"] = ""

    append_material(form)
    flash("材を登録しました。")
    return redirect(url_for("materials.list_materials"))


@materials_bp.route("/list", methods=["GET"])
def list_materials():
    materials = get_materials()
    return render_template("materials/list.html", materials=materials)


@materials_bp.route("/<material_id>", methods=["GET"])
def detail(material_id):
    material = get_material_by_id(material_id)
    if not material:
        return "指定された材が見つかりません。", 404
    return render_template("materials/detail.html", material=material)


@materials_bp.route("/interest", methods=["POST"])
def interest():
    material_id = request.form.get("material_id")
    requester_line_user_id = request.form.get("line_user_id")
    message = request.form.get("message", "")

    material = get_material_by_id(material_id)
    if not material:
        return "指定された材が見つかりません。", 404

    append_matching_history(
        {
            "material_id": material_id,
            "provider_user_id": material.get("line_user_id", ""),
            "requester_user_id": requester_line_user_id,
            "action": "欲しい",
            "message": message,
            "status": "未対応",
        }
    )

    provider_line_user_id = material.get("line_user_id", "")
    if provider_line_user_id:
        send_line_message(
            provider_line_user_id,
            f"【えらぶ材すぽっと】\n登録した材「{material.get('title', '')}」に欲しい通知が届きました。\nメッセージ：{message or 'なし'}",
        )

    flash("欲しい通知を送信しました。")
    return redirect(url_for("materials.list_materials"))
