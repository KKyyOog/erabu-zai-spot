import time
import unittest
from unittest.mock import patch

from sqlalchemy import select, update

import test_workflows as workflows
from app.services import db_service as db
from app.services.onboarding_service import WELCOME_MESSAGE, send_welcome_once


class OnboardingTests(unittest.TestCase):
    setUpClass = classmethod(workflows.WorkflowTestCase.setUpClass.__func__)
    setUp = workflows.WorkflowTestCase.setUp
    tearDown = workflows.WorkflowTestCase.tearDown
    authenticate = workflows.WorkflowTestCase.authenticate
    post_form = workflows.WorkflowTestCase.post_form

    def test_first_registration_sends_once_for_all_save_routes(self):
        for index, path in enumerate(("/users/me/save", "/users/submit", "/users/Uwelcome2/update")):
            user_id = f"Uwelcome{index}"
            self.authenticate(user_id)
            with self.subTest(path=path), patch(
                "app.services.notification_service.send_line_message", return_value=True
            ) as sender:
                for _ in range(2):
                    response = self.post_form(path, {
                        "line_user_id": user_id, "display_name": "登録者",
                        "address": "和泊町", "transport_info": "軽トラック",
                    })
                    self.assertEqual(response.status_code, 302)
                sender.assert_called_once()
                self.assertEqual(sender.call_args.args, (user_id, WELCOME_MESSAGE))

    def test_profile_read_does_not_send(self):
        self.authenticate("Uread")
        with patch("app.services.notification_service.send_line_message") as sender:
            response = self.client.post("/users/me/data", json={
                "userId": "Uread", "scope": "profile",
            }, headers={"X-CSRF-Token": self.csrf_token})
            self.assertEqual(response.status_code, 200)
            sender.assert_not_called()

    def test_invalid_or_failed_registration_does_not_send(self):
        self.authenticate("Uinvalid")
        with patch("app.routes.users.send_welcome_once") as welcome:
            self.post_form("/users/me/save", {"line_user_id": "Uinvalid"})
            with patch("app.routes.users.update_user", return_value=None):
                self.post_form("/users/me/save", {
                    "line_user_id": "Uinvalid", "display_name": "登録者",
                    "address": "和泊町", "transport_info": "軽トラック",
                })
            welcome.assert_not_called()

    def test_failed_delivery_retries_with_same_key(self):
        with self.app.app_context(), patch(
            "app.services.notification_service.send_line_message",
            side_effect=[RuntimeError("offline"), True],
        ) as sender:
            self.assertFalse(send_welcome_once("Uretry"))
            with db._engine().begin() as conn:
                conn.execute(update(db.notification_outbox).values(next_attempt_at=int(time.time()) - 1))
            self.assertTrue(send_welcome_once("Uretry"))
            self.assertEqual(sender.call_args_list[0].kwargs, sender.call_args_list[1].kwargs)
            with db._engine().connect() as conn:
                rows = conn.execute(select(db.notification_outbox)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "sent")

    def test_rejected_authentication_does_not_send(self):
        with self.client.session_transaction() as session:
            session["_csrf_token"] = self.csrf_token
        with patch("app.routes.users.send_welcome_once") as welcome:
            response = self.client.post("/users/me/data", json={"userId": "Uother"},
                                        headers={"X-CSRF-Token": self.csrf_token})
            self.assertEqual(response.status_code, 401)
            welcome.assert_not_called()

    def test_guest_does_not_send(self):
        with self.app.app_context(), patch("app.services.onboarding_service.deliver_notification") as deliver:
            self.assertFalse(send_welcome_once("anon_guest"))
            deliver.assert_not_called()

    def test_liff_login_does_not_send(self):
        self.app.config["LINE_LOGIN_ENABLED"] = True
        self.authenticate("Ulogin")
        with patch("app.routes.link.verify_id_token", return_value={"sub": "Ulogin"}), patch(
            "app.services.notification_service.send_line_message", side_effect=RuntimeError("offline")
        ) as sender:
            response = self.client.post("/link/liff", json={"userId": "Ulogin", "idToken": "verified"},
                                        headers={"X-CSRF-Token": self.csrf_token})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["ok"])
            sender.assert_not_called()

    def test_registration_survives_delivery_failure(self):
        self.authenticate("Uoffline")
        with patch("app.services.notification_service.send_line_message", side_effect=RuntimeError("offline")):
            response = self.post_form("/users/me/save", {
                "line_user_id": "Uoffline", "display_name": "登録者",
                "address": "和泊町", "transport_info": "軽トラック",
            })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(db.get_user_by_line_user_id("Uoffline"))


if __name__ == "__main__":
    unittest.main()
