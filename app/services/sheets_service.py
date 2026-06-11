from datetime import datetime
from uuid import uuid4

import gspread
from google.oauth2.service_account import Credentials
from flask import current_app

import json

SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]


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


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_material(data):
    sheet = _get_sheet("材登録")
    material_id = f"mat_{uuid4().hex[:10]}"
    
    # line_user_id が空の場合、一意のIDを生成
    line_user_id = data.get("line_user_id", "").strip()
    if not line_user_id:
        line_user_id = f"anon_{uuid4().hex[:10]}"

    row = [
        material_id,
        line_user_id,
        data.get("display_name", ""),
        data.get("title", ""),
        data.get("material_type", ""),
        data.get("description", ""),
        data.get("size", ""),
        data.get("quantity", ""),
        data.get("condition", ""),
        data.get("location", ""),
        data.get("pickup_deadline", ""),
        data.get("image_url", ""),
        "募集中",
        _now(),
    ]
    sheet.append_row(row)
    return material_id


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


def append_user(data):
    """ユーザー情報を追加。line_user_id が既に存在する場合は更新。"""
    sheet = _get_sheet("ユーザー情報")
    line_user_id = data.get("line_user_id", "").strip()
    
    # line_user_id が空の場合、一意のIDを生成
    if not line_user_id:
        line_user_id = f"anon_{uuid4().hex[:10]}"
    
    records = sheet.get_all_records()
    
    # 既存ユーザーを検索
    for idx, record in enumerate(records, start=2):
        if record.get("line_user_id") == line_user_id:
            # 更新
            sheet.update_cell(idx, 2, data.get("display_name", ""))
            sheet.update_cell(idx, 3, data.get("address", ""))
            sheet.update_cell(idx, 4, data.get("transport_info", ""))
            return line_user_id
    
    # 新規作成
    row = [
        line_user_id,
        data.get("display_name", ""),
        data.get("address", ""),
        data.get("transport_info", ""),
        _now(),
    ]
    sheet.append_row(row)
    return line_user_id


def get_user_by_line_user_id(line_user_id):
    """LINE user_id からユーザー情報を取得"""
    try:
        sheet = _get_sheet("ユーザー情報")
        records = sheet.get_all_records()
        for record in records:
            if record.get("line_user_id") == line_user_id:
                return record
    except Exception:
        pass
    return None


def get_user_by_id(user_id):
    """互換性保持のため残す（LINE user_id で検索）"""
    return get_user_by_line_user_id(user_id)


def update_user(line_user_id, data):
    """ユーザー情報を更新"""
    try:
        sheet = _get_sheet("ユーザー情報")
        records = sheet.get_all_records()
        
        for idx, record in enumerate(records, start=2):
            if record.get("line_user_id") == line_user_id:
                sheet.update_cell(idx, 2, data.get("display_name", ""))
                sheet.update_cell(idx, 3, data.get("address", ""))
                sheet.update_cell(idx, 4, data.get("transport_info", ""))
                return line_user_id
        return None
    except Exception:
        return None


def upsert_user(data):
    sheet = _get_sheet("ユーザー情報")
    records = sheet.get_all_records()
    user_id = data.get("user_id")

    for index, record in enumerate(records, start=2):
        if record.get("user_id") == user_id:
            sheet.update(f"A{index}:E{index}", [[
                user_id,
                data.get("display_name", ""),
                data.get("picture_url", ""),
                record.get("role", ""),
                _now(),
            ]])
            return

    sheet.append_row([
        user_id,
        data.get("display_name", ""),
        data.get("picture_url", ""),
        "",
        _now(),
    ])


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
