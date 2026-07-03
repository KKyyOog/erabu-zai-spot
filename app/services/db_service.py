from datetime import datetime
import json
from uuid import uuid4
import unicodedata

from flask import current_app
from sqlalchemy import (
    Column,
    Index,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    or_,
    select,
    update,
)


MATERIAL_ACTIVE_STATUS = "募集中"
DEMOLITION_ACTIVE_STATUS = "登録済み"
DELETED_STATUS = "削除済み"
MATCH_DEFAULT_STATUS = "未対応"

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("line_user_id", String(255), primary_key=True),
    Column("user_id", String(255), index=True),
    Column("userid", String(255), index=True),
    Column("display_name", Text, nullable=False, default=""),
    Column("address", Text, nullable=False, default=""),
    Column("transport_info", Text, nullable=False, default=""),
    Column("created_at", String(32), nullable=False, default=""),
    Column("updated_at", String(32), nullable=False, default=""),
)

materials = Table(
    "materials",
    metadata,
    Column("material_id", String(64), primary_key=True),
    Column("line_user_id", String(255), index=True, nullable=False, default=""),
    Column("display_name", Text, nullable=False, default=""),
    Column("title", Text, nullable=False, default=""),
    Column("material_type", Text, nullable=False, default=""),
    Column("description", Text, nullable=False, default=""),
    Column("size", Text, nullable=False, default=""),
    Column("quantity", Text, nullable=False, default=""),
    Column("condition", Text, nullable=False, default=""),
    Column("location", Text, nullable=False, default=""),
    Column("pickup_deadline", Text, nullable=False, default=""),
    Column("image_url", Text, nullable=False, default=""),
    Column("image_urls", Text, nullable=False, default=""),
    Column("status", String(64), index=True, nullable=False, default=MATERIAL_ACTIVE_STATUS),
    Column("created_at", String(32), index=True, nullable=False, default=""),
)

demolition_properties = Table(
    "demolition_properties",
    metadata,
    Column("property_id", String(64), primary_key=True),
    Column("line_user_id", String(255), index=True, nullable=False, default=""),
    Column("display_name", Text, nullable=False, default=""),
    Column("registrant_type", Text, nullable=False, default=""),
    Column("property_name", Text, nullable=False, default=""),
    Column("location", Text, nullable=False, default=""),
    Column("owner_name", Text, nullable=False, default=""),
    Column("demolition_date", Text, nullable=False, default=""),
    Column("demolition_contractor", Text, nullable=False, default=""),
    Column("viewing_period", Text, nullable=False, default=""),
    Column("building_use", Text, nullable=False, default=""),
    Column("structure", Text, nullable=False, default=""),
    Column("floors", Text, nullable=False, default=""),
    Column("building_age", Text, nullable=False, default=""),
    Column("building_photo_url", Text, nullable=False, default=""),
    Column("building_photo_urls", Text, nullable=False, default=""),
    Column("condition_evaluation", Text, nullable=False, default=""),
    Column("notes", Text, nullable=False, default=""),
    Column("status", String(64), index=True, nullable=False, default=DEMOLITION_ACTIVE_STATUS),
    Column("created_at", String(32), index=True, nullable=False, default=""),
)

matching_history = Table(
    "matching_history",
    metadata,
    Column("match_id", String(64), primary_key=True),
    Column("match_type", String(32), index=True, nullable=False, default="material"),
    Column("material_id", String(64), index=True, nullable=False, default=""),
    Column("property_id", String(64), index=True, nullable=False, default=""),
    Column("provider_user_id", String(255), index=True, nullable=False, default=""),
    Column("requester_user_id", String(255), index=True, nullable=False, default=""),
    Column("action", Text, nullable=False, default=""),
    Column("message", Text, nullable=False, default=""),
    Column("status", String(64), nullable=False, default=MATCH_DEFAULT_STATUS),
    Column("provider_contact_share_status", String(64), nullable=False, default="not_requested"),
    Column("requester_contact_share_status", String(64), nullable=False, default="not_requested"),
    Column("provider_contact_shared_at", String(32), nullable=False, default=""),
    Column("requester_contact_shared_at", String(32), nullable=False, default=""),
    Column("created_at", String(32), index=True, nullable=False, default=""),
    Column("updated_at", String(32), nullable=False, default=""),
)

contact_cards = Table(
    "contact_cards",
    metadata,
    Column("contact_card_id", String(64), primary_key=True),
    Column("user_id", String(255), index=True, nullable=False, default=""),
    Column("line_user_id", String(255), unique=True, index=True, nullable=False, default=""),
    Column("display_name", Text, nullable=False, default=""),
    Column("contact_method", Text, nullable=False, default=""),
    Column("contact_value", Text, nullable=False, default=""),
    Column("available_time", Text, nullable=False, default=""),
    Column("message", Text, nullable=False, default=""),
    Column("is_active", String(16), nullable=False, default="TRUE"),
    Column("created_at", String(32), nullable=False, default=""),
    Column("updated_at", String(32), nullable=False, default=""),
)

contact_share_logs = Table(
    "contact_share_logs",
    metadata,
    Column("contact_share_id", String(64), primary_key=True),
    Column("match_id", String(64), index=True, nullable=False, default=""),
    Column("match_type", String(32), index=True, nullable=False, default=""),
    Column("from_user_id", String(255), index=True, nullable=False, default=""),
    Column("to_user_id", String(255), index=True, nullable=False, default=""),
    Column("share_status", String(64), nullable=False, default="shared"),
    Column("shared_display_name", Text, nullable=False, default=""),
    Column("shared_contact_method", Text, nullable=False, default=""),
    Column("shared_contact_value", Text, nullable=False, default=""),
    Column("shared_available_time", Text, nullable=False, default=""),
    Column("shared_message", Text, nullable=False, default=""),
    Column("consent_version", String(64), nullable=False, default="contact_share_v1"),
    Column("requested_at", String(32), nullable=False, default=""),
    Column("shared_at", String(32), nullable=False, default=""),
    Column("declined_at", String(32), nullable=False, default=""),
    Column("expires_at", String(32), nullable=False, default=""),
    Column("created_at", String(32), nullable=False, default=""),
    Column("updated_at", String(32), nullable=False, default=""),
)

Index("ix_matching_history_member_created", matching_history.c.provider_user_id, matching_history.c.created_at)
Index("ix_matching_history_requester_created", matching_history.c.requester_user_id, matching_history.c.created_at)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_database_url(url):
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    sslmode = current_app.config.get("DATABASE_SSLMODE", "")
    if url.startswith("postgresql+psycopg://") and sslmode and "sslmode=" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}sslmode={sslmode}"

    return url


def init_database(app):
    database_url = app.config["DATABASE_URL"]
    with app.app_context():
        engine = create_engine(_normalize_database_url(database_url), pool_pre_ping=True, future=True)
    app.extensions["database_engine"] = engine

    if app.config.get("AUTO_CREATE_TABLES", True):
        metadata.create_all(engine)


def _engine():
    return current_app.extensions["database_engine"]


def _normalize_user_id(data=None, fallback=""):
    data = data or {}
    user_id = (data.get("line_user_id") or data.get("user_id") or data.get("userid") or fallback or "").strip()
    if user_id:
        return user_id
    return f"anon_{uuid4().hex[:10]}"


def _normalize_ascii(value):
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row._mapping)


def _record_values(table, record, defaults=None):
    defaults = defaults or {}
    values = {}
    for column in table.columns:
        if column.name in record:
            value = record.get(column.name)
        else:
            value = defaults.get(column.name, "")
        values[column.name] = "" if value is None else value
    return values


def _upsert_by_pk(table, pk_name, record, defaults=None):
    values = _record_values(table, record, defaults)
    pk_value = values.get(pk_name)
    if not pk_value:
        return None

    with _engine().begin() as conn:
        exists = conn.execute(select(table.c[pk_name]).where(table.c[pk_name] == pk_value)).first()
        if exists:
            conn.execute(update(table).where(table.c[pk_name] == pk_value).values(**values))
        else:
            conn.execute(table.insert().values(**values))
    return pk_value


def _select_one(table, condition):
    with _engine().connect() as conn:
        return _row_to_dict(conn.execute(select(table).where(condition)).first())


def _select_many(stmt):
    with _engine().connect() as conn:
        return [_row_to_dict(row) for row in conn.execute(stmt).all()]


def append_material(data):
    material_id = f"mat_{uuid4().hex[:10]}"
    line_user_id = _normalize_user_id(data)
    values = _record_values(
        materials,
        data,
        {
            "material_id": material_id,
            "line_user_id": line_user_id,
            "status": MATERIAL_ACTIVE_STATUS,
            "created_at": _now(),
        },
    )
    values["material_id"] = material_id
    values["line_user_id"] = line_user_id

    with _engine().begin() as conn:
        conn.execute(materials.insert().values(**values))
    return material_id


def upsert_material_record(record):
    defaults = {"status": MATERIAL_ACTIVE_STATUS, "created_at": _now()}
    return _upsert_by_pk(materials, "material_id", record, defaults)


def append_demolition_property(data):
    property_id = f"demo_{uuid4().hex[:10]}"
    line_user_id = _normalize_user_id(data)
    values = _record_values(
        demolition_properties,
        data,
        {
            "property_id": property_id,
            "line_user_id": line_user_id,
            "status": DEMOLITION_ACTIVE_STATUS,
            "created_at": _now(),
        },
    )
    values["property_id"] = property_id
    values["line_user_id"] = line_user_id

    with _engine().begin() as conn:
        conn.execute(demolition_properties.insert().values(**values))
    return property_id


def upsert_demolition_property_record(record):
    defaults = {"status": DEMOLITION_ACTIVE_STATUS, "created_at": _now()}
    return _upsert_by_pk(demolition_properties, "property_id", record, defaults)


def get_demolition_properties(include_all=False):
    stmt = select(demolition_properties).order_by(demolition_properties.c.created_at)
    if not include_all:
        stmt = stmt.where(demolition_properties.c.status != DELETED_STATUS)
    return _select_many(stmt)


def get_demolition_property_by_id(property_id):
    return _select_one(demolition_properties, demolition_properties.c.property_id == property_id)


def get_materials(include_all=False):
    stmt = select(materials).order_by(materials.c.created_at)
    if not include_all:
        stmt = stmt.where(materials.c.status == MATERIAL_ACTIVE_STATUS)
    return _select_many(stmt)


def get_material_by_id(material_id):
    return _select_one(materials, materials.c.material_id == material_id)


def get_materials_by_line_user_id(line_user_id, include_all=False):
    stmt = select(materials).where(materials.c.line_user_id == line_user_id).order_by(materials.c.created_at)
    if not include_all:
        stmt = stmt.where(materials.c.status != DELETED_STATUS)
    return [_decorate_material_record(record) for record in _select_many(stmt)]


def get_provider_shared_material_ids():
    stmt = select(matching_history.c.material_id).where(
        matching_history.c.match_type == "material",
        matching_history.c.provider_contact_share_status == "shared",
        matching_history.c.material_id != "",
    )
    with _engine().connect() as conn:
        return {row[0] for row in conn.execute(stmt).all() if row[0]}


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


def _collect_image_urls(record, primary_field, collection_field):
    urls = []
    seen = set()
    for url in _split_image_urls(record.get(collection_field, "")) + _split_image_urls(record.get(primary_field, "")):
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def _decorate_material_record(record):
    if not record:
        return record

    image_urls = _collect_image_urls(record, "image_url", "image_urls")
    record["image_urls"] = image_urls
    record["image_url"] = image_urls[0] if image_urls else record.get("image_url", "")
    return record


def _decorate_match_record(record):
    record["entry_id"] = record.get("material_id") or record.get("property_id")
    record["entry_title"] = ""
    record["entry_image_url"] = ""

    if record.get("match_type") == "viewing":
        entry = get_demolition_property_by_id(record.get("property_id", ""))
        if entry:
            image_urls = _collect_image_urls(entry, "building_photo_url", "building_photo_urls")
            record["entry_title"] = entry.get("property_name", "")
            record["entry_image_url"] = image_urls[0] if image_urls else ""
    else:
        entry = get_material_by_id(record.get("material_id", ""))
        if entry:
            image_urls = _collect_image_urls(entry, "image_url", "image_urls")
            record["entry_title"] = entry.get("title", "")
            record["entry_image_url"] = image_urls[0] if image_urls else ""

    return record


def append_matching_history(data, match_type="material"):
    match_id = f"match_{uuid4().hex[:10]}"
    now = _now()
    values = _record_values(
        matching_history,
        data,
        {
            "match_id": match_id,
            "match_type": match_type,
            "status": MATCH_DEFAULT_STATUS,
            "provider_contact_share_status": "not_requested",
            "requester_contact_share_status": "not_requested",
            "created_at": now,
            "updated_at": now,
        },
    )
    values["match_type"] = match_type
    values["match_id"] = match_id

    with _engine().begin() as conn:
        conn.execute(matching_history.insert().values(**values))
    return match_id


def upsert_matching_history_record(record, match_type="material"):
    record = dict(record)
    record["match_type"] = record.get("match_type") or match_type
    now = _now()
    defaults = {
        "match_type": match_type,
        "status": MATCH_DEFAULT_STATUS,
        "provider_contact_share_status": "not_requested",
        "requester_contact_share_status": "not_requested",
        "created_at": now,
        "updated_at": now,
    }
    return _upsert_by_pk(matching_history, "match_id", record, defaults)


def get_matching_history_by_user(line_user_id):
    stmt = (
        select(matching_history)
        .where(
            or_(
                matching_history.c.provider_user_id == line_user_id,
                matching_history.c.requester_user_id == line_user_id,
            )
        )
        .order_by(matching_history.c.created_at.desc())
    )
    history = _select_many(stmt)
    for record in history:
        _decorate_match_record(record)
    return history


def get_matching_history_by_id(match_id, match_type="material"):
    stmt = select(matching_history).where(
        matching_history.c.match_id == match_id,
        matching_history.c.match_type == match_type,
    )
    records = _select_many(stmt)
    if not records:
        return None, None
    record = records[0]
    _decorate_match_record(record)
    return 1, record


def update_matching_contact_share_status(match_id, match_type, user_id, status):
    _, record = get_matching_history_by_id(match_id, match_type)
    if not record:
        return False

    if record.get("provider_user_id") == user_id:
        status_field = "provider_contact_share_status"
        shared_at_field = "provider_contact_shared_at"
    elif record.get("requester_user_id") == user_id:
        status_field = "requester_contact_share_status"
        shared_at_field = "requester_contact_shared_at"
    else:
        return False

    values = {status_field: status, "updated_at": _now()}
    if status == "shared":
        values[shared_at_field] = _now()

    with _engine().begin() as conn:
        conn.execute(
            update(matching_history)
            .where(matching_history.c.match_id == match_id, matching_history.c.match_type == match_type)
            .values(**values)
        )
    return True


def get_contact_card_by_user(line_user_id):
    stmt = select(contact_cards).where(
        or_(contact_cards.c.line_user_id == line_user_id, contact_cards.c.user_id == line_user_id)
    )
    records = _select_many(stmt)
    return records[0] if records else None


def upsert_contact_card(line_user_id, data):
    existing = get_contact_card_by_user(line_user_id)
    now = _now()
    contact_card_id = existing.get("contact_card_id") if existing else f"contact_{uuid4().hex[:10]}"
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

    with _engine().begin() as conn:
        if existing:
            conn.execute(update(contact_cards).where(contact_cards.c.contact_card_id == contact_card_id).values(**values))
        else:
            values["created_at"] = now
            conn.execute(contact_cards.insert().values(**_record_values(contact_cards, values)))
    return contact_card_id


def upsert_contact_card_record(record):
    defaults = {"is_active": "TRUE", "created_at": _now(), "updated_at": _now()}
    return _upsert_by_pk(contact_cards, "contact_card_id", record, defaults)


def append_contact_share_log(data):
    now = _now()
    contact_share_id = f"share_{uuid4().hex[:10]}"
    values = _record_values(
        contact_share_logs,
        data,
        {
            "contact_share_id": contact_share_id,
            "share_status": "shared",
            "consent_version": "contact_share_v1",
            "shared_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )
    values["contact_share_id"] = contact_share_id

    with _engine().begin() as conn:
        conn.execute(contact_share_logs.insert().values(**values))
    return contact_share_id


def upsert_contact_share_log_record(record):
    defaults = {"share_status": "shared", "consent_version": "contact_share_v1", "created_at": _now(), "updated_at": _now()}
    return _upsert_by_pk(contact_share_logs, "contact_share_id", record, defaults)


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
    line_user_id = _normalize_user_id(data)
    now = _now()
    existing = get_user_by_line_user_id(line_user_id)
    values = {
        "line_user_id": line_user_id,
        "user_id": line_user_id,
        "userid": line_user_id,
        "display_name": data.get("display_name", existing.get("display_name", "") if existing else ""),
        "address": data.get("address", existing.get("address", "") if existing else ""),
        "transport_info": data.get("transport_info", existing.get("transport_info", "") if existing else ""),
        "updated_at": now,
    }

    with _engine().begin() as conn:
        if existing:
            conn.execute(update(users).where(users.c.line_user_id == line_user_id).values(**values))
        else:
            values["created_at"] = now
            conn.execute(users.insert().values(**_record_values(users, values)))
    return line_user_id


def upsert_user_record(record):
    record = dict(record)
    line_user_id = _normalize_user_id(record)
    record["line_user_id"] = line_user_id
    record["user_id"] = record.get("user_id") or line_user_id
    record["userid"] = record.get("userid") or line_user_id
    defaults = {"created_at": _now(), "updated_at": _now()}
    return _upsert_by_pk(users, "line_user_id", record, defaults)


def get_user_by_line_user_id(line_user_id):
    stmt = select(users).where(
        or_(users.c.line_user_id == line_user_id, users.c.user_id == line_user_id, users.c.userid == line_user_id)
    )
    records = _select_many(stmt)
    return records[0] if records else None


def get_user_by_id(user_id):
    return get_user_by_line_user_id(user_id)


def update_user(line_user_id, data):
    data = dict(data)
    data["line_user_id"] = line_user_id
    return append_user(data)


def update_material_status(material_id, status):
    with _engine().begin() as conn:
        result = conn.execute(update(materials).where(materials.c.material_id == material_id).values(status=status))
    return result.rowcount > 0


def delete_material(material_id):
    return update_material_status(material_id, DELETED_STATUS)


def update_material(material_id, line_user_id, data):
    existing = get_material_by_id(material_id)
    if not existing or existing.get("line_user_id") != line_user_id:
        return None

    allowed_fields = (
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
    )
    values = {field: data.get(field, existing.get(field, "")) for field in allowed_fields}

    with _engine().begin() as conn:
        result = conn.execute(update(materials).where(materials.c.material_id == material_id).values(**values))

    if result.rowcount <= 0:
        return None

    updated = get_material_by_id(material_id)
    return _decorate_material_record(updated)
