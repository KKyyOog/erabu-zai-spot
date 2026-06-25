import os

import cloudinary
import cloudinary.uploader
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.services.sheets_service import (
    append_material,
    append_demolition_property,
    get_materials,
    get_material_by_id,
    get_demolition_properties,
    get_demolition_property_by_id,
    append_matching_history,
    delete_material,
    get_user_by_line_user_id,
)
from app.services.line_service import send_line_message

materials_bp = Blueprint("materials", __name__, url_prefix="/materials")


cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)


def _upload_image(image_file):
    allowed_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    ext = os.path.splitext(image_file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise ValueError("画像は png, jpg, jpeg, gif, webp 形式のみアップロードできます。")

    current_app.logger.info(
        "[materials] uploading image filename=%s content_type=%s",
        image_file.filename,
        getattr(image_file, "content_type", ""),
    )

    upload_result = cloudinary.uploader.upload(
        image_file,
        folder="erabu-zai-spot/uploads",
        resource_type="image",
    )
    return upload_result.get("secure_url", "")


def _sort_key_created_at(item):
    value = item.get("created_at", "")
    if not value:
        return "9999-12-31 23:59:59"
    return str(value)


def _build_listing_items(display_filter):
    items = []

    if display_filter in ("all", "materials"):
        for material in get_materials():
            items.append(
                {
                    "entry_type": "material",
                    "id": material.get("material_id", ""),
                    "title": material.get("title", ""),
                    "image_url": material.get("image_url", ""),
                    "location": material.get("location", ""),
                    "status": material.get("status", ""),
                    "created_at": material.get("created_at", ""),
                    "material_type": material.get("material_type", ""),
                    "size": material.get("size", ""),
                    "quantity": material.get("quantity", ""),
                    "condition": material.get("condition", ""),
                }
            )

    if display_filter in ("all", "demolitions"):
        for property_record in get_demolition_properties():
            items.append(
                {
                    "entry_type": "demolition",
                    "id": property_record.get("property_id", ""),
                    "title": property_record.get("property_name", ""),
                    "image_url": property_record.get("building_photo_url", ""),
                    "location": property_record.get("location", ""),
                    "status": property_record.get("status", ""),
                    "created_at": property_record.get("created_at", ""),
                    "registrant_type": property_record.get("registrant_type", ""),
                    "demolition_date": property_record.get("demolition_date", ""),
                    "demolition_contractor": property_record.get("demolition_contractor", ""),
                    "viewing_period": property_record.get("viewing_period", ""),
                    "building_use": property_record.get("building_use", ""),
                    "structure": property_record.get("structure", ""),
                    "floors": property_record.get("floors", ""),
                    "building_age": property_record.get("building_age", ""),
                    "condition_evaluation": property_record.get("condition_evaluation", ""),
                }
            )

    return sorted(items, key=_sort_key_created_at)


def _resolve_line_user_id(form):
    for field_name in ("line_user_id", "user_id", "userid"):
        value = (form.get(field_name) or "").strip()
        if value:
            return value
    return ""


def _send_provider_notification(provider_line_user_id, message, log_context):
    if not provider_line_user_id or provider_line_user_id.startswith("anon_"):
        return False

    try:
        sent = send_line_message(provider_line_user_id, message)
        if not sent:
            current_app.logger.warning("[%s] LINE notification was not sent", log_context)
        return sent
    except Exception:
        current_app.logger.exception("[%s] LINE notification failed", log_context)
        return False


def _public_user_summary(line_user_id):
    user = get_user_by_line_user_id(line_user_id)
    if not user:
        return "登録情報: 未登録"

    return "\n".join(
        [
            f"名前: {user.get('display_name', '未登録')}",
            f"拠点住所: {user.get('address', '未登録')}",
        ]
    )


@materials_bp.route("/register", methods=["GET"])
def register():
    return render_template("materials/register_select.html")


@materials_bp.route("/register/material", methods=["GET"])
def register_material():
    return render_template("materials/register.html")


@materials_bp.route("/register/demolition", methods=["GET"])
def register_demolition():
    return render_template("materials/demolition_register.html")


@materials_bp.route("/submit", methods=["POST"])
def submit():
    form = request.form.to_dict()
    image_file = request.files.get("image_file")
    final_image_url = form.get("image_url", "")

    required_fields = ["title", "material_type", "location"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register_material"))

    if image_file and image_file.filename:
        try:
            final_image_url = _upload_image(image_file)
            current_app.logger.info("[materials.submit] cloudinary upload success secure_url=%s", final_image_url)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("materials.register_material"))
        except Exception:
            current_app.logger.exception("[materials.submit] cloudinary upload failed")
            flash("画像のアップロードに失敗しました。画像なしで登録するか、再度お試しください。")
            return redirect(url_for("materials.register_material"))

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


@materials_bp.route("/demolitions/submit", methods=["POST"])
def submit_demolition():
    form = request.form.to_dict()
    image_file = request.files.get("building_image_file")
    final_image_url = form.get("building_photo_url", "")

    required_fields = ["property_name", "location", "registrant_type"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register_demolition"))

    if image_file and image_file.filename:
        try:
            final_image_url = _upload_image(image_file)
            current_app.logger.info("[demolitions.submit] cloudinary upload success secure_url=%s", final_image_url)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("materials.register_demolition"))
        except Exception:
            current_app.logger.exception("[demolitions.submit] cloudinary upload failed")
            flash("画像のアップロードに失敗しました。画像なしで登録するか、再度お試しください。")
            return redirect(url_for("materials.register_demolition"))

    if not form.get("line_user_id"):
        form["line_user_id"] = ""
        form["display_name"] = ""

    form["building_photo_url"] = final_image_url
    append_demolition_property(form)
    flash("解体物件を登録しました。")
    return redirect(url_for("materials.list_materials"))


@materials_bp.route("/list", methods=["GET"])
def list_materials():
    display_filter = request.args.get("type", "all")
    if display_filter not in ("all", "materials", "demolitions"):
        display_filter = "all"

    items = _build_listing_items(display_filter)
    return render_template(
        "materials/list.html",
        items=items,
        display_filter=display_filter,
    )


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
    requester_line_user_id = _resolve_line_user_id(request.form)
    message = request.form.get("message", "")

    material = get_material_by_id(material_id)
    if not material:
        return "指定された材が見つかりません。", 404

    match_id = append_matching_history(
        {
            "material_id": material_id,
            "provider_user_id": material.get("line_user_id", ""),
            "requester_user_id": requester_line_user_id,
            "action": "欲しい",
            "message": message,
            "status": "未対応",
        },
        match_type="material",
    )

    provider_line_user_id = material.get("line_user_id", "")
    _send_provider_notification(
        provider_line_user_id,
        "\n".join(
            [
                "【えらぶ材すぽっと】",
                f"登録した材「{material.get('title', '')}」に欲しい通知が届きました。",
                "",
                _public_user_summary(requester_line_user_id),
                f"メッセージ: {message or 'なし'}",
                "",
                "連絡先を共有する場合は、マイページのマッチング履歴から共有してください。",
                url_for("users.me", _external=True),
                f"match_id: {match_id}",
            ]
        ),
        "materials.interest",
    )

    flash("欲しい通知を送信しました。")
    return redirect(url_for("materials.list_materials"))


@materials_bp.route("/demolitions/visit-interest", methods=["POST"])
def visit_interest():
    property_id = request.form.get("property_id")
    requester_line_user_id = _resolve_line_user_id(request.form)

    property_record = get_demolition_property_by_id(property_id)
    if not property_record:
        return "指定された解体物件が見つかりません。", 404

    match_id = append_matching_history(
        {
            "property_id": property_id,
            "provider_user_id": property_record.get("line_user_id", ""),
            "requester_user_id": requester_line_user_id,
            "action": "見学したい",
            "message": f"解体物件「{property_record.get('property_name', '')}」の見学希望",
            "status": "未対応",
        },
        match_type="viewing",
    )

    provider_line_user_id = property_record.get("line_user_id", "")
    _send_provider_notification(
        provider_line_user_id,
        "\n".join(
            [
                "【えらぶ材すぽっと】",
                f"解体物件「{property_record.get('property_name', '')}」に見学希望が届きました。",
                "",
                _public_user_summary(requester_line_user_id),
                "",
                "連絡先を共有する場合は、マイページのマッチング履歴から共有してください。",
                url_for("users.me", _external=True),
                f"match_id: {match_id}",
            ]
        ),
        "demolitions.visit_interest",
    )

    flash("見学希望を送信しました。")
    return redirect(url_for("materials.list_materials", type=request.form.get("return_type", "all")))
