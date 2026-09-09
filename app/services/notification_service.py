"""Durable delivery with a lease and a stable LINE retry key."""
import time

from flask import current_app
from sqlalchemy import select, update

from app.services.db_service import _engine, notification_outbox, record_operation
from app.services.line_service import send_line_message


def deliver_notification(notification_id, sender=None):
    sender = sender or send_line_message
    now = int(time.time())
    with _engine().begin() as conn:
        claimed = conn.execute(update(notification_outbox).where(
            notification_outbox.c.notification_id == notification_id,
            notification_outbox.c.status == "pending",
            notification_outbox.c.next_attempt_at <= now,
        ).values(next_attempt_at=now + 120, attempts=notification_outbox.c.attempts + 1))
        if not claimed.rowcount:
            return False
        row = dict(conn.execute(select(notification_outbox).where(
            notification_outbox.c.notification_id == notification_id)).first()._mapping)
    # Stop before LINE's retry-key validity expires; an operator can inspect
    # exhausted jobs without risking an automatic duplicate delivery.
    sent = False
    exhausted = now - row["created_at"] >= 23 * 3600
    reason = "再送期限（23時間）を超過" if exhausted else "送信先未設定または通知を受付できませんでした"
    if not exhausted:
        try:
            target = row["target_user_id"]
            if target:
                sent = bool(sender(target, row["message"], retry_key=row["retry_key"]))
        except Exception as exc:
            status = getattr(exc, "status", None)
            reason = f"LINE API HTTP {status}" if isinstance(status, int) else "LINE APIへの接続または送信に失敗"
            if isinstance(status, int) and 400 <= status < 500 and status != 429:
                exhausted = True
            current_app.logger.exception("[NOTIFICATION] delivery failed id=%s", notification_id)
    with _engine().begin() as conn:
        result = conn.execute(update(notification_outbox).where(
            notification_outbox.c.notification_id == notification_id,
            notification_outbox.c.attempts == row["attempts"],
        ).values(status="sent" if sent else "failed" if exhausted else "pending",
                 next_attempt_at=now + min(3600, 30 * 2 ** min(row["attempts"], 7))))
        if result.rowcount and not sent:
            record_operation(conn, "notification_error", notification_id, detail=reason)
    return sent


def drain_notifications(limit=100):
    with _engine().connect() as conn:
        ids = conn.execute(select(notification_outbox.c.notification_id).where(
            notification_outbox.c.status == "pending",
            notification_outbox.c.next_attempt_at <= int(time.time()),
        ).order_by(notification_outbox.c.next_attempt_at).limit(limit)).scalars().all()
    delivered = sum(deliver_notification(notification_id) for notification_id in ids)
    with _engine().begin() as conn:
        record_operation(conn, "notification_job", detail=f"処理 {len(ids)}件 / 受付 {delivered}件")
    return delivered
