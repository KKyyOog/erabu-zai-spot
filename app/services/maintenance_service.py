"""Bounded retention for disposable operational data only."""
import time

from flask import current_app
from sqlalchemy import delete, exists, select, or_
from app.services import db_service as db


def clean_operational_data(limit=1000):
    """Keep pending/failed notifications, reports, audit events and heartbeat.

    Each category removes at most limit rows per run to bound lock duration.
    Retention <= 0 disables cleanup for that category.
    """
    now = int(time.time())
    counts = {}
    with db._engine().begin() as conn:
        def remove(name, table, key, *conditions):
            ids = conn.execute(select(key).where(*conditions).limit(limit)).scalars().all()
            if ids:
                conn.execute(delete(table).where(key.in_(ids), *conditions))
            counts[name] = len(ids)

        days = current_app.config["SENT_NOTIFICATION_RETENTION_DAYS"]
        if days > 0:
            cutoff = now - days * 86400
            remove("sent_notifications", db.notification_outbox, db.notification_outbox.c.notification_id,
                db.notification_outbox.c.status == "sent",
                db.notification_outbox.c.created_at < cutoff,
                db.notification_outbox.c.next_attempt_at < cutoff)
        days = current_app.config["OPERATION_LOG_RETENTION_DAYS"]
        if days > 0:
            # Preserve error explanations while any related notification remains.
            related = exists(select(db.notification_outbox.c.notification_id).where(
                db.notification_outbox.c.notification_id == db.operations.c.subject_id))
            remove("operation_logs", db.operations, db.operations.c.event_id,
                db.operations.c.created_at < now - days * 86400,
                db.operations.c.event_id != "notification_job_latest",
                or_(db.operations.c.kind == "notification_job",
                    (db.operations.c.kind == "notification_error") & ~related))
        remove("expired_rate_limits", db.request_buckets, db.request_buckets.c.bucket_key,
            db.request_buckets.c.expires_at <= now)
    return counts
