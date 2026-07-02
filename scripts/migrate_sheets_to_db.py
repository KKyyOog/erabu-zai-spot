from pathlib import Path
import sys

from gspread.exceptions import WorksheetNotFound

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from app.services import db_service, sheets_service


USER_SHEET_NAME = "ユーザー情報"


def _safe_records(label, loader):
    try:
        records = loader()
        print(f"{label}: loaded {len(records)} rows")
        return records
    except WorksheetNotFound:
        print(f"{label}: sheet not found, skipped")
    except Exception as exc:
        print(f"{label}: failed, skipped ({exc})")
    return []


def _sheet_records(sheet):
    return sheet.get_all_records(numericise_ignore=["all"])


def migrate():
    app = create_app()

    with app.app_context():
        counts = {
            "users": 0,
            "materials": 0,
            "demolition_properties": 0,
            "matching_history": 0,
            "contact_cards": 0,
            "contact_share_logs": 0,
        }

        for record in _safe_records(
            "users",
            lambda: _sheet_records(sheets_service._get_sheet(USER_SHEET_NAME)),
        ):
            if db_service.upsert_user_record(record):
                counts["users"] += 1

        for record in _safe_records(
            "materials",
            lambda: sheets_service.get_materials(include_all=True),
        ):
            if db_service.upsert_material_record(record):
                counts["materials"] += 1

        for record in _safe_records(
            "demolition_properties",
            lambda: sheets_service.get_demolition_properties(include_all=True),
        ):
            if db_service.upsert_demolition_property_record(record):
                counts["demolition_properties"] += 1

        for match_type in ("material", "viewing"):
            for record in _safe_records(
                f"matching_history:{match_type}",
                lambda match_type=match_type: _sheet_records(sheets_service._get_matching_sheet(match_type)),
            ):
                if db_service.upsert_matching_history_record(record, match_type=match_type):
                    counts["matching_history"] += 1

        for record in _safe_records(
            "contact_cards",
            lambda: _sheet_records(
                sheets_service._get_or_create_sheet(
                    sheets_service.CONTACT_CARDS_SHEET,
                    sheets_service.CONTACT_CARD_HEADERS,
                )
            ),
        ):
            if db_service.upsert_contact_card_record(record):
                counts["contact_cards"] += 1

        for record in _safe_records(
            "contact_share_logs",
            lambda: _sheet_records(
                sheets_service._get_or_create_sheet(
                    sheets_service.CONTACT_SHARE_LOGS_SHEET,
                    sheets_service.CONTACT_SHARE_LOG_HEADERS,
                )
            ),
        ):
            if db_service.upsert_contact_share_log_record(record):
                counts["contact_share_logs"] += 1

        print("migration complete")
        for label, count in counts.items():
            print(f"{label}: upserted {count}")


if __name__ == "__main__":
    migrate()
