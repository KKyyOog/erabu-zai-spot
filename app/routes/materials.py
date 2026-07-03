import json
import os

import cloudinary
import cloudinary.uploader
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from app.services.db_service import (
    append_material,
    append_demolition_property,
    get_materials,
    get_material_by_id,
    get_demolition_properties,
    get_demolition_property_by_id,
    get_provider_shared_material_ids,
    append_matching_history,
    delete_material,
    get_user_by_line_user_id,
    update_material,
)
from app.services.line_service import send_line_message
from app.services.liff_service import liff_url_for

materials_bp = Blueprint("materials", __name__, url_prefix="/materials")

MATERIAL_TYPE_OPTIONS = [
    "木材",
    "金属",
    "建具",
    "家具",
    "石材・ブロック",
    "設備・配管",
    "その他",
]


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


def _upload_images(image_files):
    image_urls = []
    for image_file in image_files:
        if not image_file or not image_file.filename:
            continue
        image_url = _upload_image(image_file)
        if image_url:
            image_urls.append(image_url)
    return image_urls


def _split_image_urls(value):
    if not value:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    text = str(value).strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass

    urls = []
    for line in text.replace(",", "\n").splitlines():
        url = line.strip()
        if url:
            urls.append(url)
    return urls


def _dedupe_urls(urls):
    deduped = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def _collect_image_urls(record, primary_field, collection_field):
    return _dedupe_urls(
        _split_image_urls(record.get(collection_field, ""))
        + _split_image_urls(record.get(primary_field, ""))
    )


def _sort_key_created_at(item):
    value = item.get("created_at", "")
    if not value:
        return "9999-12-31 23:59:59"
    return str(value)


def _build_listing_items(display_filter, material_type_filter="all"):
    items = []
    matched_material_ids = get_provider_shared_material_ids()

    if display_filter in ("all", "materials") and material_type_filter in ("all", *MATERIAL_TYPE_OPTIONS):
        for material in get_materials():
            material_id = material.get("material_id", "")
            material_type = material.get("material_type", "")
            if material_id in matched_material_ids:
                continue
            if material_type_filter != "all" and material_type != material_type_filter:
                continue

            image_urls = _collect_image_urls(material, "image_url", "image_urls")
            items.append(
                {
                    "entry_type": "material",
                    "id": material_id,
                    "title": material.get("title", ""),
                    "image_url": image_urls[0] if image_urls else "",
                    "image_urls": image_urls,
                    "location": material.get("location", ""),
                    "status": material.get("status", ""),
                    "created_at": material.get("created_at", ""),
                    "material_type": material_type,
                    "quantity": material.get("quantity", ""),
                    "condition": material.get("condition", ""),
                }
            )

    if display_filter in ("all", "demolitions") and material_type_filter == "all":
        for property_record in get_demolition_properties():
            image_urls = _collect_image_urls(
                property_record,
                "building_photo_url",
                "building_photo_urls",
            )
            items.append(
                {
                    "entry_type": "demolition",
                    "id": property_record.get("property_id", ""),
                    "title": property_record.get("property_name", ""),
                    "image_url": image_urls[0] if image_urls else "",
                    "image_urls": image_urls,
                    "location": property_record.get("location", ""),
                    "status": property_record.get("status", ""),
                    "created_at": property_record.get("created_at", ""),
                    "registrant_name": property_record.get("display_name", ""),
                    "registrant_type": property_record.get("registrant_type", ""),
                    "demolition_date": property_record.get("demolition_date", ""),
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
    image_files = [image_file for image_file in request.files.getlist("image_files") if image_file and image_file.filename]
    legacy_image_file = request.files.get("image_file")
    if legacy_image_file and legacy_image_file.filename:
        image_files.append(legacy_image_file)
    input_image_urls = _dedupe_urls(
        _split_image_urls(form.get("image_url", ""))
        + _split_image_urls(form.get("image_urls_text", ""))
    )
    final_image_urls = input_image_urls

    required_fields = ["title", "material_type", "location"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register_material"))

    if image_files:
        try:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _dedupe_urls(uploaded_image_urls + input_image_urls)
            current_app.logger.info("[materials.submit] cloudinary upload success count=%s", len(uploaded_image_urls))
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

    form["image_url"] = final_image_urls[0] if final_image_urls else ""
    form["image_urls"] = json.dumps(final_image_urls, ensure_ascii=False)
    current_app.logger.info(
        "[materials.submit] final image count before save=%s line_user_id=%s title=%s",
        len(final_image_urls),
        form.get("line_user_id", ""),
        form.get("title", ""),
    )

    append_material(form)
    flash("材を登録しました。")
    return redirect(url_for("materials.list_materials"))


@materials_bp.route("/demolitions/submit", methods=["POST"])
def submit_demolition():
    form = request.form.to_dict()
    image_files = [
        image_file
        for image_file in request.files.getlist("building_image_files")
        if image_file and image_file.filename
    ]
    legacy_image_file = request.files.get("building_image_file")
    if legacy_image_file and legacy_image_file.filename:
        image_files.append(legacy_image_file)
    input_image_urls = _dedupe_urls(
        _split_image_urls(form.get("building_photo_url", ""))
        + _split_image_urls(form.get("building_photo_urls_text", ""))
    )
    final_image_urls = input_image_urls

    required_fields = ["property_name", "location", "registrant_type"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register_demolition"))

    if image_files:
        try:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _dedupe_urls(uploaded_image_urls + input_image_urls)
            current_app.logger.info("[demolitions.submit] cloudinary upload success count=%s", len(uploaded_image_urls))
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

    form["building_photo_url"] = final_image_urls[0] if final_image_urls else ""
    form["building_photo_urls"] = json.dumps(final_image_urls, ensure_ascii=False)
    append_demolition_property(form)
    flash("解体物件を登録しました。")
    return redirect(url_for("materials.list_materials"))


@materials_bp.route("/list", methods=["GET"])
def list_materials():
    display_filter = request.args.get("type", "all")
    if display_filter not in ("all", "materials", "demolitions"):
        display_filter = "all"
    material_type_filter = request.args.get("material_type", "all")
    if material_type_filter not in ("all", *MATERIAL_TYPE_OPTIONS):
        material_type_filter = "all"

    try:
        items = _build_listing_items(display_filter, material_type_filter)
    except Exception:
        current_app.logger.exception("[materials.list] failed to load listing items")
        flash("登録情報の読み込みに失敗しました。時間をおいて再度お試しください。")
        items = []

    return render_template(
        "materials/list.html",
        items=items,
        display_filter=display_filter,
        material_type_filter=material_type_filter,
        material_type_options=MATERIAL_TYPE_OPTIONS,
    )


@materials_bp.route("/<material_id>", methods=["GET"])
def detail(material_id):
    material = get_material_by_id(material_id)
    if not material:
        return "指定された材が見つかりません。", 404
    material["image_urls"] = _collect_image_urls(material, "image_url", "image_urls")
    return render_template("materials/detail.html", material=material)


@materials_bp.route("/demolitions/<property_id>", methods=["GET"])
def demolition_detail(property_id):
    property_record = get_demolition_property_by_id(property_id)
    if not property_record:
        return "指定された解体物件が見つかりません。", 404
    property_record["building_photo_urls"] = _collect_image_urls(
        property_record,
        "building_photo_url",
        "building_photo_urls",
    )
    return render_template("materials/demolition_detail.html", property_record=property_record)


@materials_bp.route("/<material_id>/delete", methods=["POST"])
def delete(material_id):
    line_user_id = request.form.get("line_user_id", "")
    if delete_material(material_id):
        flash("材登録を削除しました。")
    else:
        flash("材登録の削除に失敗しました。")

    if request.form.get("return_to") == "me":
        return redirect(url_for("users.me"))
    if line_user_id:
        return redirect(url_for("users.detail", line_user_id=line_user_id))
    return redirect(url_for("materials.list_materials", type=request.form.get("return_type", "all")))


@materials_bp.route("/<material_id>/update", methods=["POST"])
def update_material_entry(material_id):
    form = request.form.to_dict()
    line_user_id = _resolve_line_user_id(form)
    if not line_user_id:
        return jsonify({"ok": False, "message": "LINE user ID を取得できませんでした。"}), 400

    existing = get_material_by_id(material_id)
    if not existing:
        return jsonify({"ok": False, "message": "指定された材登録が見つかりません。"}), 404
    if existing.get("line_user_id") != line_user_id:
        return jsonify({"ok": False, "message": "この材登録は編集できません。"}), 403

    required_fields = ["title", "material_type", "location"]
    missing = [field for field in required_fields if not form.get(field)]
    if missing:
        return jsonify({"ok": False, "message": "必須項目が入力されていません。"}), 400

    image_files = [
        image_file
        for image_file in request.files.getlist("image_files")
        if image_file and image_file.filename
    ]
    input_image_urls = _dedupe_urls(
        _split_image_urls(form.get("image_url", ""))
        + _split_image_urls(form.get("image_urls_text", ""))
    )
    final_image_urls = input_image_urls

    if image_files:
        try:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _dedupe_urls(uploaded_image_urls + input_image_urls)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        except Exception:
            current_app.logger.exception("[materials.update] cloudinary upload failed")
            return jsonify({"ok": False, "message": "画像のアップロードに失敗しました。"}), 500

    form["image_url"] = final_image_urls[0] if final_image_urls else ""
    form["image_urls"] = json.dumps(final_image_urls, ensure_ascii=False)

    updated_material = update_material(material_id, line_user_id, form)
    if not updated_material:
        return jsonify({"ok": False, "message": "材登録の更新に失敗しました。"}), 500

    return jsonify({"ok": True, "material": updated_material})


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
                liff_url_for("users.me"),
                f"match_id: {match_id}",
            ]
        ),
        "materials.interest",
    )

    flash("欲しい通知を送信しました。")
    return redirect(
        url_for(
            "materials.list_materials",
            type=request.form.get("return_type", "all"),
            material_type=request.form.get("return_material_type", "all"),
        )
    )


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
                liff_url_for("users.me"),
                f"match_id: {match_id}",
            ]
        ),
        "demolitions.visit_interest",
    )

    flash("見学希望を送信しました。")
    return redirect(
        url_for(
            "materials.list_materials",
            type=request.form.get("return_type", "all"),
            material_type=request.form.get("return_material_type", "all"),
        )
    )
