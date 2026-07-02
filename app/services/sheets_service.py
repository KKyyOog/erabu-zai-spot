from datetime import datetime
from uuid import uuid4

import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials
from flask import current_app, g, has_request_context

import json

SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]

MATERIAL_HEADERS = [
    "material_id",
    "line_user_id",
    "display_name",
    "title",
    "material_type",
    "description",
    "size",
    "quantity",
    "condition",
    "location",
    "pickup_deadline",
    "image_url",
    "image_urls",
    "status",
    "created_at",
]

DEMOLITION_HEADERS = [
    "property_id",
    "line_user_id",
    "display_name",
    "registrant_type",
    "property_name",
    "location",
    "owner_name",
    "demolition_date",
    "demolition_contractor",
    "viewing_period",
    "building_use",
    "structure",
    "floors",
    "building_age",
    "building_photo_url",
    "building_photo_urls",
    "condition_evaluation",
    "notes",
    "status",
    "created_at",
]

USER_FIELDS = ("display_name", "address", "transport_info")

MATERIAL_MATCHING_HISTORY_SHEET = "材のマッチング履歴"
VIEWING_MATCHING_HISTORY_SHEET = "見学マッチング履歴"
CONTACT_CARDS_SHEET = "連絡先カード管理"
CONTACT_SHARE_LOGS_SHEET = "連絡先共有履歴"

MATCHING_HISTORY_HEADERS = [
    "match_id",
    "material_id",
    "property_id",
    "provider_user_id",
    "requester_user_id",
    "action",
    "message",
    "status",
    "provider_contact_share_status",
    "requester_contact_share_status",
    "provider_contact_shared_at",
    "requester_contact_shared_at",
    "created_at",
    "updated_at",
]

CONTACT_CARD_HEADERS = [
    "contact_card_id",
    "user_id",
    "line_user_id",
    "display_name",
    "contact_method",
    "contact_value",
    "available_time",
    "message",
    "is_active",
    "created_at",
    "updated_at",
]

CONTACT_SHARE_LOG_HEADERS = [
    "contact_share_id",
    "match_id",
    "match_type",
    "from_user_id",
    "to_user_id",
    "share_status",
    "shared_display_name",
    "shared_contact_method",
    "shared_contact_value",
    "shared_available_time",
    "shared_message",
    "consent_version",
    "requested_at",
    "shared_at",
    "declined_at",
    "expires_at",
    "created_at",
    "updated_at",
]


def _normalize_user_id(data=None, fallback=""):
    data = data or {}
    user_id = (data.get("line_user_id") or data.get("user_id") or data.get("userid") or fallback or "").strip()
    if user_id:
        return user_id
    return f"anon_{uuid4().hex[:10]}"


def _find_user_row(records, line_user_id):
    for idx, record in enumerate(records, start=2):
        if (
            record.get("line_user_id") == line_user_id
            or record.get("user_id") == line_user_id
            or record.get("userid") == line_user_id
        ):
            return idx, record
    return None, None


def _get_client():
    if has_request_context() and getattr(g, "gspread_client", None):
        return g.gspread_client

    json_text = current_app.config.get("GOOGLE_SERVICE_ACCOUNT_JSON_TEXT")

    if json_text:
        service_account_info = json.loads(json_text)
        credentials = Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPE,
        )
    else:
        credentials = Credentials.from_service_account_file(
            current_app.config["GOOGLE_SERVICE_ACCOUNT_JSON"],
            scopes=SCOPE,
        )

    client = gspread.authorize(credentials)
    if has_request_context():
        g.gspread_client = client
    return client


def _get_spreadsheet():
    if has_request_context() and getattr(g, "google_spreadsheet", None):
        return g.google_spreadsheet

    client = _get_client()
    spreadsheet = client.open_by_key(current_app.config["GOOGLE_SHEET_ID"])
    if has_request_context():
        g.google_spreadsheet = spreadsheet
    return spreadsheet


def _get_sheet(sheet_name):
    spreadsheet = _get_spreadsheet()
    return spreadsheet.worksheet(sheet_name)


def _get_or_create_sheet(sheet_name, headers):
    spreadsheet = _get_spreadsheet()

    try:
        sheet = spreadsheet.worksheet(sheet_name)
    except WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(
            title=sheet_name,
            rows=1000,
            cols=max(len(headers), 1),
        )
        sheet.append_row(headers)

    existing_headers = sheet.row_values(1)
    if not existing_headers:
        sheet.append_row(headers)
    else:
        missing_headers = [header for header in headers if header not in existing_headers]
        if missing_headers:
            start_col = len(existing_headers) + 1
            end_col = start_col + len(missing_headers) - 1
            sheet.update(
                f"{_column_letter(start_col)}1:{_column_letter(end_col)}1",
                [missing_headers],
            )

    return sheet


def _get_material_sheet():
    return _get_or_create_sheet("材登録", MATERIAL_HEADERS)


def _column_letter(index):
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _normalize_ascii(value):
    if value is None:
        return ""

    text = str(value).strip()
    return text.translate(str.maketrans(
        "０１２３４５６７８９"
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
        "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
        "＠．＿－＋（）　",
        "0123456789"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "@._-+() ",
    ))


def _batch_update_row_raw(sheet, row_index, header_map, values_by_header):
    updates = []
    for field, value in values_by_header.items():
        col_index = header_map.get(field)
        if col_index:
            updates.append({
                "range": f"{_column_letter(col_index)}{row_index}",
                "values": [[value]],
            })

    if updates:
        sheet.batch_update(updates, value_input_option="RAW")


def _get_header_map(sheet):
    """Return mapping header_name -> 1-based column index."""
    headers = sheet.row_values(1)
    return {h: i + 1 for i, h in enumerate(headers)}


def _build_row_for_headers(sheet, values_by_header):
    headers = sheet.row_values(1)
    header_map = {h: i + 1 for i, h in enumerate(headers)}
    row = ["" for _ in headers]

    for key, value in values_by_header.items():
        if key in header_map:
            row[header_map[key] - 1] = value

    return row, header_map


def _set_row_value(row, header_map, name, value):
    if name in header_map:
        row[header_map[name] - 1] = value


def _build_user_row(headers, header_map, line_user_id, data):
    row = ["" for _ in headers]
    _set_row_value(row, header_map, "line_user_id", line_user_id)
    for field in USER_FIELDS:
        _set_row_value(row, header_map, field, data.get(field, ""))

    if "created_at" in header_map:
        _set_row_value(row, header_map, "created_at", _now())
    elif "createdAt" in header_map:
        _set_row_value(row, header_map, "createdAt", _now())

    return row


def _update_user_row(sheet, idx, header_map, line_user_id, data, record, update_timestamp=False):
    values = {}
    if header_map.get("line_user_id"):
        values["line_user_id"] = line_user_id

    for field in USER_FIELDS:
        if header_map.get(field):
            values[field] = data.get(field, record.get(field, ""))

    if update_timestamp:
        if header_map.get("updated_at"):
            values["updated_at"] = _now()
        if header_map.get("updatedAt"):
            values["updatedAt"] = _now()

    _batch_update_row_raw(sheet, idx, header_map, values)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_material(data):
    sheet = _get_material_sheet()
    material_id = f"mat_{uuid4().hex[:10]}"

    # line_user_id が空の場合、一意のIDを生成
    line_user_id = data.get("line_user_id", "").strip()
    if not line_user_id:
        line_user_id = f"anon_{uuid4().hex[:10]}"

    row, header_map = _build_row_for_headers(
        sheet,
        {
            "material_id": material_id,
            "line_user_id": line_user_id,
            "display_name": data.get("display_name", ""),
            "title": data.get("title", ""),
            "material_type": data.get("material_type", ""),
            "description": data.get("description", ""),
            "size": data.get("size", ""),
            "quantity": data.get("quantity", ""),
            "condition": data.get("condition", ""),
            "location": data.get("location", ""),
            "pickup_deadline": data.get("pickup_deadline", ""),
            "image_url": data.get("image_url", ""),
            "image_urls": data.get("image_urls", ""),
            "status": "募集中",
            "created_at": _now(),
        },
    )

    # Fallback for any sheets whose headers use camelCase
    if "createdAt" in header_map and "created_at" not in header_map:
        row[header_map["createdAt"] - 1] = _now()

    sheet.append_row(row)
    return material_id


def append_demolition_property(data):
    sheet = _get_or_create_sheet("解体物件登録", DEMOLITION_HEADERS)
    property_id = f"demo_{uuid4().hex[:10]}"
    line_user_id = _normalize_user_id(data)

    row, header_map = _build_row_for_headers(
        sheet,
        {
            "property_id": property_id,
            "line_user_id": line_user_id,
            "display_name": data.get("display_name", ""),
            "registrant_type": data.get("registrant_type", ""),
            "property_name": data.get("property_name", ""),
            "location": data.get("location", ""),
            "owner_name": data.get("owner_name", ""),
            "demolition_date": data.get("demolition_date", ""),
            "demolition_contractor": data.get("demolition_contractor", ""),
            "viewing_period": data.get("viewing_period", ""),
            "building_use": data.get("building_use", ""),
            "structure": data.get("structure", ""),
            "floors": data.get("floors", ""),
            "building_age": data.get("building_age", ""),
            "building_photo_url": data.get("building_photo_url", ""),
            "building_photo_urls": data.get("building_photo_urls", ""),
            "condition_evaluation": data.get("condition_evaluation", ""),
            "notes": data.get("notes", ""),
            "status": "登録済み",
            "created_at": _now(),
        },
    )

    if "createdAt" in header_map and "created_at" not in header_map:
        row[header_map["createdAt"] - 1] = _now()

    sheet.append_row(row)
    return property_id


def get_demolition_properties(include_all=False):
    sheet = _get_or_create_sheet("解体物件登録", DEMOLITION_HEADERS)
    records = sheet.get_all_records()

    if include_all:
        return records

    return [record for record in records if record.get("status") != "削除済み"]


def get_demolition_property_by_id(property_id):
    properties = get_demolition_properties(include_all=True)
    for property_record in properties:
        if property_record.get("property_id") == property_id:
            return property_record
    return None


def get_materials(include_all=False):
    sheet = _get_material_sheet()
    records = sheet.get_all_records()

    if include_all:
        return records

    return [record for record in records if record.get("status") == "募集中"]


def get_material_by_id(material_id):
    materials = get_materials(include_all=True)
    for material in materials:
        if material.get("material_id") == material_id:
            return material
    return None


def get_materials_by_line_user_id(line_user_id, include_all=False):
    materials = get_materials(include_all=True)
    filtered = [
        material
        for material in materials
        if material.get("line_user_id") == line_user_id
        and (include_all or material.get("status") != "削除済み")
    ]
    return filtered


def _matching_sheet_name(match_type="material"):
    if match_type == "viewing":
        return VIEWING_MATCHING_HISTORY_SHEET
    return MATERIAL_MATCHING_HISTORY_SHEET


def _get_matching_sheet(match_type="material"):
    return _get_or_create_sheet(_matching_sheet_name(match_type), MATCHING_HISTORY_HEADERS)


def append_matching_history(data, match_type="material"):
    sheet = _get_matching_sheet(match_type)
    match_id = f"match_{uuid4().hex[:10]}"

    row, _ = _build_row_for_headers(
        sheet,
        {
            "match_id": match_id,
            "material_id": data.get("material_id", ""),
            "property_id": data.get("property_id", ""),
            "provider_user_id": data.get("provider_user_id", ""),
            "requester_user_id": data.get("requester_user_id", ""),
            "action": data.get("action", ""),
            "message": data.get("message", ""),
            "status": data.get("status", "未対応"),
            "provider_contact_share_status": data.get("provider_contact_share_status", "not_requested"),
            "requester_contact_share_status": data.get("requester_contact_share_status", "not_requested"),
            "created_at": _now(),
            "updated_at": _now(),
        },
    )
    sheet.append_row(row)
    return match_id


def get_matching_history_by_user(line_user_id):
    history = []
    for match_type in ("material", "viewing"):
        try:
            sheet = _get_matching_sheet(match_type)
            records = sheet.get_all_records()
        except Exception:
            records = []

        for record in records:
            if (
                record.get("provider_user_id") == line_user_id
                or record.get("requester_user_id") == line_user_id
            ):
                record["match_type"] = match_type
                record["entry_id"] = record.get("material_id") or record.get("property_id")
                history.append(record)

    return sorted(history, key=lambda record: str(record.get("created_at", "")), reverse=True)


def get_matching_history_by_id(match_id, match_type="material"):
    sheet = _get_matching_sheet(match_type)
    records = sheet.get_all_records()
    for idx, record in enumerate(records, start=2):
        if record.get("match_id") == match_id:
            record["match_type"] = match_type
            record["entry_id"] = record.get("material_id") or record.get("property_id")
            return idx, record
    return None, None


def update_matching_contact_share_status(match_id, match_type, user_id, status):
    sheet = _get_matching_sheet(match_type)
    row_index, record = get_matching_history_by_id(match_id, match_type)
    if not row_index:
        return False

    if record.get("provider_user_id") == user_id:
        status_field = "provider_contact_share_status"
        shared_at_field = "provider_contact_shared_at"
    elif record.get("requester_user_id") == user_id:
        status_field = "requester_contact_share_status"
        shared_at_field = "requester_contact_shared_at"
    else:
        return False

    header_map = _get_header_map(sheet)
    now = _now()
    values = {status_field: status}
    if status == "shared":
        values[shared_at_field] = now
    values["updated_at"] = now
    _batch_update_row_raw(sheet, row_index, header_map, values)
    return True


def get_contact_card_by_user(line_user_id):
    sheet = _get_or_create_sheet(CONTACT_CARDS_SHEET, CONTACT_CARD_HEADERS)
    records = sheet.get_all_records(numericise_ignore=["all"])
    for record in records:
        if (
            record.get("line_user_id") == line_user_id
            or record.get("user_id") == line_user_id
        ):
            return record
    return None


def upsert_contact_card(line_user_id, data):
    sheet = _get_or_create_sheet(CONTACT_CARDS_SHEET, CONTACT_CARD_HEADERS)
    records = sheet.get_all_records(numericise_ignore=["all"])
    header_map = _get_header_map(sheet)
    now = _now()
    contact_card_id = ""
    row_index = None

    for idx, record in enumerate(records, start=2):
        if (
            record.get("line_user_id") == line_user_id
            or record.get("user_id") == line_user_id
        ):
            row_index = idx
            contact_card_id = record.get("contact_card_id", "")
            break

    if not contact_card_id:
        contact_card_id = f"contact_{uuid4().hex[:10]}"

    values = {
        "contact_card_id": contact_card_id,
        "user_id": line_user_id,
        "line_user_id": line_user_id,
        "display_name": data.get("contact_display_name") or data.get("display_name", ""),
        "contact_method": data.get("contact_method", ""),
        "contact_value": _normalize_ascii(data.get("contact_value", "")),
        "available_time": data.get("contact_available_time", ""),
        "message": data.get("contact_message", ""),
        "is_active": data.get("contact_is_active", "TRUE"),
        "updated_at": now,
    }

    if row_index:
        _batch_update_row_raw(sheet, row_index, header_map, values)
        return contact_card_id

    values["created_at"] = now
    row, _ = _build_row_for_headers(sheet, values)
    sheet.append_row(row, value_input_option="RAW")
    return contact_card_id


def append_contact_share_log(data):
    sheet = _get_or_create_sheet(CONTACT_SHARE_LOGS_SHEET, CONTACT_SHARE_LOG_HEADERS)
    now = _now()
    contact_share_id = f"share_{uuid4().hex[:10]}"
    row, _ = _build_row_for_headers(
        sheet,
        {
            "contact_share_id": contact_share_id,
            "match_id": data.get("match_id", ""),
            "match_type": data.get("match_type", ""),
            "from_user_id": data.get("from_user_id", ""),
            "to_user_id": data.get("to_user_id", ""),
            "share_status": data.get("share_status", "shared"),
            "shared_display_name": data.get("shared_display_name", ""),
            "shared_contact_method": data.get("shared_contact_method", ""),
            "shared_contact_value": _normalize_ascii(data.get("shared_contact_value", "")),
            "shared_available_time": data.get("shared_available_time", ""),
            "shared_message": data.get("shared_message", ""),
            "consent_version": data.get("consent_version", "contact_share_v1"),
            "requested_at": data.get("requested_at", ""),
            "shared_at": data.get("shared_at", now),
            "declined_at": data.get("declined_at", ""),
            "expires_at": data.get("expires_at", ""),
            "created_at": now,
            "updated_at": now,
        },
    )
    sheet.append_row(row, value_input_option="RAW")
    return contact_share_id


def record_contact_share(match_id, match_type, from_user_id):
    row_index, match = get_matching_history_by_id(match_id, match_type)
    if not row_index:
        return None, "match_not_found"

    if match.get("provider_user_id") == from_user_id:
        to_user_id = match.get("requester_user_id", "")
    elif match.get("requester_user_id") == from_user_id:
        to_user_id = match.get("provider_user_id", "")
    else:
        return None, "not_match_member"

    card = get_contact_card_by_user(from_user_id)
    if not card or not card.get("contact_value"):
        return None, "contact_card_missing"
    if str(card.get("is_active", "TRUE")).upper() in ("FALSE", "0", "NO", "OFF"):
        return None, "contact_card_inactive"

    shared_at = _now()
    share_id = append_contact_share_log(
        {
            "match_id": match_id,
            "match_type": match_type,
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "share_status": "shared",
            "shared_display_name": card.get("display_name", ""),
            "shared_contact_method": card.get("contact_method", ""),
            "shared_contact_value": card.get("contact_value", ""),
            "shared_available_time": card.get("available_time", ""),
            "shared_message": card.get("message", ""),
            "shared_at": shared_at,
        }
    )
    update_matching_contact_share_status(match_id, match_type, from_user_id, "shared")
    return {
        "contact_share_id": share_id,
        "match": match,
        "card": card,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "shared_at": shared_at,
    }, None


def append_user(data):
    """ユーザー情報を追加。line_user_id が既に存在する場合は更新。"""
    sheet = _get_sheet("ユーザー情報")
    line_user_id = _normalize_user_id(data)
    current_app.logger.info(f"append_user: resolved user_id={line_user_id}")

    # Try to find existing row
    records = sheet.get_all_records()
    idx, record = _find_user_row(records, line_user_id)
    header_map = _get_header_map(sheet)

    if idx:
        current_app.logger.info(f"append_user: found existing row {idx}, updating")
        _update_user_row(sheet, idx, header_map, line_user_id, data, record)
        return line_user_id

    # Build a row aligned to existing headers to avoid column order issues
    headers = sheet.row_values(1)
    row = _build_user_row(headers, header_map, line_user_id, data)

    current_app.logger.info(f"append_user: appending new row for {line_user_id}")
    sheet.append_row(row)
    return line_user_id


def get_user_by_line_user_id(line_user_id):
    """LINE user_id からユーザー情報を取得"""
    try:
        sheet = _get_sheet("ユーザー情報")
        records = sheet.get_all_records()
        for record in records:
            if (
                record.get("line_user_id") == line_user_id
                or record.get("user_id") == line_user_id
                or record.get("userid") == line_user_id
            ):
                return record
    except Exception:
        pass
    return None


def get_user_by_id(user_id):
    """互換性保持のため残す（LINE user_id で検索）"""
    return get_user_by_line_user_id(user_id)


def update_user(line_user_id, data):
    """ユーザー情報を更新。見つからない場合は新規追記する。"""
    try:
        sheet = _get_sheet("ユーザー情報")
        records = sheet.get_all_records()
        idx, record = _find_user_row(records, line_user_id)
        header_map = _get_header_map(sheet)
        if idx:
            current_app.logger.info(f"update_user: updating row {idx} for {line_user_id}")
            _update_user_row(sheet, idx, header_map, line_user_id, data, record, update_timestamp=True)
            return line_user_id

        # not found -> append new row aligned to headers
        headers = sheet.row_values(1)
        row = _build_user_row(headers, header_map, line_user_id, data)

        current_app.logger.info(f"update_user: no existing row, appending for {line_user_id}")
        sheet.append_row(row)
        return line_user_id
    except Exception:
        return None


def update_material_status(material_id, status):
    sheet = _get_material_sheet()
    records = sheet.get_all_records()

    headers = sheet.row_values(1)
    status_col = headers.index("status") + 1

    for index, record in enumerate(records, start=2):
        if record.get("material_id") == material_id:
            sheet.update_cell(index, status_col, status)
            return True

    return False


def delete_material(material_id):
    return update_material_status(material_id, "削除済み")
