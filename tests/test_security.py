import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, select, update

import test_workflows as fixtures
from app.services import db_service as db
from app.services.notification_service import deliver_notification
from app.services.rate_limit_service import allow_request


class SecurityTestCase(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.WorkflowTestCase.setUpClass())
    setUp = fixtures.WorkflowTestCase.setUp
    tearDown = fixtures.WorkflowTestCase.tearDown
    authenticate = fixtures.WorkflowTestCase.authenticate
    post_form = fixtures.WorkflowTestCase.post_form

    def test_temporary_verification_failure_preserves_session(self):
        from app.services.line_auth_service import LineAuthUnavailable
        self.app.config["LINE_LOGIN_ENABLED"] = True
        self.authenticate("owner")
        with self.client.session_transaction() as saved:
            authenticated_at = saved["line_authenticated_at"]
        with patch("app.routes.link.verify_id_token", side_effect=LineAuthUnavailable()):
            response = self.client.post("/link/liff", json={"userId": "owner", "idToken": "token"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "line_auth_unavailable")
        self.assertEqual(response.headers["Retry-After"], "10")
        with self.client.session_transaction() as saved:
            self.assertEqual(saved["line_user_id"], "owner")
            self.assertEqual(saved["line_authenticated_at"], authenticated_at)

    def test_temporary_verification_failure_in_shared_auth_is_503(self):
        from app.services.line_auth_service import LineAuthUnavailable
        self.authenticate("owner")
        with self.client.session_transaction() as saved:
            saved["line_authenticated_at"] = 1
        with patch("app.services.line_auth_service.verify_id_token", side_effect=LineAuthUnavailable()):
            response = self.client.post("/users/me/data", json={"userId": "owner", "idToken": "token"},
                                        headers={"X-CSRF-Token": self.csrf_token})
        self.assertEqual(response.status_code, 503)

    def test_diagnostic_batch_is_bounded_and_does_not_log_arbitrary_text(self):
        self.app.config["LIFF_DEBUG_LOGGING"] = True
        item = {"event": "auth.flow_started", "details": {
            "errorMessage": "private-token", "errorName": "private-token",
            "private-token": "private-token", "durationMs": "private-token",
            "userId": "private-token", "pathname": "/private-token"}}
        with self.assertLogs("app.routes.link", level="INFO") as logs:
            response = self.client.post("/link/liff-debug", json={"events": [item] * 10, "dropped": 3},
                                        headers={"User-Agent": "private-token", "Referer": "https://example.com/private-token"})
        self.assertEqual(response.status_code, 204)
        output = " ".join(logs.output)
        self.assertNotIn("private-token", output)
        self.assertIn("diagnostics.dropped", output)
        self.assertIn("count=3", output)
        self.assertEqual(self.client.post("/link/liff-debug", json={"events": [item] * 11}).status_code, 400)
        self.assertEqual(self.client.post("/link/liff-debug", json={"event": "private-token"}).status_code, 400)

    def test_login_rejects_malformed_fields_without_verification(self):
        self.app.config["LINE_LOGIN_ENABLED"] = True
        for payload in ([1], {"idToken": 123}, {"userId": [], "idToken": "token"}):
            with self.subTest(payload=payload), patch("app.routes.link.verify_id_token") as verify:
                response = self.client.post("/link/liff", json=payload)
                self.assertEqual(response.status_code, 400)
                verify.assert_not_called()

    def test_deleted_demolition_cannot_be_viewed_or_requested(self):
        with self.app.app_context():
            entry = db.append_demolition_property({"line_user_id": "owner", "location": "private location"})
            db.delete_demolition_property(entry)
        self.assertEqual(self.client.get(f"/materials/demolitions/{entry}").status_code, 404)
        self.authenticate("visitor")
        with patch("app.routes.materials._redirect_unavailable_notifications_to_user_page", return_value=None), patch("app.routes.materials.send_line_message") as send:
            response = self.post_form("/materials/demolitions/visit-interest", {"property_id": entry})
        self.assertEqual(response.status_code, 404)
        send.assert_not_called()
        with self.app.app_context():
            self.assertEqual(db.get_matching_history_by_user("visitor"), [])

    def test_expired_and_undated_sessions_cannot_change_data(self):
        with self.app.app_context():
            entry = db.append_material({"line_user_id": "owner"})
        for timestamp in (None, int(time.time()) - self.app.config["LINE_SESSION_SECONDS"] - 1):
            self.authenticate("owner")
            with self.client.session_transaction() as session:
                if timestamp is None:
                    session.pop("line_authenticated_at")
                else:
                    session["line_authenticated_at"] = timestamp
            self.post_form(f"/materials/{entry}/close", {"line_user_id": "owner"})
            with self.app.app_context():
                self.assertEqual(db.get_material_by_id(entry)["effective_status"], "active")
            self.assertFalse(self.client.get("/link/session").get_json()["ok"])

    def test_admin_requires_recent_authentication(self):
        self.app.config["ADMIN_LINE_USER_ID"] = "admin"
        self.authenticate("admin")
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        with self.client.session_transaction() as session:
            session["line_authenticated_at"] = int(time.time()) - 901
        self.assertEqual(self.client.get("/admin/").status_code, 401)
        self.assertEqual(self.post_form("/admin/materials/status", {"material_id": "id", "status": "closed"}).status_code, 403)

    def test_legacy_guest_migrates_after_opening_the_login_page(self):
        guest = "anon_legacy"
        self.authenticate(guest)
        with self.app.app_context():
            db.append_user({"line_user_id": guest, "display_name": "Guest"})
        self.app.config["LINE_LOGIN_ENABLED"] = True
        self.client.get("/")
        self.assertFalse(self.client.get("/link/session").get_json()["ok"])
        with patch("app.routes.link.verify_id_token", return_value={"sub": "verified"}):
            response = self.client.post("/link/liff", json={"userId": "verified", "idToken": "valid"})
        self.assertTrue(response.get_json()["migrated_guest_data"])
        with self.app.app_context():
            self.assertEqual(db.get_user_by_line_user_id("verified")["display_name"], "Guest")

    def test_expired_session_can_reauthenticate_with_verified_token(self):
        self.authenticate("owner")
        with self.client.session_transaction() as session:
            session["line_authenticated_at"] = 1
        with patch("app.services.line_auth_service.verify_id_token", return_value={"sub": "owner"}):
            response = self.client.post("/users/me/data", json={"userId": "owner", "idToken": "valid"}, headers={"X-CSRF-Token": self.csrf_token})
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertGreater(session["line_authenticated_at"], time.time() - 10)

    def test_parallel_requests_create_one_match_and_one_notification(self):
        with tempfile.TemporaryDirectory(dir=self.app.root_path) as folder:
            engine = create_engine("sqlite:///" + Path(folder, "concurrency.db").as_posix())
            original = self.app.extensions["database_engine"]
            self.app.extensions["database_engine"] = engine
            db.metadata.create_all(engine)
            try:
                with self.app.app_context():
                    entry = db.append_material({"line_user_id": "owner"})
                barrier = Barrier(2)
                def submit():
                    with self.app.app_context():
                        barrier.wait(timeout=5)
                        return db.append_matching_history({"material_id": entry, "provider_user_id": "owner", "requester_user_id": "visitor"}, prevent_duplicate=True)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: submit(), range(2)))
                self.assertEqual(sum(result is not None for result in results), 1)
                with engine.connect() as conn:
                    self.assertEqual(len(conn.execute(select(db.matching_history)).all()), 1)
                    self.assertEqual(len(conn.execute(select(db.notification_outbox)).all()), 1)
            finally:
                self.app.extensions["database_engine"] = original
                engine.dispose()

    def test_notification_insert_failure_rolls_back_match(self):
        with self.app.app_context():
            entry = db.append_material({"line_user_id": "owner"})
            with patch.object(db, "enqueue_notification", side_effect=RuntimeError("database failure")):
                with self.assertRaises(RuntimeError):
                    db.append_matching_history({"material_id": entry, "provider_user_id": "owner", "requester_user_id": "visitor"}, prevent_duplicate=True)
            self.assertEqual(db.get_matching_history_by_user("visitor"), [])

    def test_failed_notification_retries_with_same_payload_and_key(self):
        with self.app.app_context():
            with db._engine().begin() as conn:
                db.enqueue_notification(conn, "job", "owner", "hello")
            sender = Mock(side_effect=[TimeoutError(), True])
            self.assertFalse(deliver_notification("job", sender))
            self.assertFalse(deliver_notification("job", sender))  # Backoff.
            with db._engine().begin() as conn:
                conn.execute(update(db.notification_outbox).values(next_attempt_at=0))
            self.assertTrue(deliver_notification("job", sender))
            self.assertEqual(sender.call_args_list[0], sender.call_args_list[1])
            self.assertFalse(deliver_notification("job", sender))  # Already sent.
            self.assertEqual(sender.call_count, 2)

    def test_rate_limit_is_shared_and_expires(self):
        with self.app.app_context(), patch("app.services.rate_limit_service.time.time", return_value=120):
            self.assertTrue(allow_request("test", "user", 2, 60))
            self.assertTrue(allow_request("test", "user", 2, 60))
            self.assertFalse(allow_request("test", "user", 2, 60))
            self.assertTrue(allow_request("test", "other", 2, 60))
        with self.app.app_context(), patch("app.services.rate_limit_service.time.time", return_value=180):
            self.assertTrue(allow_request("test", "user", 2, 60))

    def test_notification_retry_stops_before_retry_key_expires(self):
        with self.app.app_context():
            with db._engine().begin() as conn:
                db.enqueue_notification(conn, "old-job", "owner", "hello")
                conn.execute(update(db.notification_outbox).values(created_at=int(time.time()) - 24 * 3600))
            sender = Mock()
            self.assertFalse(deliver_notification("old-job", sender))
            sender.assert_not_called()
            with db._engine().connect() as conn:
                self.assertEqual(conn.execute(select(db.notification_outbox.c.status)).scalar(), "failed")

    def test_cli_delivers_due_notifications(self):
        with self.app.app_context():
            with db._engine().begin() as conn:
                db.enqueue_notification(conn, "cli-job", "owner", "hello")
        with patch("app.services.notification_service.send_line_message", return_value=True) as sender:
            result = self.app.test_cli_runner().invoke(args=["send-notifications"])
        self.assertEqual(result.exit_code, 0, result.output)
        sender.assert_called_once()

    def test_combined_listing_pages_have_no_duplicates_or_closed_posts(self):
        with self.app.app_context():
            for index in range(25):
                db.append_material({"line_user_id": "owner", "title": str(index)})
            db.append_material({"line_user_id": "owner", "status": "closed"})
            db.append_material({"line_user_id": "owner", "expires_at": "2000-01-01"})
            db.append_demolition_property({"line_user_id": "owner"})
            first = db.get_public_listing_page("all", "all", 1)
            second = db.get_public_listing_page("all", "all", 2)
            self.assertEqual(len(first[2]), 24)
            self.assertEqual(len(second[2]), 2)
            self.assertTrue(first[3])
            self.assertFalse(second[3])
            self.assertEqual(len({r["id"] for r in first[2] + second[2]}), 26)
        page = self.client.get("/materials/list").get_data(as_text=True)
        self.assertIn("次のページ", page)

    def test_debug_log_endpoint_is_rate_limited(self):
        self.app.config["LIFF_DEBUG_LOGGING"] = True
        with patch("app.routes.link.logger.info"), patch("app.services.rate_limit_service.time.time", return_value=time.time()):
            for _ in range(30):
                self.assertEqual(self.client.post("/link/liff-debug", json={"event": "auth.flow_started"}).status_code, 204)
            self.assertEqual(self.client.post("/link/liff-debug", json={"event": "test"}).status_code, 429)
