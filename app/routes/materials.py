import json
import os
import re
import time
from uuid import uuid4
from urllib.parse import unquote, urlparse

import cloudinary
import cloudinary.uploader
from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select, delete as sql_delete

from app.services.db_service import (
    _engine, image_upload_jobs,
    record_operation,
    DELETED_STATUS,
    DEMOLITION_ACTIVE_STATUS,
    POST_STATUS_ACTIVE,
    POST_TYPE_OFFER,
    POST_TYPE_REQUEST,
    append_material,
    append_demolition_property,
    can_receive_line_notifications,
    close_material,
    delete_demolition_property,
    get_materials,
    get_public_listing_page,
    get_material_by_id,
    get_demolition_properties,
    get_demolition_property_by_id,
    has_recent_matching_request,
    renew_material,
    append_matching_history,
    delete_material,
    update_demolition_property,
    update_material,
)
from app.services.line_service import send_line_message
from app.services.notification_service import deliver_notification
from app.services.liff_service import liff_url_for
from app.services.line_auth_service import LineAuthError, require_verified_line_user_id
from app.services.user_cache_service import get_user_profile_snapshot
from app.validation import first_overlong_field
from app.services.location_service import public_location, public_post

materials_bp = Blueprint("materials", __name__, url_prefix="/materials")


def _listing_return_args():
    return {
        "type": request.form.get("return_type", "all"),
        "material_type": request.form.get("return_material_type", "all"),
        "page": max(1, min(request.form.get("return_page", 1, type=int), 100000)),
        "area": request.form.get("return_area", "all"),
        "q": request.form.get("return_q", "")[:100],
    }


def _return_to_listing():
    return redirect(url_for("materials.list_materials", **_listing_return_args()))


@materials_bp.route("/report/<kind>/<entry_id>", methods=["POST"])
def report_post(kind, entry_id):
    try:
        user_id = require_verified_line_user_id(_resolve_line_user_id(request.form))
    except LineAuthError:
        flash("通報するにはLINEからログインしてください。")
        return redirect(url_for("users.me"))
    entry = get_material_by_id(entry_id) if kind == "material" else get_demolition_property_by_id(entry_id) if kind == "demolition" else None
    reason = request.form.get("reason", "").strip()
    if not entry or reason not in ("個人情報が公開されている", "内容が不適切", "掲載内容に問題がある"):
        return "対象または通報理由を確認してください。", 400
    with _engine().begin() as conn:
        record_operation(conn, "report", f"{kind}:{entry_id}", user_id, reason)
    flash("通報を受け付けました。運営者が内容を確認します。")
    return redirect(url_for("materials.list_materials"))

MAX_IMAGES_PER_ENTRY = 6

MATERIAL_FIELD_LIMITS = {
    "title": 200,
    "post_type": 16,
    "material_type": 100,
    "description": 5000,
    "size": 300,
    "quantity": 100,
    "quantity_level": 64,
    "condition": 100,
    "location": 300,
    "custom_location": 300,
    "usage_purpose": 100,
    "pickup_deadline": 100,
    "image_urls_text": 3000,
}

DEMOLITION_FIELD_LIMITS = {
    "registrant_type": 100,
    "property_name": 200,
    "location": 300,
    "owner_name": 200,
    "demolition_contractor": 300,
    "viewing_period": 300,
    "building_use": 200,
    "structure": 200,
    "condition_evaluation": 5000,
    "notes": 5000,
    "building_photo_urls_text": 3000,
}


def _overlong_input_message(form, limits):
    invalid = first_overlong_field(form, limits)
    if not invalid:
        return ""
    field, max_length = invalid
    return f"入力が長すぎます（{field}: 最大{max_length}文字）。"

MATERIAL_TYPE_OPTIONS = [
    "木材",
    "合板・ボード",
    "建具",
    "トタン・金属材",
    "タイル・石材",
    "コンクリート・ブロック",
    "金物",
    "その他",
]

LEGACY_MATERIAL_TYPE_OPTIONS = [
    "金属",
    "家具",
    "石材・ブロック",
    "設備・配管",
]

ALL_MATERIAL_TYPE_OPTIONS = MATERIAL_TYPE_OPTIONS + LEGACY_MATERIAL_TYPE_OPTIONS
QUANTITY_LEVEL_OPTIONS = ("少量", "まとまってあります", "大量", "不明")
AREA_OPTIONS = ("和泊町", "知名町", "その他")
REQUEST_AREA_OPTIONS = ("和泊町", "知名町", "島内どこでも可", "その他")
USAGE_PURPOSE_OPTIONS = ("DIY", "修繕", "建築・施工", "家具製作", "その他")


cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)


def _upload_image(image_file):
    allowed_extensions = {
        ".png": "png",
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".gif": "gif",
        ".webp": "webp",
    }
    ext = os.path.splitext(image_file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise ValueError("画像は png, jpg, jpeg, gif, webp 形式のみアップロードできます。")

    header = image_file.stream.read(32)
    image_file.stream.seek(0)
    detected_type = _detect_image_type(header)
    if detected_type != allowed_extensions[ext]:
        raise ValueError("画像ファイルの形式を確認できませんでした。")

    current_app.logger.info(
        "[materials] uploading image filename=%s content_type=%s",
        image_file.filename,
        getattr(image_file, "content_type", ""),
    )

    public_id = f"erabu-zai-spot/uploads/{uuid4().hex}"
    with _engine().begin() as conn:
        conn.execute(image_upload_jobs.insert().values(public_id=public_id, created_at=int(time.time())))
    g.upload_jobs = getattr(g, "upload_jobs", []) + [public_id]
    upload_result = cloudinary.uploader.upload(
        image_file,
        public_id=public_id,
        resource_type="image",
    )
    image_url = upload_result.get("secure_url", "")
    if not image_url or not _is_allowed_image_url(image_url):
        raise ValueError("写真の保存結果を確認できませんでした。写真を選び直してください。")
    return image_url


def _upload_images(image_files):
    if len(image_files) > MAX_IMAGES_PER_ENTRY:
        raise ValueError(f"画像は{MAX_IMAGES_PER_ENTRY}枚までアップロードできます。")

    image_urls = []
    for image_file in image_files:
        if not image_file or not image_file.filename:
            continue
        image_url = _upload_image(image_file)
        if image_url:
            image_urls.append(image_url)
    return image_urls


def clean_upload_jobs(public_ids=None):
    """Remove only tracked uploads unreferenced by any retained post."""
    if public_ids is None:
        with _engine().connect() as conn:
            public_ids = conn.execute(select(image_upload_jobs.c.public_id).where(
                image_upload_jobs.c.created_at < int(time.time()) - 86400
            ).order_by(image_upload_jobs.c.created_at).limit(100)).scalars().all()
    if not public_ids:
        return 0
    # Match the full asset suffix too: Cloudinary URLs may omit a version or
    # include transformations. Never delete a referenced asset on parse failure.
    active_paths = {os.path.splitext(unquote(urlparse(url).path))[0] for url in _active_cloudinary_image_urls()}
    cleaned = 0
    for public_id in public_ids:
        if not any(path.endswith('/' + public_id) for path in active_paths):
            try:
                result = cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
                if result.get("result") not in ("ok", "not found"):
                    continue
            except Exception:
                current_app.logger.exception("[UPLOAD CLEANUP] failed")
                continue
        with _engine().begin() as conn:
            conn.execute(sql_delete(image_upload_jobs).where(image_upload_jobs.c.public_id == public_id))
        cleaned += 1
    return cleaned


@materials_bp.after_request
def finish_upload_jobs(response):
    if getattr(g, "upload_jobs", None):
        try:
            clean_upload_jobs(g.upload_jobs)
        except Exception:
            current_app.logger.exception("[UPLOAD CLEANUP] deferred to scheduled job")
    return response


def _detect_image_type(header):
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return ""


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


def _is_allowed_image_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False

    hostname = (parsed.hostname or "").lower()
    return hostname == "res.cloudinary.com"


def _validate_image_urls(urls):
    if len(urls) > MAX_IMAGES_PER_ENTRY:
        raise ValueError(f"画像URLは{MAX_IMAGES_PER_ENTRY}件まで登録できます。")

    if any(not _is_allowed_image_url(url) for url in urls):
        raise ValueError("画像URLはCloudinaryのhttps URLのみ登録できます。")

    return urls


def _collect_image_urls(record, primary_field, collection_field):
    return _validate_display_image_urls(_dedupe_urls(
        _split_image_urls(record.get(collection_field, ""))
        + _split_image_urls(record.get(primary_field, ""))
    ))


def _validate_display_image_urls(urls):
    return [url for url in urls if _is_allowed_image_url(url)]


def _cloudinary_public_id(image_url):
    parsed = urlparse(image_url)
    expected_cloud_name = (os.environ.get("CLOUDINARY_CLOUD_NAME") or "").strip()
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "res.cloudinary.com"
        or not expected_cloud_name
    ):
        return ""

    segments = [unquote(segment) for segment in parsed.path.strip("/").split("/")]
    if len(segments) < 5 or segments[0] != expected_cloud_name:
        return ""
    if segments[1:3] != ["image", "upload"]:
        return ""

    version_index = next(
        (
            index
            for index in range(3, len(segments))
            if re.fullmatch(r"v\d+", segments[index])
        ),
        -1,
    )
    if version_index < 0 or version_index + 1 >= len(segments):
        return ""

    public_id_parts = segments[version_index + 1 :]
    public_id_parts[-1] = os.path.splitext(public_id_parts[-1])[0]
    public_id = "/".join(part for part in public_id_parts if part)
    if not public_id.startswith("erabu-zai-spot/uploads/"):
        return ""
    return public_id


def _active_cloudinary_image_urls():
    active_urls = set()
    for material in get_materials(include_all=True):
        if material.get("status") == "削除済み":
            continue
        active_urls.update(_collect_image_urls(material, "image_url", "image_urls"))

    for property_record in get_demolition_properties(include_all=True):
        if property_record.get("status") == "削除済み":
            continue
        active_urls.update(
            _collect_image_urls(
                property_record,
                "building_photo_url",
                "building_photo_urls",
            )
        )
    return active_urls


def _delete_cloudinary_images(image_urls, log_context):
    public_ids = []
    failures = []
    skipped_count = 0
    seen = set()
    active_urls = _active_cloudinary_image_urls()

    for image_url in _dedupe_urls(image_urls):
        if image_url in active_urls:
            skipped_count += 1
            current_app.logger.info(
                "[%s] Cloudinary image is still referenced and will not be deleted url=%s",
                log_context,
                image_url,
            )
            continue
        public_id = _cloudinary_public_id(image_url)
        if not public_id:
            failures.append(image_url)
            current_app.logger.warning(
                "[%s] Cloudinary public ID could not be resolved url=%s",
                log_context,
                image_url,
            )
            continue
        if public_id not in seen:
            public_ids.append(public_id)
            seen.add(public_id)

    deleted_count = 0
    for public_id in public_ids:
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type="image",
                invalidate=True,
            )
            if result.get("result") in ("ok", "not found"):
                deleted_count += 1
            else:
                failures.append(public_id)
                current_app.logger.warning(
                    "[%s] Cloudinary image deletion was not accepted public_id=%s result=%s",
                    log_context,
                    public_id,
                    result.get("result", ""),
                )
        except Exception:
            failures.append(public_id)
            current_app.logger.exception(
                "[%s] Cloudinary image deletion failed public_id=%s",
                log_context,
                public_id,
            )

    return deleted_count, failures, skipped_count


def _flash_deleted_with_image_result(label, image_urls, log_context):
    if not image_urls:
        flash(f"{label}を削除しました。")
        return

    deleted_count, failures, skipped_count = _delete_cloudinary_images(
        image_urls,
        log_context,
    )
    if failures:
        flash(
            f"{label}は削除しましたが、画像{len(failures)}件をCloudinaryから削除できませんでした。"
            "運営者に連絡してください。"
        )
        return

    if skipped_count:
        flash(
            f"{label}を削除しました。画像{deleted_count}件をCloudinaryから削除し、"
            f"他の登録でも使用中の画像{skipped_count}件は残しました。"
        )
        return

    flash(f"{label}を削除し、画像{deleted_count}件もCloudinaryから削除しました。")


def _sort_key_created_at(item):
    value = item.get("created_at", "")
    if not value:
        return ""
    return str(value)


def _build_listing_items(display_filter, material_type_filter="all", material_records=None, demolition_records=None):
    items = []

    if display_filter in ("all", "materials", "offer", "request") and material_type_filter in ("all", *ALL_MATERIAL_TYPE_OPTIONS):
        for material in (get_materials() if material_records is None else material_records):
            material_id = material.get("material_id", "")
            material_type = material.get("material_type", "")
            post_type = material.get("post_type", POST_TYPE_OFFER)
            if display_filter in ("offer", "request") and post_type != display_filter:
                continue
            if material_type_filter != "all" and material_type != material_type_filter:
                continue

            image_urls = _collect_image_urls(material, "image_url", "image_urls")
            items.append(
                {
                    "entry_type": "material",
                    "post_type": post_type,
                    "id": material_id,
                    "title": material.get("title", ""),
                    "image_url": image_urls[0] if image_urls else "",
                    "image_urls": image_urls,
                    "location": public_location(material.get("location")),
                    "status": material.get("status_label", "受付中"),
                    "effective_status": material.get("effective_status", POST_STATUS_ACTIVE),
                    "created_at": material.get("created_at", ""),
                    "expires_at": material.get("expires_at", ""),
                    "material_type": material_type,
                    "quantity_level": material.get("quantity_level", ""),
                    "quantity": material.get("quantity", ""),
                    "condition": material.get("condition", ""),
                    "pickup_deadline": material.get("pickup_deadline", ""),
                    "description": material.get("description", ""),
                    "size": material.get("size", ""),
                    "usage_purpose": material.get("usage_purpose", ""),
                    "display_name": material.get("display_name", ""),
                }
            )

    if display_filter in ("all", "demolitions") and material_type_filter == "all":
        for property_record in (get_demolition_properties() if demolition_records is None else demolition_records):
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
                    "location": public_location(property_record.get("location")),
                    "status": property_record.get("status", ""),
                    "created_at": property_record.get("created_at", ""),
                    "registrant_name": property_record.get("display_name", ""),
                    "registrant_type": property_record.get("registrant_type", ""),
                    "demolition_date": property_record.get("demolition_date", ""),
                    "demolition_contractor": property_record.get("demolition_contractor", ""),
                    "viewing_period": property_record.get("viewing_period", ""),
                    "building_use": property_record.get("building_use", ""),
                    "structure": property_record.get("structure", ""),
                    "floors": property_record.get("floors", ""),
                    "building_age": property_record.get("building_age", ""),
                    "condition_evaluation": property_record.get("condition_evaluation", ""),
                    "notes": property_record.get("notes", ""),
                }
            )

    return sorted(items, key=_sort_key_created_at, reverse=True)


def _resolve_line_user_id(form):
    for field_name in ("line_user_id", "user_id", "userid"):
        value = (form.get(field_name) or "").strip()
        if value:
            return value
    return ""


def _redirect_unavailable_notifications_to_user_page(line_user_id):
    if can_receive_line_notifications(line_user_id):
        return None

    flash(
        "「欲しい」「見学したい」を送るには、LINE通知を受け取れる状態にしてください。"
        "公式アカウントを友だち追加した状態でユーザー情報ページを開き直してください。"
    )
    return redirect(
        url_for(
            "users.me",
            notification_required="1",
            _anchor="notification-readiness",
        )
    )


def _registered_profile(line_user_id):
    if not line_user_id:
        return None
    user, _, _ = get_user_profile_snapshot(line_user_id)
    return user


def _profile_delivery_location(profile):
    if not profile:
        return ""
    area = (profile.get("area") or "").strip()
    address = (profile.get("address") or "").strip()
    if not address:
        return area
    if not area or area in address:
        return address
    return f"{area} {address}"


@materials_bp.route("/register", methods=["GET"])
def register():
    return render_template("materials/register_select.html")


@materials_bp.route("/register/material", methods=["GET"])
def register_material():
    return render_template(
        "materials/register.html",
        material_type_options=MATERIAL_TYPE_OPTIONS,
        quantity_level_options=QUANTITY_LEVEL_OPTIONS,
        area_options=AREA_OPTIONS,
    )


@materials_bp.route("/register/request", methods=["GET"])
def register_request():
    return render_template(
        "materials/request_register.html",
        material_type_options=MATERIAL_TYPE_OPTIONS,
        area_options=REQUEST_AREA_OPTIONS,
        usage_purpose_options=USAGE_PURPOSE_OPTIONS,
    )


@materials_bp.route("/register/demolition", methods=["GET"])
def register_demolition():
    return render_template("materials/demolition_register.html")


@materials_bp.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "GET":
        return redirect(url_for("materials.register_material"))

    form = request.form.to_dict()
    validation_error = _overlong_input_message(form, MATERIAL_FIELD_LIMITS)
    if validation_error:
        flash(validation_error)
        return redirect(url_for("materials.register_material"))
    try:
        line_user_id = require_verified_line_user_id(form.get("line_user_id", ""))
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("materials.register_material"))
    form["line_user_id"] = line_user_id

    profile = _registered_profile(line_user_id)
    if not profile:
        flash("材を登録する前に、マイページでユーザー情報を登録してください。")
        return redirect(url_for("users.me"))
    form["display_name"] = (
        form.get("display_name")
        or profile.get("business_name")
        or profile.get("display_name", "")
    )
    if form.get("location_source") == "profile":
        form["location"] = _profile_delivery_location(profile)
    elif form.get("location_source") == "custom":
        form["location"] = (form.get("custom_location") or form.get("location") or "").strip()

    image_files = [image_file for image_file in request.files.getlist("image_files") if image_file and image_file.filename]
    legacy_image_file = request.files.get("image_file")
    if legacy_image_file and legacy_image_file.filename:
        image_files.append(legacy_image_file)
    input_image_urls = _dedupe_urls(
        _split_image_urls(form.get("image_url", ""))
        + _split_image_urls(form.get("image_urls_text", ""))
    )
    try:
        input_image_urls = _validate_image_urls(input_image_urls)
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("materials.register_material"))
    final_image_urls = input_image_urls

    required_fields = ["material_type", "quantity_level", "location"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register_material"))

    if not image_files and not input_image_urls:
        flash("「材があります」の投稿には写真を1枚以上登録してください。")
        return redirect(url_for("materials.register_material"))

    if image_files:
        try:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _validate_image_urls(_dedupe_urls(uploaded_image_urls + input_image_urls))
            current_app.logger.info("[materials.submit] cloudinary upload success count=%s", len(uploaded_image_urls))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("materials.register_material"))
        except Exception:
            current_app.logger.exception("[materials.submit] cloudinary upload failed")
            flash("写真を保存できませんでした。下書きを復元し、写真を選び直して再度お試しください。")
            return redirect(url_for("materials.register_material"))

    form["post_type"] = POST_TYPE_OFFER
    form.pop("status", None)
    form.pop("expires_at", None)
    form["title"] = (form.get("title") or f"{form.get('material_type', '材')}があります").strip()
    form["image_url"] = final_image_urls[0] if final_image_urls else ""
    form["image_urls"] = json.dumps(final_image_urls, ensure_ascii=False)
    current_app.logger.info(
        "[materials.submit] final image count before save=%s line_user_id=%s title=%s",
        len(final_image_urls),
        form.get("line_user_id", ""),
        form.get("title", ""),
    )

    append_material(form)
    flash("「材があります」を投稿しました。掲載期間は30日です。")
    session["completed_draft"] = {"kind": "offer", "owner": form["line_user_id"]}
    return redirect(url_for("materials.list_materials", type="offer"))


@materials_bp.route("/requests/submit", methods=["GET", "POST"])
def submit_request():
    if request.method == "GET":
        return redirect(url_for("materials.register_request"))

    form = request.form.to_dict()
    validation_error = _overlong_input_message(form, MATERIAL_FIELD_LIMITS)
    if validation_error:
        flash(validation_error)
        return redirect(url_for("materials.register_request"))
    try:
        line_user_id = require_verified_line_user_id(form.get("line_user_id", ""))
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("materials.register_request"))
    form["line_user_id"] = line_user_id

    profile = _registered_profile(line_user_id)
    if not profile:
        flash("投稿する前に、マイページでユーザー情報を登録してください。")
        return redirect(url_for("users.me"))
    form["display_name"] = (
        form.get("display_name")
        or profile.get("business_name")
        or profile.get("display_name", "")
    )

    required_fields = ["material_type", "description"]
    if any(not (form.get(field) or "").strip() for field in required_fields):
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register_request"))

    image_files = [
        image_file
        for image_file in request.files.getlist("image_files")
        if image_file and image_file.filename
    ]
    input_image_urls = _dedupe_urls(
        _split_image_urls(form.get("image_url", ""))
        + _split_image_urls(form.get("image_urls_text", ""))
    )
    try:
        final_image_urls = _validate_image_urls(input_image_urls)
        if image_files:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _validate_image_urls(
                _dedupe_urls(uploaded_image_urls + final_image_urls)
            )
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("materials.register_request"))
    except Exception:
        current_app.logger.exception("[materials.requests.submit] cloudinary upload failed")
        flash("画像のアップロードに失敗しました。画像なしで投稿するか、再度お試しください。")
        return redirect(url_for("materials.register_request"))

    form["post_type"] = POST_TYPE_REQUEST
    form.pop("status", None)
    form.pop("expires_at", None)
    form["title"] = (form.get("title") or f"{form.get('material_type', '材')}を探しています").strip()
    form["image_url"] = final_image_urls[0] if final_image_urls else ""
    form["image_urls"] = json.dumps(final_image_urls, ensure_ascii=False)
    append_material(form)
    flash("「材を探しています」を投稿しました。掲載期間は30日です。")
    session["completed_draft"] = {"kind": "request", "owner": form["line_user_id"]}
    return redirect(url_for("materials.list_materials", type="request"))


@materials_bp.route("/demolitions/submit", methods=["GET", "POST"])
def submit_demolition():
    if request.method == "GET":
        return redirect(url_for("materials.register_demolition"))

    form = request.form.to_dict()
    validation_error = _overlong_input_message(form, DEMOLITION_FIELD_LIMITS)
    if validation_error:
        flash(validation_error)
        return redirect(url_for("materials.register_demolition"))
    try:
        line_user_id = require_verified_line_user_id(form.get("line_user_id", ""))
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("materials.register_demolition"))
    form["line_user_id"] = line_user_id

    if not _registered_profile(line_user_id):
        flash("解体物件を登録する前に、マイページでユーザー情報を登録してください。")
        return redirect(url_for("users.me"))

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
    try:
        input_image_urls = _validate_image_urls(input_image_urls)
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("materials.register_demolition"))
    final_image_urls = input_image_urls

    required_fields = ["property_name", "location", "registrant_type"]
    missing = [field for field in required_fields if not form.get(field)]

    if missing:
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.register_demolition"))

    if image_files:
        try:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _validate_image_urls(_dedupe_urls(uploaded_image_urls + input_image_urls))
            current_app.logger.info("[demolitions.submit] cloudinary upload success count=%s", len(uploaded_image_urls))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("materials.register_demolition"))
        except Exception:
            current_app.logger.exception("[demolitions.submit] cloudinary upload failed")
            flash("画像のアップロードに失敗しました。画像なしで登録するか、再度お試しください。")
            return redirect(url_for("materials.register_demolition"))

    form["building_photo_url"] = final_image_urls[0] if final_image_urls else ""
    form["building_photo_urls"] = json.dumps(final_image_urls, ensure_ascii=False)
    append_demolition_property(form)
    flash("解体物件を登録しました。")
    session["completed_draft"] = {"kind": "demolition", "owner": form["line_user_id"]}
    return redirect(url_for("materials.list_materials"))


@materials_bp.route("/list", methods=["GET"])
def list_materials():
    load_error = False
    page = max(1, min(request.args.get("page", 1, type=int), 100000))
    has_next = False
    area = request.args.get("area", "all")
    if area not in ("all", "和泊町", "知名町"):
        area = "all"
    query = request.args.get("q", "").strip()[:100]
    display_filter = request.args.get("type", "all")
    if display_filter == "materials":
        display_filter = "offer"
    if display_filter not in ("all", "materials", "offer", "request", "demolitions"):
        display_filter = "all"
    material_type_filter = request.args.get("material_type", "all")
    if material_type_filter not in ("all", *ALL_MATERIAL_TYPE_OPTIONS):
        material_type_filter = "all"

    try:
        material_records, demolition_records, refs, has_next = get_public_listing_page(display_filter, material_type_filter, page, area=area, query=query)
        items = _build_listing_items(display_filter, material_type_filter, material_records, demolition_records)
        positions = {(r["kind"], r["id"]): i for i, r in enumerate(refs)}
        items.sort(key=lambda item: positions[(item["entry_type"], item["id"])])
    except Exception:
        current_app.logger.exception("[materials.list] failed to load listing items")
        load_error = True
        items = []

    def listing_url(**changes):
        args = {"type": display_filter, "material_type": material_type_filter, "area": area, "q": query, "page": 1}
        args.update(changes)
        return url_for("materials.list_materials", **args)

    return render_template(
        "materials/list.html",
        items=items,
        load_error=load_error,
        page=page,
        has_next=has_next,
        area=area,
        query=query,
        listing_url=listing_url,
        inquiry_result=session.pop("inquiry_result", None),
        display_filter=display_filter,
        material_type_filter=material_type_filter,
        material_type_options=ALL_MATERIAL_TYPE_OPTIONS,
    ), (503 if load_error else 200)


@materials_bp.route("/<material_id>", methods=["GET"])
def detail(material_id):
    material = get_material_by_id(material_id)
    if not material or material.get("effective_status") == "deleted":
        return "指定された材が見つかりません。", 404
    material["image_urls"] = _collect_image_urls(material, "image_url", "image_urls")
    return render_template("materials/detail.html", material=public_post(material))


@materials_bp.route("/demolitions/<property_id>", methods=["GET"])
def demolition_detail(property_id):
    property_record = get_demolition_property_by_id(property_id)
    if not property_record or property_record.get("status") == DELETED_STATUS:
        return "指定された解体物件が見つかりません。", 404
    property_record["building_photo_urls"] = _collect_image_urls(
        property_record,
        "building_photo_url",
        "building_photo_urls",
    )
    return render_template("materials/demolition_detail.html", property_record=public_post(property_record))


@materials_bp.route("/demolitions/<property_id>/edit", methods=["GET"])
def edit_demolition(property_id):
    property_record = get_demolition_property_by_id(property_id)
    if not property_record or property_record.get("status") == "削除済み":
        return "指定された解体物件が見つかりません。", 404

    try:
        require_verified_line_user_id(property_record.get("line_user_id", ""))
    except LineAuthError:
        flash("この解体物件を編集するにはLINE認証が必要です。")
        return redirect(url_for("users.me"))

    property_record["building_photo_urls"] = _collect_image_urls(
        property_record,
        "building_photo_url",
        "building_photo_urls",
    )
    return render_template(
        "materials/demolition_edit.html",
        property_record=property_record,
    )


@materials_bp.route("/demolitions/<property_id>/update", methods=["POST"])
def update_demolition_entry(property_id):
    form = request.form.to_dict()
    validation_error = _overlong_input_message(form, DEMOLITION_FIELD_LIMITS)
    if validation_error:
        flash(validation_error)
        return redirect(url_for("materials.edit_demolition", property_id=property_id))

    try:
        line_user_id = require_verified_line_user_id(
            _resolve_line_user_id(form)
        )
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    existing = get_demolition_property_by_id(property_id)
    if not existing or existing.get("line_user_id") != line_user_id:
        flash("この解体物件は編集できません。")
        return redirect(url_for("users.me"))

    required_fields = ["property_name", "location", "registrant_type"]
    if any(not form.get(field) for field in required_fields):
        flash("必須項目が入力されていません。")
        return redirect(url_for("materials.edit_demolition", property_id=property_id))

    image_files = [
        image_file
        for image_file in request.files.getlist("building_image_files")
        if image_file and image_file.filename
    ]
    input_image_urls = _dedupe_urls(
        _split_image_urls(form.get("building_photo_url", ""))
        + _split_image_urls(form.get("building_photo_urls_text", ""))
    )
    try:
        final_image_urls = _validate_image_urls(input_image_urls)
        if image_files:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _validate_image_urls(
                _dedupe_urls(uploaded_image_urls + final_image_urls)
            )
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("materials.edit_demolition", property_id=property_id))
    except Exception:
        current_app.logger.exception("[demolitions.update] cloudinary upload failed")
        flash("画像のアップロードに失敗しました。")
        return redirect(url_for("materials.edit_demolition", property_id=property_id))

    form["building_photo_url"] = final_image_urls[0] if final_image_urls else ""
    form["building_photo_urls"] = json.dumps(final_image_urls, ensure_ascii=False)
    updated = update_demolition_property(property_id, line_user_id, form)
    if not updated:
        flash("解体物件の更新に失敗しました。")
        return redirect(url_for("materials.edit_demolition", property_id=property_id))

    flash("解体物件を更新しました。")
    return redirect(url_for("users.me", refresh="1"))


@materials_bp.route("/demolitions/<property_id>/delete", methods=["POST"])
def delete_demolition(property_id):
    try:
        line_user_id = require_verified_line_user_id(
            _resolve_line_user_id(request.form)
        )
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    existing = get_demolition_property_by_id(property_id)
    if not existing or existing.get("line_user_id") != line_user_id:
        flash("この解体物件は削除できません。")
        return redirect(url_for("users.me"))

    image_urls = _collect_image_urls(
        existing,
        "building_photo_url",
        "building_photo_urls",
    )
    if delete_demolition_property(property_id):
        _flash_deleted_with_image_result(
            "解体物件",
            image_urls,
            "demolitions.delete",
        )
    else:
        flash("解体物件の削除に失敗しました。")

    return redirect(url_for("users.me", refresh="1"))


@materials_bp.route("/<material_id>/delete", methods=["POST"])
def delete(material_id):
    line_user_id = request.form.get("line_user_id", "")
    try:
        line_user_id = require_verified_line_user_id(line_user_id)
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    existing = get_material_by_id(material_id)
    if not existing or existing.get("line_user_id") != line_user_id:
        flash("This material cannot be deleted by the current user.")
        return redirect(url_for("users.me"))

    image_urls = _collect_image_urls(existing, "image_url", "image_urls")
    if delete_material(material_id):
        _flash_deleted_with_image_result(
            "材登録",
            image_urls,
            "materials.delete",
        )
    else:
        flash("材登録の削除に失敗しました。")

    if request.form.get("return_to") == "me":
        return redirect(url_for("users.me", refresh="1"))
    if line_user_id:
        return redirect(url_for("users.detail", line_user_id=line_user_id))
    return redirect(url_for("materials.list_materials", type=request.form.get("return_type", "all")))


@materials_bp.route("/<material_id>/close", methods=["POST"])
def close(material_id):
    try:
        line_user_id = require_verified_line_user_id(
            _resolve_line_user_id(request.form)
        )
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    material = get_material_by_id(material_id)
    if not material or material.get("line_user_id") != line_user_id:
        flash("この投稿は終了できません。")
        return redirect(url_for("users.me", refresh="1"))

    if close_material(material_id, line_user_id):
        label = (
            "見つかりました・終了"
            if material.get("post_type") == POST_TYPE_REQUEST
            else "譲渡済み・終了"
        )
        flash(f"投稿を「{label}」にしました。")
    else:
        flash("投稿の終了に失敗しました。")
    return redirect(url_for("users.me", refresh="1"))


@materials_bp.route("/<material_id>/renew", methods=["POST"])
def renew(material_id):
    try:
        line_user_id = require_verified_line_user_id(
            _resolve_line_user_id(request.form)
        )
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return redirect(url_for("users.me"))

    if renew_material(material_id, line_user_id):
        flash("投稿を受付中に戻し、掲載期限を30日延長しました。")
    else:
        flash("投稿の再掲載に失敗しました。")
    return redirect(url_for("users.me", refresh="1"))


@materials_bp.route("/<material_id>/update", methods=["POST"])
def update_material_entry(material_id):
    form = request.form.to_dict()
    validation_error = _overlong_input_message(form, MATERIAL_FIELD_LIMITS)
    if validation_error:
        return jsonify({"ok": False, "message": validation_error}), 400
    line_user_id = _resolve_line_user_id(form)
    try:
        line_user_id = require_verified_line_user_id(line_user_id)
    except LineAuthError:
        return jsonify({"ok": False, "message": "LINE authentication failed"}), 401

    if not line_user_id:
        return jsonify({"ok": False, "message": "LINE user ID を取得できませんでした。"}), 400

    existing = get_material_by_id(material_id)
    if not existing:
        return jsonify({"ok": False, "message": "指定された材登録が見つかりません。"}), 404
    if existing.get("line_user_id") != line_user_id:
        return jsonify({"ok": False, "message": "この材登録は編集できません。"}), 403

    post_type = existing.get("post_type", POST_TYPE_OFFER)
    form["post_type"] = post_type
    required_fields = (
        ["material_type", "description"]
        if post_type == POST_TYPE_REQUEST
        else ["material_type", "quantity_level", "location"]
    )
    missing = [field for field in required_fields if not form.get(field)]
    if missing:
        return jsonify({"ok": False, "message": "必須項目が入力されていません。"}), 400

    image_files = [
        image_file
        for image_file in request.files.getlist("image_files")
        if image_file and image_file.filename
    ]
    if request.form.get("keep_image_urls_present"):
        input_image_urls = _dedupe_urls(
            request.form.getlist("keep_image_urls")
        )
    else:
        input_image_urls = _dedupe_urls(
            _split_image_urls(form.get("image_url", ""))
            + _split_image_urls(form.get("image_urls_text", ""))
        )
    try:
        input_image_urls = _validate_image_urls(input_image_urls)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    final_image_urls = input_image_urls

    if image_files:
        try:
            uploaded_image_urls = _upload_images(image_files)
            final_image_urls = _validate_image_urls(_dedupe_urls(uploaded_image_urls + input_image_urls))
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        except Exception:
            current_app.logger.exception("[materials.update] cloudinary upload failed")
            return jsonify({"ok": False, "message": "画像のアップロードに失敗しました。"}), 500

    existing_image_urls = _collect_image_urls(existing, "image_url", "image_urls")
    if (
        post_type == POST_TYPE_OFFER
        and existing_image_urls
        and not final_image_urls
    ):
        return jsonify({
            "ok": False,
            "message": "「材があります」の写真をすべて外すことはできません。",
        }), 400

    generated_title_suffix = (
        "を探しています" if post_type == POST_TYPE_REQUEST else "があります"
    )
    submitted_title = str(form.get("title") or "").strip()
    form["title"] = submitted_title or (
        f"{form.get('material_type', '材')}{generated_title_suffix}"
    )
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
    try:
        requester_line_user_id = require_verified_line_user_id(requester_line_user_id)
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return _return_to_listing()

    notification_setup_redirect = (
        _redirect_unavailable_notifications_to_user_page(
            requester_line_user_id
        )
    )
    if notification_setup_redirect:
        return notification_setup_redirect

    message = request.form.get("message", "")
    if len(message) > 1000:
        flash("メッセージは1000文字以内で入力してください。")
        return _return_to_listing()

    material = get_material_by_id(material_id)
    if not material:
        return "指定された材が見つかりません。", 404
    if material.get("effective_status") != POST_STATUS_ACTIVE:
        flash("この投稿は受付を終了しています。")
        return _return_to_listing()

    if material.get("line_user_id") == requester_line_user_id:
        flash("自分が登録した投稿には問い合わせできません。")
        return _return_to_listing()

    post_type = material.get("post_type", POST_TYPE_OFFER)
    match_type = "request" if post_type == POST_TYPE_REQUEST else "material"
    if has_recent_matching_request(match_type, material_id, requester_line_user_id):
        flash("同じ問い合わせを送信済みです。少し時間をおいてください。")
        return _return_to_listing()

    if post_type == POST_TYPE_REQUEST:
        provider_user_id = requester_line_user_id
        request_owner_user_id = material.get("line_user_id", "")
        action = "提供できます"
    else:
        provider_user_id = material.get("line_user_id", "")
        request_owner_user_id = requester_line_user_id
        action = "欲しい"

    match_id = append_matching_history(
        {
            "material_id": material_id,
            "provider_user_id": provider_user_id,
            "requester_user_id": request_owner_user_id,
            "action": action,
            "message": message,
            "status": "未対応",
        },
        match_type=match_type,
        prevent_duplicate=True,
    )

    if not match_id:
        flash("送信済み、または受付を終了した投稿です。")
        return _return_to_listing()

    notification_sent = deliver_notification(match_id, sender=send_line_message)
    session["inquiry_result"] = {"match_id": match_id, "notification_sent": notification_sent}

    if notification_sent:
        flash("問い合わせを送信しました。")
    else:
        notification_target_label = (
            "投稿者" if post_type == POST_TYPE_REQUEST else "登録者"
        )
        flash(
            f"問い合わせはマッチング履歴に保存しましたが、{notification_target_label}へのLINE通知に失敗しました。"
            "マイページで履歴を確認し、必要に応じて運営者へ連絡してください。"
        )
    return _return_to_listing()


@materials_bp.route("/demolitions/visit-interest", methods=["POST"])
def visit_interest():
    property_id = request.form.get("property_id")
    requester_line_user_id = _resolve_line_user_id(request.form)
    try:
        requester_line_user_id = require_verified_line_user_id(requester_line_user_id)
    except LineAuthError:
        flash("LINE login verification failed. Please reopen this page from LINE.")
        return _return_to_listing()

    notification_setup_redirect = (
        _redirect_unavailable_notifications_to_user_page(
            requester_line_user_id
        )
    )
    if notification_setup_redirect:
        return notification_setup_redirect

    property_record = get_demolition_property_by_id(property_id)
    if not property_record or property_record.get("status") == DELETED_STATUS:
        return "指定された解体物件が見つかりません。", 404
    if property_record.get("status") != DEMOLITION_ACTIVE_STATUS:
        flash("この物件は受付を終了しています。")
        return _return_to_listing()

    if property_record.get("line_user_id") == requester_line_user_id:
        flash("自分が登録した物件には見学希望を送れません。")
        return _return_to_listing()
    if has_recent_matching_request("viewing", property_id, requester_line_user_id):
        flash("同じ見学希望を送信済みです。少し時間をおいてください。")
        return _return_to_listing()

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
        prevent_duplicate=True,
    )

    if not match_id:
        flash("送信済み、または受付を終了した物件です。")
        return _return_to_listing()

    notification_sent = deliver_notification(match_id, sender=send_line_message)
    session["inquiry_result"] = {"match_id": match_id, "notification_sent": notification_sent}

    if notification_sent:
        flash("見学希望を送信しました。")
    else:
        flash(
            "見学希望はマッチング履歴に保存しましたが、登録者へのLINE通知に失敗しました。"
            "マイページで履歴を確認し、必要に応じて運営者へ連絡してください。"
        )
    return _return_to_listing()
