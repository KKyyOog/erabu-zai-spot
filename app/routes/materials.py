import os
from uuid import uuid4

import cloudinary
import cloudinary.uploader
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.services.sheets_service import (
    append_material,
    get_materials,
    get_material_by_id,
    append_matching_history,
    delete_material,
)
from app.services.line_service import send_line_message

materials_bp = Blueprint("materials", __name__, url_prefix="/materials")


cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)


@materials_bp.route("/register", methods=["GET"])
def register():
    return render_template("materials/register.html")


@materials_bp.route("/submit", methods=["POST"])
def submit():
    form = request.form.to_dict()
    image_file = request.files.get("image_file")
    final_image_url = form.get("image_url", "")

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

        current_app.logger.info(
            "[materials.submit] uploading image filename=%s content_type=%s",
            image_file.filename,
            getattr(image_file, "content_type", ""),
        )

        try:
            upload_result = cloudinary.uploader.upload(
                image_file,
                folder="erabu-zai-spot/uploads",
                resource_type="image",
            )
            final_image_url = upload_result.get("secure_url", "")
            current_app.logger.info(
                "[materials.submit] cloudinary upload success secure_url=%s public_id=%s",
                final_image_url,
                upload_result.get("public_id", ""),
            )
        except Exception:
            current_app.logger.exception("[materials.submit] cloudinary upload failed")
            flash("画像のアップロードに失敗しました。画像なしで登録するか、再度お試しください。")
            return redirect(url_for("materials.register"))

    if not form.get("line_user_id"):
        form["line_user_id"] = ""
        form["display_name"] = ""

    form["image_url"] = final_image_url
    current_app.logger.info(
        "[materials.submit] final image_url before save=%s line_user_id=%s title=%s",
        form.get("image_url", ""),
        form.get("line_user_id", ""),
        form.get("title", ""),
    )

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


@materials_bp.route("/<material_id>/delete", methods=["POST"])
def delete(material_id):
    line_user_id = request.form.get("line_user_id", "")
    if delete_material(material_id):
        flash("材登録を削除しました。")
    else:
        flash("材登録の削除に失敗しました。")

    if line_user_id:
        return redirect(url_for("users.detail", line_user_id=line_user_id))
    return redirect(url_for("materials.list_materials"))


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