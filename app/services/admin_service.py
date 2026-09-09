"""Bounded database queries for operational visibility and moderation."""
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, or_, update
from app.services import db_service as db


def dashboard(kind, query, page, status=""):
    table = db.demolition_properties if kind == "demolition" else db.materials
    key = "property_id" if kind == "demolition" else "material_id"
    title = "property_name" if kind == "demolition" else "title"
    stmt = select(table)
    if status:
        if kind == "demolition":
            stmt = stmt.where(table.c.status == status)
        elif status == "active":
            stmt = stmt.where(*db._active_material_conditions())
        elif status == "expired":
            stmt = stmt.where(table.c.status.not_in([db.DELETED_STATUS, 'closed', '交渉中', '引取済み', '廃棄予定']),
                or_(table.c.status == 'expired', (table.c.expires_at != '') & (table.c.expires_at < db._now())))
        elif status == "closed":
            stmt = stmt.where(table.c.status.in_(['closed', '交渉中', '引取済み', '廃棄予定']))
        else:
            stmt = stmt.where(table.c.status == status)
    if query:
        stmt = stmt.where(or_(table.c[title].icontains(query, autoescape=True),
            table.c.location.icontains(query, autoescape=True), table.c[key].icontains(query, autoescape=True)))
    with db._engine().connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(stmt.order_by(table.c.created_at.desc(), table.c[key])
            .offset((page - 1) * 25).limit(26))]
        counts = dict(conn.execute(select(db.notification_outbox.c.status, func.count()).group_by(db.notification_outbox.c.status)).all())
        oldest = conn.execute(select(func.min(db.notification_outbox.c.created_at)).where(db.notification_outbox.c.status == "pending")).scalar()
        heartbeat = conn.execute(select(db.operations.c.created_at).where(db.operations.c.kind == "notification_job")
            .order_by(db.operations.c.created_at.desc()).limit(1)).scalar()
        notifications = [dict(row._mapping) for row in conn.execute(select(
            db.notification_outbox.c.notification_id, db.notification_outbox.c.status,
            db.notification_outbox.c.attempts, db.notification_outbox.c.created_at
        ).where(db.notification_outbox.c.status != "sent").order_by(db.notification_outbox.c.created_at).limit(25))]
        for notification in notifications:
            notification["reason"] = conn.execute(select(db.operations.c.detail).where(
                db.operations.c.kind == "notification_error", db.operations.c.subject_id == notification["notification_id"]
            ).order_by(db.operations.c.created_at.desc()).limit(1)).scalar() or "初回送信待ち"
        events = [dict(row._mapping) for row in conn.execute(select(db.operations)
            .where(db.operations.c.kind.in_(["admin_status", "match_status", "report_resolution"]))
            .order_by(db.operations.c.created_at.desc()).limit(25))]
        resolved = select(db.operations.c.subject_id).where(db.operations.c.kind == "report_resolution")
        reports = [dict(row._mapping) for row in conn.execute(select(db.operations).where(
            db.operations.c.kind == "report", db.operations.c.event_id.not_in(resolved)
        ).order_by(db.operations.c.created_at).limit(25))]
        uploads = conn.execute(select(func.count()).select_from(db.image_upload_jobs).where(
            db.image_upload_jobs.c.created_at < int(time.time()) - 86400)).scalar()
    entries = []
    for row in rows[:25]:
        entries.append({"id": row[key], "title": row[title], "location": row["location"],
            "status": row["status"] if kind == "demolition" else db._effective_post_status(row)})
    now = int(time.time())
    def format_time(value):
        return datetime.fromtimestamp(value, timezone(timedelta(hours=9))).strftime('%Y/%m/%d %H:%M JST')
    labels = {"admin_status": "掲載状態の変更", "match_status": "マッチング状態の変更", "report_resolution": "通報の確認"}
    for event in events:
        event['label'] = labels[event['kind']]
        event['time_label'] = format_time(event['created_at'])
    for report in reports:
        report['post_kind'], _, report['post_id'] = report['subject_id'].partition(':')
    return dict(entries=entries, has_next=len(rows) > 25, counts=counts,
        oldest_minutes=(now - oldest) // 60 if oldest else 0,
        heartbeat=format_time(heartbeat) if heartbeat else "未実行",
        job_stale=not heartbeat or now - heartbeat > 300, notifications=notifications,
        events=events, reports=reports, stale_uploads=uploads)


def change_post_status(kind, entry_id, status, actor):
    table = db.demolition_properties if kind == "demolition" else db.materials
    key = "property_id" if kind == "demolition" else "material_id"
    allowed = (db.DEMOLITION_ACTIVE_STATUS, "受付終了", db.DELETED_STATUS) if kind == "demolition" else ("active", "closed", db.DELETED_STATUS)
    if status not in allowed:
        return False
    with db._engine().begin() as conn:
        previous = conn.execute(select(table.c.status).where(table.c[key] == entry_id)).scalar()
        if previous is None:
            return False
        values = {"status": status}
        if kind != "demolition" and status == "active":
            values["expires_at"] = db._expires_after()
        result = conn.execute(update(table).where(table.c[key] == entry_id).values(**values))
        if result.rowcount:
            db.record_operation(conn, "admin_status", entry_id, actor, f"{previous} → {status}")
        return bool(result.rowcount)
