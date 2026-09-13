import time
import unittest
from unittest.mock import patch

from sqlalchemy import select
import test_workflows as fixtures
from app.services import db_service as db
from app.services.admin_service import dashboard
from app.services.maintenance_service import clean_operational_data
from app.services.notification_service import drain_notifications


class MaintenanceTestCase(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.WorkflowTestCase.setUpClass())
    setUp = fixtures.WorkflowTestCase.setUp
    tearDown = fixtures.WorkflowTestCase.tearDown

    def add_notification(self, conn, key, status, timestamp, next_attempt=None):
        conn.execute(db.notification_outbox.insert().values(notification_id=key,
            app_user_id="user", target_user_id="user", message="private message",
            retry_key=key, status=status, attempts=1, created_at=timestamp,
            next_attempt_at=timestamp if next_attempt is None else next_attempt))

    def test_empty_runs_update_one_heartbeat_and_warning_follows_threshold(self):
        now = int(time.time())
        with self.app.app_context():
            with patch("app.services.notification_service.time.time", return_value=now - 600):
                drain_notifications()
            self.assertFalse(dashboard("material", "", 1)["job_stale"])
            self.app.config["NOTIFICATION_JOB_STALE_SECONDS"] = 300
            self.assertTrue(dashboard("material", "", 1)["job_stale"])
            self.assertEqual(dashboard("material", "", 1)["job_stale_minutes"], 5)
            with patch("app.services.notification_service.time.time", return_value=now):
                drain_notifications()
            self.assertFalse(dashboard("material", "", 1)["job_stale"])
            with db._engine().connect() as conn:
                rows = conn.execute(select(db.operations)).all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]._mapping["created_at"], now)

    def test_cleanup_preserves_actionable_data_and_recent_delivery(self):
        now = int(time.time())
        old = now - 40 * 86400
        with self.app.app_context():
            with db._engine().begin() as conn:
                for key, status, stamp, attempt in (
                    ("old_sent", "sent", old, old),
                    ("pending", "pending", old, old),
                    ("failed", "failed", old, old),
                    ("recent", "sent", now, now),
                    ("recent_delivery", "sent", old, now),
                ):
                    self.add_notification(conn, key, status, stamp, attempt)
                for key, kind, subject in (
                    ("legacy", "notification_job", ""),
                    ("notification_job_latest", "notification_job", ""),
                    ("orphan", "notification_error", "missing"),
                    ("sent_error", "notification_error", "old_sent"),
                    ("failed_error", "notification_error", "failed"),
                    ("pending_error", "notification_error", "pending"),
                    ("report", "report", "material:123"),
                    ("resolution", "report_resolution", "report"),
                    ("audit", "admin_status", "123"),
                    ("match", "match_status", "123"),
                ):
                    conn.execute(db.operations.insert().values(event_id=key, kind=kind,
                        subject_id=subject, created_at=old))
                conn.execute(db.request_buckets.insert(), [
                    dict(bucket_key="expired", count=1, expires_at=old),
                    dict(bucket_key="active", count=1, expires_at=now + 600)])
            result = clean_operational_data()
            self.assertEqual(result, dict(sent_notifications=1, operation_logs=3, expired_rate_limits=1))
            with db._engine().connect() as conn:
                self.assertEqual(set(conn.execute(select(db.notification_outbox.c.notification_id)).scalars()),
                    {"pending", "failed", "recent", "recent_delivery"})
                self.assertEqual(set(conn.execute(select(db.operations.c.event_id)).scalars()),
                    {"notification_job_latest", "failed_error", "pending_error", "report", "resolution", "audit", "match"})
                self.assertEqual(conn.execute(select(db.request_buckets.c.bucket_key)).scalar(), "active")
            self.assertEqual(sum(clean_operational_data().values()), 0)

    def test_cleanup_is_bounded_and_retention_can_be_disabled(self):
        old = int(time.time()) - 40 * 86400
        with self.app.app_context():
            with db._engine().begin() as conn:
                for key in ("one", "two", "three"):
                    self.add_notification(conn, key, "sent", old)
            self.assertEqual(clean_operational_data(limit=2)["sent_notifications"], 2)
            self.app.config["SENT_NOTIFICATION_RETENTION_DAYS"] = 0
            self.app.config["OPERATION_LOG_RETENTION_DAYS"] = 0
            clean_operational_data()
            with db._engine().connect() as conn:
                self.assertEqual(len(conn.execute(select(db.notification_outbox)).all()), 1)

    def test_existing_daily_command_also_cleans_operational_data(self):
        with patch("app.routes.materials.clean_upload_jobs", return_value=0), patch(
            "app.services.maintenance_service.clean_operational_data", return_value={}) as cleanup:
            result = self.app.test_cli_runner().invoke(args=["clean-upload-jobs"])
        self.assertEqual(result.exit_code, 0, result.output)
        cleanup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
