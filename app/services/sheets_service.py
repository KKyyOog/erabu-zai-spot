from datetime import datetime
from uuid import uuid4

import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials
from flask import current_app

import json

SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]

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
    "condition_evaluation",
    "notes",
    "status",
    "created_at",
]

USER_FIELDS = ("display_name", "address", "transport_info")


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

    return gspread.authorize(credentials)


def _get_sheet(sheet_name):
    client = _get_client()
    spreadsheet = client.open_by_key(current_app.config["GOOGLE_SHEET_ID"])
    return spreadsheet.worksheet(sheet_name)


def _get_or_create_sheet(sheet_name, headers):
    client = _get_client()
    spreadsheet = client.open_by_key(current_app.config["GOOGLE_SHEET_ID"])

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

    return sheet


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
    if header_map.get("line_user_id"):
        sheet.update_cell(idx, header_map["line_user_id"], line_user_id)

    for field in USER_FIELDS:
        if header_map.get(field):
            sheet.update_cell(idx, header_map[field], data.get(field, record.get(field, "")))

    if update_timestamp:
        if header_map.get("updated_at"):
            sheet.update_cell(idx, header_map["updated_at"], _now())
        if header_map.get("updatedAt"):
            sheet.update_cell(idx, header_map["updatedAt"], _now())


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_material(data):
    sheet = _get_sheet("材登録")
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
    sheet = _get_sheet("材登録")
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


def append_matching_history(data):
    sheet = _get_sheet("マッチング履歴")
    match_id = f"match_{uuid4().hex[:10]}"

    row = [
        match_id,
        data.get("material_id", ""),
        data.get("provider_user_id", ""),
        data.get("requester_user_id", ""),
        data.get("action", ""),
        data.get("message", ""),
        data.get("status", "未対応"),
        _now(),
    ]
    sheet.append_row(row)
    return match_id


def get_matching_history_by_user(line_user_id):
    sheet = _get_sheet("マッチング履歴")
    records = sheet.get_all_records()
    return [
        record
        for record in records
        if record.get("provider_user_id") == line_user_id
        or record.get("requester_user_id") == line_user_id
    ]


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
    sheet = _get_sheet("材登録")
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
