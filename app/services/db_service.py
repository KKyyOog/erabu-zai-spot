from datetime import datetime, timedelta
import json
import hashlib
from urllib.parse import urlparse, urlencode
from uuid import uuid4
import unicodedata

from flask import current_app
from sqlalchemy import (
    Boolean,
    Column,
    delete,
    Index,
    Integer,
    func,
    false,
    union_all,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    literal,
    or_,
    select,
    true,
    update,
)


MATERIAL_ACTIVE_STATUS = "募集中"
DEMOLITION_ACTIVE_STATUS = "登録済み"
DELETED_STATUS = "削除済み"
MATCH_DEFAULT_STATUS = "未対応"
POST_TYPE_OFFER = "offer"
POST_TYPE_REQUEST = "request"
POST_STATUS_ACTIVE = "active"
POST_STATUS_CLOSED = "closed"
POST_STATUS_EXPIRED = "expired"
POST_TTL_DAYS = 30

metadata = MetaData()

operations = Table(
    "operations", metadata,
    Column("event_id", String(64), primary_key=True),
    Column("kind", String(64), nullable=False, index=True),
    Column("subject_id", String(255), nullable=False, default=""),
    Column("actor_id", String(255), nullable=False, default=""),
    Column("detail", Text, nullable=False, default=""),
    Column("created_at", Integer, nullable=False, index=True),
)
Index("ix_operations_kind_subject_created", operations.c.kind, operations.c.subject_id, operations.c.created_at)
Index("ix_operations_kind_created", operations.c.kind, operations.c.created_at)

image_upload_jobs = Table(
    "image_upload_jobs", metadata,
    Column("public_id", String(255), primary_key=True),
    Column("created_at", Integer, nullable=False, index=True),
)

request_buckets = Table(
    "request_buckets", metadata,
    Column("bucket_key", String(64), primary_key=True),
    Column("count", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False, index=True),
)

notification_outbox = Table(
    "notification_outbox", metadata,
    Column("notification_id", String(64), primary_key=True),
    Column("app_user_id", String(255), nullable=False),
    Column("target_user_id", String(255), nullable=False),
    Column("message", Text, nullable=False),
    Column("retry_key", String(36), nullable=False),
    Column("status", String(16), nullable=False, index=True),
    Column("attempts", Integer, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("next_attempt_at", Integer, nullable=False, index=True),
)

users = Table(
    "users",
    metadata,
    Column("line_user_id", String(255), primary_key=True),
    Column("user_id", String(255), index=True),
    Column("userid", String(255), index=True),
    Column("display_name", Text, nullable=False, default=""),
    Column("business_name", Text, nullable=False, default=""),
    Column("user_category", String(100), nullable=False, default=""),
    Column("area", String(100), nullable=False, default=""),
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
    Column("post_type", String(16), index=True, nullable=False, default=POST_TYPE_OFFER),
    Column("quantity_level", String(64), nullable=False, default=""),
    Column("usage_purpose", String(100), nullable=False, default=""),
    Column("status", String(64), index=True, nullable=False, default=MATERIAL_ACTIVE_STATUS),
    Column("expires_at", String(32), index=True, nullable=False, default=""),
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

line_notification_links = Table(
    "line_notification_links",
    metadata,
    Column("app_user_id", String(255), primary_key=True),
    Column("line_user_id", String(255), unique=True, index=True, nullable=False),
    Column("created_at", String(32), nullable=False, default=""),
    Column("updated_at", String(32), nullable=False, default=""),
)

line_notification_link_codes = Table(
    "line_notification_link_codes",
    metadata,
    Column("code_hash", String(64), primary_key=True),
    Column("app_user_id", String(255), index=True, nullable=False),
    Column("expires_at", String(32), index=True, nullable=False),
    Column("used_at", String(32), nullable=False, default=""),
    Column("created_at", String(32), nullable=False, default=""),
)

line_friendships = Table(
    "line_friendships",
    metadata,
    Column("line_user_id", String(255), primary_key=True),
    Column("is_friend", Boolean, nullable=False, default=False),
    Column("updated_at", String(32), nullable=False, default=""),
)

Index("ix_matching_history_member_created", matching_history.c.provider_user_id, matching_history.c.created_at)
Index("ix_matching_history_requester_created", matching_history.c.requester_user_id, matching_history.c.created_at)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_operation(conn, kind, subject_id="", actor_id="", detail=""):
    import time
    conn.execute(operations.insert().values(event_id=uuid4().hex, kind=kind,
        subject_id=subject_id, actor_id=actor_id, detail=detail, created_at=int(time.time())))


def _expires_after(days=POST_TTL_DAYS):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _effective_post_type(record):
    post_type = str((record or {}).get("post_type") or "").strip().lower()
    return post_type if post_type in (POST_TYPE_OFFER, POST_TYPE_REQUEST) else POST_TYPE_OFFER


def _effective_post_status(record, now=None):
    record = record or {}
    status = str(record.get("status") or "").strip()
    if status == DELETED_STATUS:
        return "deleted"
    if status in (POST_STATUS_CLOSED, "交渉中", "引取済み", "廃棄予定"):
        return POST_STATUS_CLOSED
    if status == POST_STATUS_EXPIRED:
        return POST_STATUS_EXPIRED

    expires_at = str(record.get("expires_at") or "").strip()
    if expires_at and expires_at < (now or _now()):
        return POST_STATUS_EXPIRED
    return POST_STATUS_ACTIVE


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
    else:
        metadata.create_all(
            engine,
            tables=[
                operations,
                image_upload_jobs,
                request_buckets,
                notification_outbox,
                line_notification_links,
                line_notification_link_codes,
                line_friendships,
            ],
            checkfirst=True,
        )


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


def create_line_notification_link_code(app_user_id, code_hash, expires_at):
    if not app_user_id or not code_hash or not expires_at:
        return False

    now = _now()
    with _engine().begin() as conn:
        conn.execute(
            update(line_notification_link_codes)
            .where(
                line_notification_link_codes.c.app_user_id == app_user_id,
                line_notification_link_codes.c.used_at == "",
            )
            .values(used_at=now)
        )
        conn.execute(
            line_notification_link_codes.insert().values(
                code_hash=code_hash,
                app_user_id=app_user_id,
                expires_at=expires_at,
                used_at="",
                created_at=now,
            )
        )
    return True


def consume_line_notification_link_code(code_hash, line_user_id):
    if not code_hash or not line_user_id:
        return None, "invalid"

    now = _now()
    with _engine().begin() as conn:
        row = conn.execute(
            select(line_notification_link_codes).where(
                line_notification_link_codes.c.code_hash == code_hash
            )
        ).first()
        code_record = _row_to_dict(row)
        if not code_record:
            return None, "invalid"

        existing_link = conn.execute(
            select(line_notification_links).where(
                line_notification_links.c.app_user_id
                == code_record["app_user_id"]
            )
        ).first()
        existing_link = _row_to_dict(existing_link)

        if code_record.get("used_at"):
            if (
                existing_link
                and existing_link.get("line_user_id") == line_user_id
            ):
                return existing_link, "already_linked"
            return None, "used"
        if code_record.get("expires_at", "") < now:
            return None, "expired"

        line_owner = conn.execute(
            select(line_notification_links).where(
                line_notification_links.c.line_user_id == line_user_id
            )
        ).first()
        line_owner = _row_to_dict(line_owner)
        if (
            line_owner
            and line_owner.get("app_user_id") != code_record["app_user_id"]
        ):
            return None, "line_already_linked"

        claimed = conn.execute(
            update(line_notification_link_codes)
            .where(
                line_notification_link_codes.c.code_hash == code_hash,
                line_notification_link_codes.c.used_at == "",
                line_notification_link_codes.c.expires_at >= now,
            )
            .values(used_at=now)
        )
        if claimed.rowcount <= 0:
            return None, "used"

        values = {
            "line_user_id": line_user_id,
            "updated_at": now,
        }
        if existing_link:
            conn.execute(
                update(line_notification_links)
                .where(
                    line_notification_links.c.app_user_id
                    == code_record["app_user_id"]
                )
                .values(**values)
            )
        else:
            conn.execute(
                line_notification_links.insert().values(
                    app_user_id=code_record["app_user_id"],
                    created_at=now,
                    **values,
                )
            )

        return {
            "app_user_id": code_record["app_user_id"],
            "line_user_id": line_user_id,
        }, "linked"


def get_line_notification_link(app_user_id):
    if not app_user_id:
        return None
    return _select_one(
        line_notification_links,
        line_notification_links.c.app_user_id == app_user_id,
    )


def get_notification_line_user_id(app_user_id):
    if not app_user_id:
        return ""
    if not app_user_id.startswith("anon_"):
        if app_user_id.startswith("U"):
            friendship = get_line_friendship(app_user_id)
            if not friendship or not friendship.get("is_friend"):
                return ""
        return app_user_id

    link = get_line_notification_link(app_user_id)
    return link.get("line_user_id", "") if link else ""


def set_line_friendship(line_user_id, is_friend):
    if not line_user_id or line_user_id.startswith("anon_"):
        return False

    now = _now()
    with _engine().begin() as conn:
        existing = conn.execute(
            select(line_friendships.c.line_user_id).where(
                line_friendships.c.line_user_id == line_user_id
            )
        ).first()
        if existing:
            conn.execute(
                update(line_friendships)
                .where(line_friendships.c.line_user_id == line_user_id)
                .values(is_friend=bool(is_friend), updated_at=now)
            )
        else:
            conn.execute(
                line_friendships.insert().values(
                    line_user_id=line_user_id,
                    is_friend=bool(is_friend),
                    updated_at=now,
                )
            )
    return True


def get_line_friendship(line_user_id):
    if not line_user_id:
        return None
    return _select_one(
        line_friendships,
        line_friendships.c.line_user_id == line_user_id,
    )


def can_receive_line_notifications(app_user_id):
    if not app_user_id:
        return False
    if app_user_id.startswith("anon_"):
        return bool(get_notification_line_user_id(app_user_id))
    if not app_user_id.startswith("U"):
        return True

    friendship = get_line_friendship(app_user_id)
    return bool(friendship and friendship.get("is_friend"))


def migrate_guest_identity(guest_user_id, line_user_id):
    """Move data owned by a legacy guest session to a verified LINE user ID."""
    if (
        not guest_user_id
        or not guest_user_id.startswith("anon_")
        or not line_user_id
        or guest_user_id == line_user_id
    ):
        return False

    now = _now()
    migrated = False
    with _engine().begin() as conn:
        source_user = _row_to_dict(
            conn.execute(
                select(users).where(users.c.line_user_id == guest_user_id)
            ).first()
        )
        target_user = _row_to_dict(
            conn.execute(
                select(users).where(users.c.line_user_id == line_user_id)
            ).first()
        )

        if source_user and target_user:
            merged_user = {
                field: target_user.get(field) or source_user.get(field) or ""
                for field in (
                    "display_name",
                    "business_name",
                    "user_category",
                    "area",
                    "address",
                    "transport_info",
                )
            }
            merged_user.update(
                user_id=line_user_id,
                userid=line_user_id,
                updated_at=now,
            )
            conn.execute(
                update(users)
                .where(users.c.line_user_id == line_user_id)
                .values(**merged_user)
            )
            conn.execute(delete(users).where(users.c.line_user_id == guest_user_id))
            migrated = True
        elif source_user:
            conn.execute(
                update(users)
                .where(users.c.line_user_id == guest_user_id)
                .values(
                    line_user_id=line_user_id,
                    user_id=line_user_id,
                    userid=line_user_id,
                    updated_at=now,
                )
            )
            migrated = True

        source_card = _row_to_dict(
            conn.execute(
                select(contact_cards).where(
                    or_(
                        contact_cards.c.line_user_id == guest_user_id,
                        contact_cards.c.user_id == guest_user_id,
                    )
                )
            ).first()
        )
        target_card = _row_to_dict(
            conn.execute(
                select(contact_cards).where(
                    or_(
                        contact_cards.c.line_user_id == line_user_id,
                        contact_cards.c.user_id == line_user_id,
                    )
                )
            ).first()
        )
        if source_card and target_card:
            merged_card = {
                field: target_card.get(field) or source_card.get(field) or ""
                for field in (
                    "display_name",
                    "contact_method",
                    "contact_value",
                    "available_time",
                    "message",
                    "is_active",
                )
            }
            merged_card.update(
                user_id=line_user_id,
                line_user_id=line_user_id,
                updated_at=now,
            )
            conn.execute(
                update(contact_cards)
                .where(
                    contact_cards.c.contact_card_id
                    == target_card["contact_card_id"]
                )
                .values(**merged_card)
            )
            conn.execute(
                delete(contact_cards).where(
                    contact_cards.c.contact_card_id
                    == source_card["contact_card_id"]
                )
            )
            migrated = True
        elif source_card:
            conn.execute(
                update(contact_cards)
                .where(
                    contact_cards.c.contact_card_id
                    == source_card["contact_card_id"]
                )
                .values(
                    user_id=line_user_id,
                    line_user_id=line_user_id,
                    updated_at=now,
                )
            )
            migrated = True

        ownership_updates = (
            (materials, materials.c.line_user_id),
            (demolition_properties, demolition_properties.c.line_user_id),
            (matching_history, matching_history.c.provider_user_id),
            (matching_history, matching_history.c.requester_user_id),
            (contact_share_logs, contact_share_logs.c.from_user_id),
            (contact_share_logs, contact_share_logs.c.to_user_id),
        )
        for table, column in ownership_updates:
            result = conn.execute(
                update(table)
                .where(column == guest_user_id)
                .values({column.name: line_user_id})
            )
            migrated = migrated or result.rowcount > 0

        conn.execute(
            delete(line_notification_links).where(
                line_notification_links.c.app_user_id == guest_user_id
            )
        )
        conn.execute(
            delete(line_notification_link_codes).where(
                line_notification_link_codes.c.app_user_id == guest_user_id
            )
        )

    return migrated


def append_material(data):
    material_id = f"mat_{uuid4().hex[:10]}"
    line_user_id = _normalize_user_id(data)
    values = _record_values(
        materials,
        data,
        {
            "material_id": material_id,
            "line_user_id": line_user_id,
            "post_type": POST_TYPE_OFFER,
            "status": POST_STATUS_ACTIVE,
            "expires_at": _expires_after(),
            "created_at": _now(),
        },
    )
    values["material_id"] = material_id
    values["line_user_id"] = line_user_id

    with _engine().begin() as conn:
        conn.execute(materials.insert().values(**values))
    return material_id


def upsert_material_record(record):
    defaults = {
        "post_type": POST_TYPE_OFFER,
        "status": MATERIAL_ACTIVE_STATUS,
        "expires_at": "",
        "created_at": _now(),
    }
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


def get_demolition_properties_by_line_user_id(line_user_id, include_all=False):
    stmt = (
        select(demolition_properties)
        .where(demolition_properties.c.line_user_id == line_user_id)
        .order_by(demolition_properties.c.created_at)
    )
    if not include_all:
        stmt = stmt.where(demolition_properties.c.status != DELETED_STATUS)
    return [_decorate_demolition_property_record(record) for record in _select_many(stmt)]


def _active_material_conditions():
    return (
        func.trim(materials.c.status).not_in((DELETED_STATUS, POST_STATUS_CLOSED, POST_STATUS_EXPIRED, "交渉中", "引取済み", "廃棄予定")),
        or_(func.trim(materials.c.expires_at) == "", func.trim(materials.c.expires_at) >= _now()),
    )


def get_public_listing_page(display_filter, material_type, page, page_size=24, area="all", query=""):
    """Page the combined feed in SQL before loading full records."""
    offer_type = func.lower(func.trim(materials.c.post_type))
    material_query = select(materials.c.material_id.label("id"), literal("material").label("kind"), materials.c.created_at).where(*_active_material_conditions())
    if display_filter == "demolitions":
        material_query = material_query.where(false())
    elif display_filter == POST_TYPE_REQUEST:
        material_query = material_query.where(offer_type == POST_TYPE_REQUEST)
    elif display_filter == POST_TYPE_OFFER:
        material_query = material_query.where(offer_type != POST_TYPE_REQUEST)
    if material_type != "all":
        material_query = material_query.where(materials.c.material_type == material_type)
    demolition_query = select(demolition_properties.c.property_id.label("id"), literal("demolition").label("kind"), demolition_properties.c.created_at).where(demolition_properties.c.status == DEMOLITION_ACTIVE_STATUS)
    if area != "all":
        material_query = material_query.where(materials.c.location.contains(area, autoescape=True))
        demolition_query = demolition_query.where(demolition_properties.c.location.contains(area, autoescape=True))
    if query:
        material_query = material_query.where(or_(materials.c.title.icontains(query, autoescape=True), materials.c.description.icontains(query, autoescape=True), materials.c.material_type.icontains(query, autoescape=True)))
        demolition_query = demolition_query.where(or_(demolition_properties.c.property_name.icontains(query, autoescape=True), demolition_properties.c.notes.icontains(query, autoescape=True)))
    if display_filter not in ("all", "demolitions") or material_type != "all":
        demolition_query = demolition_query.where(false())
    feed = union_all(material_query, demolition_query).subquery()
    refs = _select_many(select(feed).order_by(feed.c.created_at.desc(), feed.c.kind, feed.c.id).offset((page - 1) * page_size).limit(page_size + 1))
    visible = refs[:page_size]
    material_ids = [r["id"] for r in visible if r["kind"] == "material"]
    demolition_ids = [r["id"] for r in visible if r["kind"] == "demolition"]
    material_records = [_decorate_material_record(r) for r in _select_many(select(materials).where(materials.c.material_id.in_(material_ids), *_active_material_conditions()))]
    demolition_records = _select_many(select(demolition_properties).where(demolition_properties.c.property_id.in_(demolition_ids), demolition_properties.c.status == DEMOLITION_ACTIVE_STATUS))
    return material_records, demolition_records, visible, len(refs) > page_size


def get_materials(include_all=False, post_type=""):
    stmt = select(materials).order_by(materials.c.created_at)
    if not include_all:
        stmt = stmt.where(*_active_material_conditions())
    records = [
        _decorate_material_record(record)
        for record in _select_many(stmt)
    ]
    if post_type in (POST_TYPE_OFFER, POST_TYPE_REQUEST):
        records = [record for record in records if record.get("post_type") == post_type]
    if not include_all:
        records = [
            record
            for record in records
            if record.get("effective_status") == POST_STATUS_ACTIVE
        ]
    return records


def get_material_by_id(material_id):
    return _decorate_material_record(
        _select_one(materials, materials.c.material_id == material_id)
    )


def get_materials_by_line_user_id(line_user_id, include_all=False):
    stmt = select(materials).where(materials.c.line_user_id == line_user_id).order_by(materials.c.created_at)
    records = [_decorate_material_record(record) for record in _select_many(stmt)]
    if not include_all:
        records = [record for record in records if record.get("effective_status") != "deleted"]
    return records


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
        if url and url not in seen and _is_allowed_image_url(url):
            urls.append(url)
            seen.add(url)
    return urls


def _is_allowed_image_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    return (parsed.hostname or "").lower() == "res.cloudinary.com"


def _decorate_material_record(record):
    if not record:
        return record

    record["post_type"] = _effective_post_type(record)
    record["effective_status"] = _effective_post_status(record)
    record["status_label"] = {
        POST_STATUS_ACTIVE: "受付中",
        POST_STATUS_CLOSED: "終了",
        POST_STATUS_EXPIRED: "掲載期限切れ",
        "deleted": "削除済み",
    }.get(record["effective_status"], record.get("status", ""))
    image_urls = _collect_image_urls(record, "image_url", "image_urls")
    record["image_urls"] = image_urls
    record["image_url"] = image_urls[0] if image_urls else record.get("image_url", "")
    return record


def _decorate_demolition_property_record(record):
    if not record:
        return record

    image_urls = _collect_image_urls(
        record,
        "building_photo_url",
        "building_photo_urls",
    )
    record["building_photo_urls"] = image_urls
    record["building_photo_url"] = (
        image_urls[0] if image_urls else record.get("building_photo_url", "")
    )
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

    record["entry_owner_id"] = entry.get("line_user_id", "") if entry else ""
    record["entry_status"] = entry.get("effective_status", entry.get("status", "")) if entry else "deleted"
    return record


def append_matching_history(data, match_type="material", prevent_duplicate=False):
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
        if prevent_duplicate:
            # A write locks the parent row on PostgreSQL and serializes writes
            # on SQLite. Recheck availability and duplicates under this lock.
            parent = demolition_properties if match_type == "viewing" else materials
            key = "property_id" if match_type == "viewing" else "material_id"
            parent_id = values[key]
            result = conn.execute(update(parent).where(parent.c[key] == parent_id)
                                  .values(status=parent.c.status))
            if not result.rowcount:
                return None
            record = _row_to_dict(conn.execute(select(parent).where(parent.c[key] == parent_id)).first())
            if (match_type == "viewing" and record["status"] != DEMOLITION_ACTIVE_STATUS
                    or match_type != "viewing" and _effective_post_status(record) != POST_STATUS_ACTIVE):
                return None
            duplicate = conn.execute(select(matching_history.c.match_id).where(
                matching_history.c.match_type == match_type,
                matching_history.c[key] == parent_id,
                matching_history.c.provider_user_id == values["provider_user_id"],
                matching_history.c.requester_user_id == values["requester_user_id"],
                matching_history.c.created_at >= (datetime.now() - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S"),
            ).limit(1)).first()
            if duplicate:
                return None
        conn.execute(matching_history.insert().values(**values))
        if prevent_duplicate:
            actor_id = values["provider_user_id"] if match_type == "request" else values["requester_user_id"]
            actor = _row_to_dict(conn.execute(select(users).where(users.c.line_user_id == actor_id)).first()) or {}
            action_label = {"material": "欲しい通知", "request": "提供の申し出", "viewing": "見学希望"}[match_type]
            enqueue_notification(conn, match_id, record["line_user_id"],
                                 "\n".join([
                                     f"「{record.get('title') or record.get('property_name') or parent_id}」に{action_label}が届きました。",
                                     f"名前・事業者名: {actor.get('business_name') or actor.get('display_name') or '未登録'}",
                                     f"エリア: {actor.get('area') or '未登録'}",
                                     f"メッセージ: {values['message'] or 'なし'}",
                                     "連絡先を共有する場合は、マイページのマッチング履歴から共有してください。",
                                 ]), match_id=match_id)
    return match_id


def enqueue_notification(conn, notification_id, app_user_id, message, match_id=None):
    import time
    from app.services.liff_service import build_liff_url
    now = int(time.time())
    target = app_user_id
    if app_user_id.startswith("anon_"):
        target = conn.execute(select(line_notification_links.c.line_user_id).where(line_notification_links.c.app_user_id == app_user_id)).scalar() or ""
    path = '/users/me?' + urlencode({"tab": "matches", "refresh": "1", **({"match": match_id} if match_id else {})})
    conn.execute(notification_outbox.insert().values(
        notification_id=notification_id, app_user_id=app_user_id, target_user_id=target,
        message=f"【えらぶ材すぽっと】\n{message}\n問い合わせの履歴をご確認ください。\n{build_liff_url(path)}",
        retry_key=str(uuid4()), status="pending", attempts=0,
        created_at=now, next_attempt_at=now,
    ))


def has_recent_matching_request(match_type, entry_id, requester_user_id, seconds=30):
    if match_type not in ("material", "request", "viewing") or not entry_id or not requester_user_id:
        return False

    entry_column = (
        matching_history.c.property_id
        if match_type == "viewing"
        else matching_history.c.material_id
    )
    actor_column = (
        matching_history.c.provider_user_id
        if match_type == "request"
        else matching_history.c.requester_user_id
    )
    cutoff = (datetime.now() - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
    stmt = select(matching_history.c.match_id).where(
        matching_history.c.match_type == match_type,
        entry_column == entry_id,
        actor_column == requester_user_id,
        matching_history.c.created_at >= cutoff,
    ).limit(1)
    with _engine().connect() as conn:
        return conn.execute(stmt).first() is not None


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
    # Only expose the snapshot explicitly sent to this viewer, never a live profile card.
    received = _select_many(select(contact_share_logs).where(
        contact_share_logs.c.to_user_id == line_user_id,
        contact_share_logs.c.share_status == "shared",
    ).order_by(contact_share_logs.c.shared_at.desc(), contact_share_logs.c.created_at.desc()))
    cards = {}
    for share in received:
        cards.setdefault((share["match_type"], share["match_id"], share["from_user_id"]), {
            key: share.get("shared_" + key, "")
            for key in ("display_name", "contact_method", "contact_value", "available_time", "message")
        })
    for record in history:
        _decorate_match_record(record)
        other_id = record["requester_user_id"] if record["provider_user_id"] == line_user_id else record["provider_user_id"]
        other = get_user_by_line_user_id(other_id) or {}
        record["other_display_name"] = other.get("business_name") or other.get("display_name") or "相手"
        record["received_contact"] = cards.get((record["match_type"], record["match_id"], other_id))
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


def update_matching_status(match_id, match_type, user_id, status, expected_status=None, completion_action="keep", expected_updated_at=None):
    if match_type not in ("material", "request", "viewing"):
        return None

    with _engine().begin() as conn:
        if status not in ("未対応", "連絡・調整中", "成立", "辞退") or completion_action not in ("keep", "close"):
            return None
        match = _row_to_dict(conn.execute(select(matching_history).where(
            matching_history.c.match_id == match_id, matching_history.c.match_type == match_type
        )).first())
        if not match or user_id not in (match["provider_user_id"], match["requester_user_id"]):
            return None
        if expected_status is not None and match["status"] != expected_status:
            return None
        if expected_updated_at is not None and match["updated_at"] != expected_updated_at:
            return None
        parent = demolition_properties if match_type == "viewing" else materials
        key = "property_id" if match_type == "viewing" else "material_id"
        if completion_action == "close":
            if status != "成立" or match_type == "viewing":
                return None
            post = conn.execute(select(parent.c.line_user_id, parent.c.status).where(parent.c[key] == match[key]).with_for_update()).first()
            if not post or post.line_user_id != user_id or post.status == DELETED_STATUS:
                return None
        result = conn.execute(
            update(matching_history)
            .where(
                matching_history.c.match_id == match_id,
                matching_history.c.match_type == match_type,
                matching_history.c.status == match["status"],
                matching_history.c.updated_at == match["updated_at"],
                or_(
                    matching_history.c.provider_user_id == user_id,
                    matching_history.c.requester_user_id == user_id,
                ),
            )
            .values(status=status, updated_at=datetime.now().isoformat(sep=" ", timespec="microseconds"))
        )
        if result.rowcount <= 0:
            return None
        if completion_action == "close":
            conn.execute(update(materials).where(materials.c.material_id == match["material_id"],
                materials.c.line_user_id == user_id, materials.c.status != DELETED_STATUS
            ).values(status=POST_STATUS_CLOSED))
        record_operation(conn, "match_status", match_id, user_id,
            json.dumps({"from": match["status"], "to": status, "listing": completion_action}, ensure_ascii=False))
        record = _row_to_dict(conn.execute(select(matching_history).where(matching_history.c.match_id == match_id)).first())
        target = record["requester_user_id"] if record["provider_user_id"] == user_id else record["provider_user_id"]
        notification_id = str(uuid4())
        parent = demolition_properties if match_type == "viewing" else materials
        key = "property_id" if match_type == "viewing" else "material_id"
        title_column = parent.c.property_name if match_type == "viewing" else parent.c.title
        title = conn.execute(select(title_column).where(parent.c[key] == record[key])).scalar() or record[key]
        status_label = {"成立": "見学完了" if match_type == "viewing" else "受け渡し完了", "辞退": "今回は見送り", "連絡・調整中": "連絡先の共有・相談中", "未対応": "問い合わせ受付"}.get(status, status)
        enqueue_notification(conn, notification_id, target, f"「{title}」について、相手から「{status_label}」の連絡がありました。", match_id=match_id)
    record = _decorate_match_record(record)
    record["notification_id"] = notification_id
    return record


def get_contact_card_by_user(line_user_id):
    stmt = select(contact_cards).where(
        or_(contact_cards.c.line_user_id == line_user_id, contact_cards.c.user_id == line_user_id)
    )
    records = _select_many(stmt)
    return records[0] if records else None


def get_me_profile_by_line_user_id(line_user_id):
    """Load the profile and contact card in one database round trip."""
    user_record = (
        select(users)
        .where(
            or_(
                users.c.line_user_id == line_user_id,
                users.c.user_id == line_user_id,
                users.c.userid == line_user_id,
            )
        )
        .limit(1)
        .cte("me_user")
    )
    contact_record = (
        select(contact_cards)
        .where(
            or_(
                contact_cards.c.line_user_id == line_user_id,
                contact_cards.c.user_id == line_user_id,
            )
        )
        .limit(1)
        .cte("me_contact")
    )
    anchor = select(literal(1).label("value")).cte("me_anchor")
    stmt = (
        select(
            *(
                user_record.c[column.name].label(f"user__{column.name}")
                for column in users.columns
            ),
            *(
                contact_record.c[column.name].label(f"contact__{column.name}")
                for column in contact_cards.columns
            ),
        )
        .select_from(
            anchor.outerjoin(user_record, true()).outerjoin(contact_record, true())
        )
    )

    with _engine().connect() as conn:
        row = conn.execute(stmt).first()

    values = _row_to_dict(row) or {}
    user = None
    if values.get("user__line_user_id") is not None:
        user = {
            column.name: values.get(f"user__{column.name}")
            for column in users.columns
        }

    contact_card = None
    if values.get("contact__contact_card_id") is not None:
        contact_card = {
            column.name: values.get(f"contact__{column.name}")
            for column in contact_cards.columns
        }

    return user, contact_card


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


def contact_card_version(card):
    return hashlib.sha256(json.dumps(card, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_contact_share(match_id, match_type, from_user_id, expected_version=None):
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
    if expected_version is not None and expected_version != contact_card_version(card):
        return None, "contact_card_changed"
    if str(card.get("is_active", "TRUE")).upper() in ("FALSE", "0", "NO", "OFF"):
        return None, "contact_card_inactive"

    shared_at = _now()
    share_id = f"share_{uuid4().hex}"
    share_data = {
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
    share_data.update(contact_share_id=share_id, consent_version="contact_share_v1", created_at=shared_at, updated_at=shared_at)
    role = "provider" if match["provider_user_id"] == from_user_id else "requester"
    with _engine().begin() as conn:
        conn.execute(contact_share_logs.insert().values(**_record_values(contact_share_logs, share_data)))
        conn.execute(update(matching_history).where(
            matching_history.c.match_id == match_id,
            matching_history.c.match_type == match_type,
        ).values(**{f"{role}_contact_share_status": "shared", f"{role}_contact_shared_at": shared_at, "updated_at": shared_at}))
        conn.execute(update(matching_history).where(
            matching_history.c.match_id == match_id,
            matching_history.c.match_type == match_type,
            matching_history.c.status == "未対応",
        ).values(status="連絡・調整中"))
        enqueue_notification(conn, share_id, to_user_id, "\n".join([
            "連絡先カードが共有されました。",
            f"お名前: {card.get('display_name', '')}",
            f"連絡方法: {card.get('contact_method', '')}",
            f"連絡先: {card.get('contact_value', '')}",
            f"連絡可能時間: {card.get('available_time', '')}",
            card.get("message", ""),
        ]), match_id=match_id)
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
        "business_name": data.get("business_name", existing.get("business_name", "") if existing else ""),
        "user_category": data.get("user_category", existing.get("user_category", "") if existing else ""),
        "area": data.get("area", existing.get("area", "") if existing else ""),
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
    values = {"status": status}
    if status == POST_STATUS_ACTIVE:
        values["expires_at"] = _expires_after()
    with _engine().begin() as conn:
        result = conn.execute(
            update(materials)
            .where(materials.c.material_id == material_id)
            .values(**values)
        )
    return result.rowcount > 0


def delete_material(material_id):
    return update_material_status(material_id, DELETED_STATUS)


def close_material(material_id, line_user_id):
    with _engine().begin() as conn:
        result = conn.execute(
            update(materials)
            .where(
                materials.c.material_id == material_id,
                materials.c.line_user_id == line_user_id,
                materials.c.status != DELETED_STATUS,
            )
            .values(status=POST_STATUS_CLOSED)
        )
    return result.rowcount > 0


def renew_material(material_id, line_user_id, days=POST_TTL_DAYS):
    with _engine().begin() as conn:
        result = conn.execute(
            update(materials)
            .where(
                materials.c.material_id == material_id,
                materials.c.line_user_id == line_user_id,
                materials.c.status != DELETED_STATUS,
            )
            .values(status=POST_STATUS_ACTIVE, expires_at=_expires_after(days))
        )
    return result.rowcount > 0


def delete_demolition_property(property_id):
    with _engine().begin() as conn:
        result = conn.execute(
            update(demolition_properties)
            .where(demolition_properties.c.property_id == property_id)
            .values(status=DELETED_STATUS)
        )
    return result.rowcount > 0


def update_material(material_id, line_user_id, data):
    existing = get_material_by_id(material_id)
    if not existing or existing.get("line_user_id") != line_user_id:
        return None

    allowed_fields = (
        "title",
        "post_type",
        "material_type",
        "description",
        "size",
        "quantity",
        "quantity_level",
        "condition",
        "location",
        "usage_purpose",
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


def update_demolition_property(property_id, line_user_id, data):
    existing = get_demolition_property_by_id(property_id)
    if not existing or existing.get("line_user_id") != line_user_id:
        return None

    allowed_fields = (
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
    )
    values = {
        field: data.get(field, existing.get(field, "")) for field in allowed_fields
    }

    with _engine().begin() as conn:
        result = conn.execute(
            update(demolition_properties)
            .where(demolition_properties.c.property_id == property_id)
            .values(**values)
        )

    if result.rowcount <= 0:
        return None

    updated = get_demolition_property_by_id(property_id)
    return _decorate_demolition_property_record(updated)
