import base64
import hashlib
import hmac
import json
import os
import time
import unittest
from io import BytesIO
from unittest.mock import patch

from sqlalchemy import create_engine, event, inspect, text

from app import create_app
from app.config import Config
from app.services import db_service, user_cache_service
from scripts.migrate_posts_v2 import migrate as migrate_posts_v2


class WorkflowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Config.DATABASE_URL = "sqlite://"
        Config.DATABASE_SSLMODE = ""
        Config.AUTO_CREATE_TABLES = True
        Config.SECRET_KEY = "test-secret-key-that-is-long-enough-for-tests"
        Config.ALLOW_INSECURE_DEV_CONFIG = True
        Config.SESSION_COOKIE_SECURE = False
        Config.LIFF_ID = "test-liff-id"
        Config.LINE_LOGIN_ENABLED = False
        Config.LINE_CHANNEL_SECRET = "test-line-channel-secret"
        Config.LINE_CHANNEL_ACCESS_TOKEN = "test-line-channel-access-token"
        Config.LINE_OFFICIAL_ACCOUNT_ID = "@test-account"
        Config.LIFF_DEBUG_LOGGING = False
        Config.USER_INFO_CACHE_SECONDS = 600
        Config.USER_INFO_CACHE_MAX_ENTRIES = 1000

    def setUp(self):
        user_cache_service.clear_user_profile_cache()
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.csrf_token = "test-csrf-token"

    def tearDown(self):
        user_cache_service.clear_user_profile_cache()
        self.app.extensions["database_engine"].dispose()

    def authenticate(self, line_user_id):
        with self.client.session_transaction() as session:
            session["line_user_id"] = line_user_id
            session["_csrf_token"] = self.csrf_token

    def post_form(self, path, data, follow_redirects=False):
        payload = dict(data)
        payload["_csrf_token"] = self.csrf_token
        return self.client.post(
            path,
            data=payload,
            follow_redirects=follow_redirects,
        )

    def add_user(self, user_id, name):
        with self.app.app_context():
            db_service.append_user(
                {
                    "line_user_id": user_id,
                    "display_name": name,
                    "address": "和泊町",
                    "transport_info": "軽トラック",
                }
            )

    def start_guest_session(self):
        with self.client.session_transaction() as session:
            session["_csrf_token"] = self.csrf_token
        response = self.post_form("/link/guest", {})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def post_line_text_webhook(self, line_user_id, text):
        payload = {
            "destination": "U00000000000000000000000000000000",
            "events": [
                {
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": "123456789012345678",
                        "quoteToken": "test-quote-token",
                        "text": text,
                    },
                    "webhookEventId": "01TESTWEBHOOK000000000000000",
                    "deliveryContext": {"isRedelivery": False},
                    "timestamp": 1750000000000,
                    "source": {
                        "type": "user",
                        "userId": line_user_id,
                    },
                    "replyToken": "test-reply-token",
                    "mode": "active",
                }
            ],
        }
        return self.post_signed_line_webhook(payload)

    def post_line_friendship_webhook(self, line_user_id, event_type):
        event = {
            "type": event_type,
            "webhookEventId": f"01TEST{event_type.upper()}000000000000",
            "deliveryContext": {"isRedelivery": False},
            "timestamp": 1750000000000,
            "source": {
                "type": "user",
                "userId": line_user_id,
            },
            "mode": "active",
        }
        if event_type == "follow":
            event["replyToken"] = "test-follow-reply-token"
            event["follow"] = {"isUnblocked": False}
        payload = {
            "destination": "U00000000000000000000000000000000",
            "events": [event],
        }
        return self.post_signed_line_webhook(payload)

    def post_signed_line_webhook(self, payload):
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        signature = base64.b64encode(
            hmac.new(
                Config.LINE_CHANNEL_SECRET.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        return self.client.post(
            "/callback",
            data=body.encode("utf-8"),
            content_type="application/json",
            headers={"X-Line-Signature": signature},
        )

    def test_notification_tables_exist_when_auto_create_is_disabled(self):
        Config.AUTO_CREATE_TABLES = False
        isolated_app = None
        try:
            isolated_app = create_app()
            engine = isolated_app.extensions["database_engine"]
            table_names = set(inspect(engine).get_table_names())
        finally:
            Config.AUTO_CREATE_TABLES = True
            if isolated_app is not None:
                isolated_app.extensions["database_engine"].dispose()

        self.assertEqual(
            table_names,
            {
                "line_friendships",
                "line_notification_link_codes",
                "line_notification_links",
            },
        )

    def test_guest_links_line_notifications_by_sending_one_time_code(self):
        guest_user_id = self.start_guest_session()["line_user_id"]
        code_response = self.post_form("/link/notification-code", {})
        self.assertEqual(code_response.status_code, 200)
        code_body = code_response.get_json()
        self.assertTrue(code_body["message"].startswith("通知連携 "))
        self.assertIn("%40test-account", code_body["deep_link"])

        initial_status = self.client.get(
            "/link/notification-status"
        ).get_json()
        self.assertFalse(initial_status["linked"])

        line_user_id = "U1234567890abcdef1234567890abcdef"
        with patch(
            "app.routes.callback.reply_line_message",
            return_value=True,
        ) as reply:
            webhook_response = self.post_line_text_webhook(
                line_user_id,
                code_body["message"],
            )
        self.assertEqual(webhook_response.status_code, 200)
        self.assertIn("連携が完了", reply.call_args.args[1])

        with self.app.app_context():
            notification_user_id = (
                db_service.get_notification_line_user_id(guest_user_id)
            )
        self.assertEqual(notification_user_id, line_user_id)
        with patch(
            "app.routes.link.get_line_user_profile",
            return_value={
                "display_name": "Linked LINE user",
                "picture_url": "https://example.com/profile.jpg",
            },
        ):
            linked_status = self.client.get(
                "/link/notification-status?include_profile=1"
            ).get_json()
        self.assertTrue(linked_status["linked"])
        self.assertEqual(
            linked_status["profile"]["display_name"],
            "Linked LINE user",
        )

        with patch(
            "app.routes.callback.reply_line_message",
            return_value=True,
        ) as repeated_reply:
            repeated_response = self.post_line_text_webhook(
                line_user_id,
                code_body["message"],
            )
        self.assertEqual(repeated_response.status_code, 200)
        self.assertIn("すでに連携済み", repeated_reply.call_args.args[1])

        self.add_user("notification-requester", "通知希望者")
        with self.app.app_context():
            db_service.append_user(
                {
                    "line_user_id": guest_user_id,
                    "display_name": "通知を受けるゲスト",
                    "address": "和泊町",
                    "transport_info": "軽トラック",
                }
            )
            material_id = db_service.append_material(
                {
                    "line_user_id": guest_user_id,
                    "title": "通知テスト材",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )

        self.authenticate("notification-requester")
        with patch(
            "app.routes.materials.send_line_message",
            return_value=True,
        ) as send:
            interest_response = self.post_form(
                "/materials/interest",
                {
                    "line_user_id": "notification-requester",
                    "material_id": material_id,
                    "message": "受け取りを希望します",
                },
            )
        self.assertEqual(interest_response.status_code, 302)
        self.assertEqual(send.call_args.args[0], line_user_id)

    def test_expired_notification_link_code_is_rejected(self):
        self.start_guest_session()
        code = "ABCDEFGH23"
        with self.client.session_transaction() as session:
            guest_user_id = session["line_user_id"]
        with self.app.app_context():
            db_service.create_line_notification_link_code(
                guest_user_id,
                hashlib.sha256(code.encode("utf-8")).hexdigest(),
                "2000-01-01 00:00:00",
            )

        with patch(
            "app.routes.callback.reply_line_message",
            return_value=True,
        ) as reply:
            response = self.post_line_text_webhook(
                "Uabcdef1234567890abcdef1234567890",
                f"通知連携 {code}",
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("期限が切れて", reply.call_args.args[1])
        with self.app.app_context():
            self.assertEqual(
                db_service.get_notification_line_user_id(guest_user_id),
                "",
            )

    def test_notification_link_code_rejects_invalid_signature(self):
        response = self.client.post(
            "/callback",
            data=b'{"events":[]}',
            content_type="application/json",
            headers={"X-Line-Signature": "invalid"},
        )
        self.assertEqual(response.status_code, 400)

    def test_follow_and_unfollow_webhooks_update_notification_status(self):
        line_user_id = "U33333333333333333333333333333333"

        follow_response = self.post_line_friendship_webhook(
            line_user_id,
            "follow",
        )
        self.assertEqual(follow_response.status_code, 200)
        with self.app.app_context():
            self.assertTrue(
                db_service.can_receive_line_notifications(line_user_id)
            )

        unfollow_response = self.post_line_friendship_webhook(
            line_user_id,
            "unfollow",
        )
        self.assertEqual(unfollow_response.status_code, 200)
        with self.app.app_context():
            self.assertFalse(
                db_service.can_receive_line_notifications(line_user_id)
            )

    def test_guest_session_is_stable_and_does_not_replace_line_session(self):
        guest = self.start_guest_session()
        self.assertTrue(guest["line_user_id"].startswith("anon_"))
        self.assertEqual(guest["auth_mode"], "guest")

        repeated = self.post_form("/link/guest", {}).get_json()
        self.assertEqual(repeated["line_user_id"], guest["line_user_id"])

        status = self.client.get("/link/session").get_json()
        self.assertTrue(status["ok"])
        self.assertEqual(status["auth_mode"], "guest")
        with self.client.session_transaction() as session:
            self.assertTrue(session.permanent)

        self.authenticate("existing-line-user")
        preserved = self.post_form("/link/guest", {}).get_json()
        self.assertEqual(preserved["line_user_id"], "existing-line-user")
        self.assertEqual(preserved["auth_mode"], "line")

    def test_line_login_endpoint_is_disabled_during_guest_flow_trial(self):
        response = self.client.post(
            "/link/liff",
            json={
                "userId": "U1234567890abcdef1234567890abcdef",
                "idToken": "test-token",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["code"],
            "line_login_disabled",
        )

    def test_line_login_can_be_restored_with_the_feature_flag(self):
        self.app.config["LINE_LOGIN_ENABLED"] = True
        line_user_id = "U1234567890abcdef1234567890abcdef"
        with patch(
            "app.routes.link.verify_id_token",
            return_value={"sub": line_user_id},
        ):
            response = self.client.post(
                "/link/liff",
                json={
                    "userId": line_user_id,
                    "idToken": "test-token",
                },
            )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session["line_user_id"], line_user_id)
            self.assertGreater(session["line_authenticated_at"], 0)
        page = self.client.get("/users/me").get_data(as_text=True)
        self.assertIn(
            "https://static.line-scdn.net/liff/edge/2/sdk.js",
            page,
        )

    def test_guest_can_save_profile_and_register_material(self):
        guest_user_id = self.start_guest_session()["line_user_id"]

        save_response = self.post_form(
            "/users/me/save",
            {
                "line_user_id": guest_user_id,
                "display_name": "ログインなし利用者",
                "address": "知名町",
                "transport_info": "軽トラック",
                "contact_method": "電話",
                "contact_value": "0997-00-0000",
            },
        )
        self.assertEqual(save_response.status_code, 302)

        material_response = self.post_form(
            "/materials/submit",
            {
                "line_user_id": guest_user_id,
                "title": "ゲスト登録の材",
                "material_type": "木材",
                "quantity_level": "少量",
                "location": "知名町",
                "image_url": "https://res.cloudinary.com/test-cloud/image/upload/v1/erabu-zai-spot/uploads/guest.jpg",
            },
        )
        self.assertEqual(material_response.status_code, 302)

        profile_response = self.client.post(
            "/users/me/data",
            json={
                "userId": guest_user_id,
                "scope": "all",
                "refresh": True,
            },
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(profile_response.status_code, 200)
        profile = profile_response.get_json()
        self.assertTrue(profile["exists"])
        self.assertEqual(profile["user"]["display_name"], "ログインなし利用者")
        self.assertEqual(profile["materials"][0]["title"], "ゲスト登録の材")

    def test_unlinked_guest_is_sent_to_notification_setup_before_interest(self):
        guest_user_id = self.start_guest_session()["line_user_id"]
        self.add_user("interest-provider", "提供者")
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "interest-provider",
                    "title": "通知連携が必要な材",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )
            property_id = db_service.append_demolition_property(
                {
                    "line_user_id": "interest-provider",
                    "property_name": "通知連携が必要な物件",
                    "location": "知名町",
                }
            )

        with patch("app.routes.materials.send_line_message") as send:
            material_response = self.post_form(
                "/materials/interest",
                {
                    "line_user_id": guest_user_id,
                    "material_id": material_id,
                    "message": "欲しいです",
                },
            )
            viewing_response = self.post_form(
                "/materials/demolitions/visit-interest",
                {
                    "line_user_id": guest_user_id,
                    "property_id": property_id,
                },
                follow_redirects=True,
            )

        self.assertEqual(material_response.status_code, 302)
        self.assertIn(
            "/users/me?notification_required=1#notification-readiness",
            material_response.headers["Location"],
        )
        self.assertEqual(viewing_response.status_code, 200)
        page = viewing_response.get_data(as_text=True)
        self.assertIn(
            "LINE通知を受け取れる状態にしてください。",
            page,
        )
        self.assertIn('id="notification-readiness"', page)
        send.assert_not_called()
        with self.app.app_context():
            history = db_service.get_matching_history_by_user(guest_user_id)
        self.assertEqual(history, [])

    def test_notification_linked_guest_can_send_interest(self):
        guest_user_id = self.start_guest_session()["line_user_id"]
        self.add_user("linked-interest-provider", "提供者")
        code = "ABCDEFGH23"
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        with self.app.app_context():
            db_service.create_line_notification_link_code(
                guest_user_id,
                code_hash,
                "2999-01-01 00:00:00",
            )
            _, link_status = db_service.consume_line_notification_link_code(
                code_hash,
                "U1234567890abcdef1234567890abcdef",
            )
            material_id = db_service.append_material(
                {
                    "line_user_id": "linked-interest-provider",
                    "title": "通知連携後に希望できる材",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )
        self.assertEqual(link_status, "linked")

        with patch(
            "app.routes.materials.send_line_message",
            return_value=True,
        ) as send:
            response = self.post_form(
                "/materials/interest",
                {
                    "line_user_id": guest_user_id,
                    "material_id": material_id,
                    "message": "欲しいです",
                },
            )

        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        with self.app.app_context():
            history = db_service.get_matching_history_by_user(guest_user_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["material_id"], material_id)

    def test_line_user_must_be_a_friend_before_sending_interest(self):
        line_user_id = "U44444444444444444444444444444444"
        self.add_user("friendship-provider", "提供者")
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "friendship-provider",
                    "title": "友だち確認用の材",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )
        self.authenticate(line_user_id)

        blocked = self.post_form(
            "/materials/interest",
            {
                "line_user_id": line_user_id,
                "material_id": material_id,
            },
        )
        self.assertIn(
            "/users/me?notification_required=1#notification-readiness",
            blocked.headers["Location"],
        )

        with self.app.app_context():
            db_service.set_line_friendship(line_user_id, True)
        with patch(
            "app.routes.materials.send_line_message",
            return_value=True,
        ) as send:
            allowed = self.post_form(
                "/materials/interest",
                {
                    "line_user_id": line_user_id,
                    "material_id": material_id,
                },
            )
        self.assertEqual(allowed.status_code, 302)
        send.assert_called_once()

    def test_guest_session_cannot_access_another_user(self):
        self.add_user("other-user", "別の利用者")
        self.start_guest_session()

        response = self.client.post(
            "/users/me/data",
            json={"userId": "other-user", "scope": "profile"},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(response.status_code, 401)

    def test_my_page_uses_line_identity_and_simple_readiness_status(self):
        self.app.config["LINE_LOGIN_ENABLED"] = True
        page = self.client.get("/users/me").get_data(as_text=True)
        self.assertIn("LINE本人確認", page)
        self.assertIn("LINE通知", page)
        self.assertIn("友だち追加・ブロック解除", page)
        self.assertIn("connectLineIdentity", page)
        self.assertIn("syncFriendshipStatus", page)
        self.assertIn("restoreCachedLineIdentity", page)
        self.assertIn("window.cacheUserRegistration", page)
        self.assertIn("window.USER_INFO_CACHE_SECONDS = 600", page)
        self.assertIn("window.LINE_LOGIN_ENABLED = true", page)
        self.assertIn('id="user-page-skeleton"', page)
        self.assertIn('id="user-page-live" class="user-page-live" hidden', page)
        self.assertIn('id="page-transition-skeleton"', page)
        self.assertIn("startUserPageSkeletonFallback", page)
        self.assertNotIn("通知連携コード", page)
        self.assertIn(
            "https://static.line-scdn.net/liff/edge/2/sdk.js",
            page,
        )

    def test_line_login_migrates_existing_guest_profile_and_posts(self):
        guest_user_id = self.start_guest_session()["line_user_id"]
        with self.app.app_context():
            db_service.append_user(
                {
                    "line_user_id": guest_user_id,
                    "display_name": "移行前ユーザー",
                    "address": "和泊町",
                    "transport_info": "軽トラック",
                }
            )
            db_service.upsert_contact_card(
                guest_user_id,
                {
                    "contact_display_name": "移行連絡先",
                    "contact_method": "電話",
                    "contact_value": "090-0000-0000",
                },
            )
            db_service.append_material(
                {
                    "line_user_id": guest_user_id,
                    "title": "移行対象の材",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )

        self.app.config["LINE_LOGIN_ENABLED"] = True
        line_user_id = "U11111111111111111111111111111111"
        with patch(
            "app.routes.link.verify_id_token",
            return_value={"sub": line_user_id},
        ):
            response = self.client.post(
                "/link/liff",
                json={"userId": line_user_id, "idToken": "test-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["migrated_guest_data"])
        with self.app.app_context():
            self.assertIsNone(
                db_service.get_user_by_line_user_id(guest_user_id)
            )
            migrated_user = db_service.get_user_by_line_user_id(line_user_id)
            self.assertEqual(migrated_user["display_name"], "移行前ユーザー")
            self.assertEqual(
                db_service.get_contact_card_by_user(line_user_id)["contact_value"],
                "090-0000-0000",
            )
            self.assertEqual(
                db_service.get_materials_by_line_user_id(line_user_id)[0]["title"],
                "移行対象の材",
            )

    def test_line_mode_disables_new_guest_sessions(self):
        self.app.config["LINE_LOGIN_ENABLED"] = True
        with self.client.session_transaction() as session:
            session["_csrf_token"] = self.csrf_token

        response = self.post_form("/link/guest", {})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "line_login_required")

    def test_authenticated_line_user_can_sync_friendship_status(self):
        line_user_id = "U22222222222222222222222222222222"
        self.authenticate(line_user_id)

        response = self.client.post(
            "/link/friendship",
            json={"friendFlag": True},
            headers={"X-CSRF-Token": self.csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["friend"])
        with self.app.app_context():
            self.assertTrue(
                db_service.can_receive_line_notifications(line_user_id)
            )

    def test_recent_line_session_can_skip_reauthentication(self):
        line_user_id = "U44444444444444444444444444444444"
        with self.client.session_transaction() as session:
            session["line_user_id"] = line_user_id
            session["line_authenticated_at"] = int(time.time())

        response = self.client.get("/link/session")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["cache_valid"])
        self.assertGreater(body["cache_expires_in"], 0)

    def test_expired_line_session_requires_fresh_liff_authentication(self):
        line_user_id = "U55555555555555555555555555555555"
        self.app.config["USER_INFO_CACHE_SECONDS"] = 600
        with self.client.session_transaction() as session:
            session["line_user_id"] = line_user_id
            session["line_authenticated_at"] = int(time.time()) - 601

        response = self.client.get("/link/session")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["cache_valid"])
        self.assertEqual(body["cache_expires_in"], 0)

    def test_user_registration_check_reuses_cached_profile(self):
        line_user_id = "cached-profile-user"
        self.add_user(line_user_id, "キャッシュ利用者")
        self.authenticate(line_user_id)

        with patch(
            "app.services.user_cache_service.get_me_profile_by_line_user_id",
            wraps=db_service.get_me_profile_by_line_user_id,
        ) as loader:
            first = self.client.get(f"/users/check/{line_user_id}")
            second = self.client.get(f"/users/check/{line_user_id}")

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()["exists"])
        self.assertFalse(first.get_json()["cached"])
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(loader.call_count, 1)

    def test_profile_update_refreshes_cached_user_information(self):
        line_user_id = "cache-update-user"
        self.add_user(line_user_id, "変更前")
        self.authenticate(line_user_id)

        initial = self.client.get(f"/users/check/{line_user_id}")
        self.assertTrue(initial.get_json()["exists"])

        save_response = self.post_form(
            "/users/me/save",
            {
                "line_user_id": line_user_id,
                "display_name": "変更後",
                "address": "知名町",
                "transport_info": "軽トラック",
                "contact_display_name": "新しい連絡先名",
                "contact_method": "LINE",
                "contact_value": "line-contact",
            },
        )
        self.assertEqual(save_response.status_code, 302)

        profile_response = self.client.post(
            "/users/me/data",
            json={"userId": line_user_id, "scope": "profile"},
            headers={"X-CSRF-Token": self.csrf_token},
        )

        self.assertEqual(profile_response.status_code, 200)
        profile = profile_response.get_json()
        self.assertTrue(profile["cached"])
        self.assertEqual(profile["user"]["display_name"], "変更後")
        self.assertEqual(profile["contact_card"]["display_name"], "新しい連絡先名")

    def test_liff_debug_logging_records_structured_safe_event(self):
        line_user_id = "U33333333333333333333333333333333"
        self.authenticate(line_user_id)
        self.app.config["LIFF_DEBUG_LOGGING"] = True

        with self.assertLogs("app.routes.link", level="INFO") as captured:
            response = self.client.post(
                "/link/liff-debug",
                json={
                    "event": "friendship.check_failed",
                    "level": "warning",
                    "traceId": "trace-test-1",
                    "timestamp": "2026-09-08T00:00:00.000Z",
                    "details": {
                        "errorCode": "400",
                        "errorMessage": "There is no login bot linked",
                        "friendFlag": False,
                        "idToken": "secret-id-token",
                        "href": "https://example.com/?code=secret-code",
                    },
                },
                headers={"Referer": "https://example.com/users/me?code=secret-code"},
            )

        self.assertEqual(response.status_code, 204)
        log_output = "\n".join(captured.output)
        self.assertIn("event=friendship.check_failed", log_output)
        self.assertIn("trace=trace-test-1", log_output)
        self.assertIn('"errorCode":"400"', log_output)
        self.assertIn('"friendFlag":false', log_output)
        self.assertIn("referer_path=/users/me", log_output)
        self.assertIn("[redacted]", log_output)
        self.assertNotIn("secret-id-token", log_output)
        self.assertNotIn("secret-code", log_output)
        self.assertNotIn(line_user_id, log_output)

    def test_disabled_liff_debug_endpoint_does_not_return_404(self):
        self.app.config["LIFF_DEBUG_LOGGING"] = False

        response = self.client.post(
            "/link/liff-debug",
            json={"event": "page.initialization_started"},
        )

        self.assertEqual(response.status_code, 204)

    def test_registration_forms_use_photo_picker_without_url_inputs(self):
        material_page = self.client.get("/materials/register/material").get_data(
            as_text=True
        )
        self.assertIn("写真を撮る・ライブラリから選ぶ", material_page)
        self.assertIn('name="image_files"', material_page)
        self.assertNotIn('name="image_urls_text"', material_page)
        self.assertIn('class="registration-skeleton skeleton-screen"', material_page)

        demolition_page = self.client.get(
            "/materials/register/demolition"
        ).get_data(as_text=True)
        self.assertIn("建物写真を撮る・ライブラリから選ぶ", demolition_page)
        self.assertIn('name="building_image_files"', demolition_page)
        self.assertNotIn('name="building_photo_urls_text"', demolition_page)
        self.assertIn('class="registration-skeleton skeleton-screen"', demolition_page)

        request_page = self.client.get(
            "/materials/register/request"
        ).get_data(as_text=True)
        self.assertIn("材を探しています", request_page)
        self.assertIn('name="description"', request_page)
        self.assertIn('name="image_files"', request_page)
        self.assertNotIn('name="image_urls_text"', request_page)
        self.assertIn('class="registration-skeleton skeleton-screen"', request_page)

        selection_page = self.client.get("/materials/register").get_data(
            as_text=True
        )
        self.assertIn("材があります", selection_page)
        self.assertIn("材を探しています", selection_page)
        self.assertIn("解体予定物件を登録する", selection_page)

    def test_profile_scope_authenticates_and_uses_one_database_query(self):
        self.add_user("fast-profile-user", "高速表示ユーザー")
        with self.app.app_context():
            db_service.upsert_contact_card(
                "fast-profile-user",
                {
                    "contact_display_name": "連絡先名",
                    "contact_method": "電話",
                    "contact_value": "090-0000-0000",
                },
            )

        with self.client.session_transaction() as session:
            session["_csrf_token"] = self.csrf_token

        engine = self.app.extensions["database_engine"]
        select_statements = []

        def record_statement(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                select_statements.append(statement)

        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            with patch(
                "app.services.line_auth_service.verify_id_token",
                return_value={"sub": "fast-profile-user"},
            ):
                response = self.client.post(
                    "/users/me/data",
                    json={
                        "userId": "fast-profile-user",
                        "idToken": "valid-id-token",
                        "scope": "profile",
                        "refresh": True,
                    },
                    headers={"X-CSRF-Token": self.csrf_token},
                )
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["exists"])
        self.assertEqual(body["user"]["display_name"], "高速表示ユーザー")
        self.assertEqual(body["contact_card"]["display_name"], "連絡先名")
        self.assertNotIn("materials", body)
        self.assertEqual(len(select_statements), 1)
        with self.client.session_transaction() as session:
            self.assertEqual(session["line_user_id"], "fast-profile-user")

    def test_profile_scope_reuses_verified_session_without_token_verification(self):
        self.add_user("session-profile-user", "セッション利用者")
        self.authenticate("session-profile-user")

        with patch(
            "app.services.line_auth_service.verify_id_token"
        ) as verify_id_token:
            response = self.client.post(
                "/users/me/data",
                json={
                    "userId": "session-profile-user",
                    "idToken": "already-verified-token",
                    "scope": "profile",
                    "refresh": True,
                },
                headers={"X-CSRF-Token": self.csrf_token},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["display_name"], "セッション利用者")
        verify_id_token.assert_not_called()

    def test_demolition_can_be_edited_and_deleted_by_owner(self):
        self.add_user("owner-user", "登録者")
        with self.app.app_context():
            property_id = db_service.append_demolition_property(
                {
                    "line_user_id": "owner-user",
                    "registrant_type": "家主",
                    "property_name": "旧住宅",
                    "location": "和泊町",
                }
            )

        self.authenticate("owner-user")
        me_data = self.client.post(
            "/users/me/data",
            json={"userId": "owner-user", "refresh": True},
            headers={"X-CSRF-Token": self.csrf_token},
        )
        self.assertEqual(me_data.status_code, 200)
        self.assertEqual(
            me_data.get_json()["demolition_properties"][0]["property_id"],
            property_id,
        )

        edit_page = self.client.get(f"/materials/demolitions/{property_id}/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn("旧住宅", edit_page.get_data(as_text=True))

        update_response = self.post_form(
            f"/materials/demolitions/{property_id}/update",
            {
                "line_user_id": "owner-user",
                "registrant_type": "管理者・代理人",
                "property_name": "旧住宅（更新）",
                "location": "知名町",
                "building_photo_urls_text": "",
            },
        )
        self.assertEqual(update_response.status_code, 302)
        with self.app.app_context():
            updated = db_service.get_demolition_property_by_id(property_id)
        self.assertEqual(updated["property_name"], "旧住宅（更新）")
        self.assertEqual(updated["line_user_id"], "owner-user")

        with patch("app.routes.materials.cloudinary.uploader.destroy") as destroy:
            delete_response = self.post_form(
                f"/materials/demolitions/{property_id}/delete",
                {"line_user_id": "owner-user"},
            )
        self.assertEqual(delete_response.status_code, 302)
        destroy.assert_not_called()
        with self.app.app_context():
            deleted = db_service.get_demolition_property_by_id(property_id)
        self.assertEqual(deleted["status"], "削除済み")

    def test_delete_removes_cloudinary_images_for_material_and_demolition(self):
        cloud_name = "test-cloud"
        os.environ["CLOUDINARY_CLOUD_NAME"] = cloud_name
        material_url = (
            f"https://res.cloudinary.com/{cloud_name}/image/upload/"
            "v123/erabu-zai-spot/uploads/material-image.jpg"
        )
        demolition_url = (
            f"https://res.cloudinary.com/{cloud_name}/image/upload/"
            "v124/erabu-zai-spot/uploads/demolition-image.webp"
        )
        self.add_user("image-owner", "画像登録者")
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "image-owner",
                    "title": "古材",
                    "material_type": "木材",
                    "location": "和泊町",
                    "image_url": material_url,
                    "image_urls": json.dumps([material_url]),
                }
            )
            property_id = db_service.append_demolition_property(
                {
                    "line_user_id": "image-owner",
                    "registrant_type": "家主",
                    "property_name": "解体予定住宅",
                    "location": "和泊町",
                    "building_photo_url": demolition_url,
                    "building_photo_urls": json.dumps([demolition_url]),
                }
            )

        self.authenticate("image-owner")
        with patch(
            "app.routes.materials.cloudinary.uploader.destroy",
            return_value={"result": "ok"},
        ) as destroy:
            self.post_form(
                f"/materials/{material_id}/delete",
                {"line_user_id": "image-owner", "return_to": "me"},
            )
            self.post_form(
                f"/materials/demolitions/{property_id}/delete",
                {"line_user_id": "image-owner"},
            )

        public_ids = [call.args[0] for call in destroy.call_args_list]
        self.assertEqual(
            public_ids,
            [
                "erabu-zai-spot/uploads/material-image",
                "erabu-zai-spot/uploads/demolition-image",
            ],
        )

    def test_match_status_can_only_be_updated_by_a_participant(self):
        self.add_user("provider-user", "提供者")
        self.add_user("requester-user", "希望者")
        self.add_user("other-user", "第三者")
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "provider-user",
                    "title": "建具",
                    "material_type": "建具",
                    "location": "知名町",
                }
            )
            match_id = db_service.append_matching_history(
                {
                    "material_id": material_id,
                    "provider_user_id": "provider-user",
                    "requester_user_id": "requester-user",
                    "action": "欲しい",
                }
            )

        self.authenticate("requester-user")
        with patch("app.routes.users.send_line_message", return_value=True):
            response = self.post_form(
                f"/users/matches/material/{match_id}/status",
                {"line_user_id": "requester-user", "status": "成立"},
            )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            _, updated = db_service.get_matching_history_by_id(match_id, "material")
        self.assertEqual(updated["status"], "成立")

        self.authenticate("other-user")
        rejected = self.post_form(
            f"/users/matches/material/{match_id}/status",
            {"line_user_id": "other-user", "status": "辞退"},
        )
        self.assertEqual(rejected.status_code, 302)
        with self.app.app_context():
            _, unchanged = db_service.get_matching_history_by_id(match_id, "material")
        self.assertEqual(unchanged["status"], "成立")

    def test_delete_keeps_a_cloudinary_image_used_by_another_active_entry(self):
        cloud_name = "test-cloud"
        os.environ["CLOUDINARY_CLOUD_NAME"] = cloud_name
        shared_url = (
            f"https://res.cloudinary.com/{cloud_name}/image/upload/"
            "v125/erabu-zai-spot/uploads/shared-image.jpg"
        )
        self.add_user("shared-owner", "共有画像登録者")
        with self.app.app_context():
            first_material_id = db_service.append_material(
                {
                    "line_user_id": "shared-owner",
                    "title": "共有画像の材1",
                    "material_type": "木材",
                    "location": "和泊町",
                    "image_url": shared_url,
                    "image_urls": json.dumps([shared_url]),
                }
            )
            db_service.append_material(
                {
                    "line_user_id": "shared-owner",
                    "title": "共有画像の材2",
                    "material_type": "木材",
                    "location": "和泊町",
                    "image_url": shared_url,
                    "image_urls": json.dumps([shared_url]),
                }
            )

        self.authenticate("shared-owner")
        with patch("app.routes.materials.cloudinary.uploader.destroy") as destroy:
            response = self.post_form(
                f"/materials/{first_material_id}/delete",
                {"line_user_id": "shared-owner", "return_to": "me"},
            )

        self.assertEqual(response.status_code, 302)
        destroy.assert_not_called()

    def test_interest_reports_line_notification_failure_without_losing_history(self):
        self.add_user("provider-user", "提供者")
        self.add_user("requester-user", "希望者")
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "provider-user",
                    "title": "角材",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )

        self.authenticate("requester-user")
        with patch("app.routes.materials.send_line_message", return_value=False):
            response = self.post_form(
                "/materials/interest",
                {
                    "line_user_id": "requester-user",
                    "material_id": material_id,
                    "message": "引き取りたいです",
                },
                follow_redirects=True,
            )

        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("登録者へのLINE通知に失敗しました", page)
        with self.app.app_context():
            history = db_service.get_matching_history_by_user("requester-user")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["material_id"], material_id)

    def test_offer_creation_saves_post_type_expiry_and_multiple_images(self):
        self.add_user("offer-owner", "提供者")
        self.authenticate("offer-owner")
        uploaded_urls = [
            "https://res.cloudinary.com/test-cloud/image/upload/v1/erabu-zai-spot/uploads/offer-1.jpg",
            "https://res.cloudinary.com/test-cloud/image/upload/v1/erabu-zai-spot/uploads/offer-2.jpg",
        ]

        with patch(
            "app.routes.materials._upload_images",
            return_value=uploaded_urls,
        ):
            response = self.post_form(
                "/materials/submit",
                {
                    "line_user_id": "offer-owner",
                    "material_type": "木材",
                    "quantity_level": "少量",
                    "location": "和泊町",
                    "image_files": [
                        (BytesIO(b"first"), "first.jpg"),
                        (BytesIO(b"second"), "second.jpg"),
                    ],
                },
            )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            records = db_service.get_materials_by_line_user_id("offer-owner")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["post_type"], "offer")
        self.assertEqual(records[0]["status"], "active")
        self.assertEqual(records[0]["effective_status"], "active")
        self.assertEqual(records[0]["quantity_level"], "少量")
        self.assertEqual(records[0]["title"], "木材があります")
        self.assertEqual(records[0]["image_urls"], uploaded_urls)
        self.assertTrue(records[0]["expires_at"])

    def test_offer_requires_at_least_one_photo(self):
        self.add_user("offer-without-photo", "提供者")
        self.authenticate("offer-without-photo")

        response = self.post_form(
            "/materials/submit",
            {
                "line_user_id": "offer-without-photo",
                "material_type": "木材",
                "quantity_level": "少量",
                "location": "和泊町",
            },
            follow_redirects=True,
        )

        self.assertIn("写真を1枚以上登録してください", response.get_data(as_text=True))
        with self.app.app_context():
            records = db_service.get_materials_by_line_user_id("offer-without-photo")
        self.assertEqual(records, [])

    def test_offer_edit_keeps_selected_existing_images(self):
        first_url = "https://res.cloudinary.com/test-cloud/image/upload/v1/erabu-zai-spot/uploads/keep.jpg"
        second_url = "https://res.cloudinary.com/test-cloud/image/upload/v1/erabu-zai-spot/uploads/remove.jpg"
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "image-edit-owner",
                    "title": "画像編集用",
                    "post_type": "offer",
                    "material_type": "木材",
                    "quantity_level": "少量",
                    "location": "和泊町",
                    "image_url": first_url,
                    "image_urls": json.dumps([first_url, second_url]),
                }
            )
        self.authenticate("image-edit-owner")

        response = self.post_form(
            f"/materials/{material_id}/update",
            {
                "line_user_id": "image-edit-owner",
                "post_type": "offer",
                "title": "画像編集用",
                "material_type": "木材",
                "quantity_level": "少量",
                "location": "和泊町",
                "keep_image_urls_present": "1",
                "keep_image_urls": first_url,
            },
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            record = db_service.get_material_by_id(material_id)
        self.assertEqual(record["image_urls"], [first_url])

    def test_request_creation_allows_no_photo(self):
        self.add_user("request-owner", "探している人")
        self.authenticate("request-owner")

        response = self.post_form(
            "/materials/requests/submit",
            {
                "line_user_id": "request-owner",
                "material_type": "建具",
                "description": "古い木製建具を探しています",
                "quantity": "2枚",
                "size": "高さ2m程度",
                "usage_purpose": "修繕",
                "location": "島内どこでも可",
            },
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            records = db_service.get_materials_by_line_user_id("request-owner")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["post_type"], "request")
        self.assertEqual(records[0]["title"], "建具を探しています")
        self.assertEqual(records[0]["image_urls"], [])
        self.assertEqual(records[0]["usage_purpose"], "修繕")

    def test_offer_and_request_list_filters(self):
        with self.app.app_context():
            db_service.append_material(
                {
                    "line_user_id": "offer-filter-owner",
                    "title": "フィルター用提供投稿",
                    "post_type": "offer",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )
            db_service.append_material(
                {
                    "line_user_id": "request-filter-owner",
                    "title": "フィルター用募集投稿",
                    "post_type": "request",
                    "material_type": "木材",
                    "description": "角材を探しています",
                }
            )

        offer_page = self.client.get(
            "/materials/list?type=offer"
        ).get_data(as_text=True)
        request_page = self.client.get(
            "/materials/list?type=request"
        ).get_data(as_text=True)
        self.assertIn("フィルター用提供投稿", offer_page)
        self.assertNotIn("フィルター用募集投稿", offer_page)
        self.assertIn("フィルター用募集投稿", request_page)
        self.assertNotIn("フィルター用提供投稿", request_page)

    def test_legacy_material_is_read_as_active_offer_without_expiry(self):
        with self.app.app_context():
            db_service.upsert_material_record(
                {
                    "material_id": "legacy-material",
                    "line_user_id": "legacy-owner",
                    "title": "既存の材",
                    "material_type": "家具",
                    "location": "知名町",
                    "status": "募集中",
                    "created_at": "2026-01-01 00:00:00",
                }
            )
            record = db_service.get_material_by_id("legacy-material")
            public_ids = {
                item["material_id"] for item in db_service.get_materials()
            }

        self.assertEqual(record["post_type"], "offer")
        self.assertEqual(record["effective_status"], "active")
        self.assertEqual(record["expires_at"], "")
        self.assertIn("legacy-material", public_ids)

    def test_posts_v2_migration_is_idempotent_and_preserves_legacy_rows(self):
        engine = create_engine("sqlite://", future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE materials ("
                        "material_id VARCHAR(64) PRIMARY KEY, status VARCHAR(64))"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE users ("
                        "line_user_id VARCHAR(255) PRIMARY KEY, display_name TEXT)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO materials (material_id, status) "
                        "VALUES ('legacy-row', '募集中')"
                    )
                )

            first_added = migrate_posts_v2(engine)
            second_added = migrate_posts_v2(engine)
            material_columns = {
                column["name"] for column in inspect(engine).get_columns("materials")
            }
            user_columns = {
                column["name"] for column in inspect(engine).get_columns("users")
            }
            with engine.connect() as connection:
                legacy_row = connection.execute(
                    text(
                        "SELECT post_type, expires_at FROM materials "
                        "WHERE material_id = 'legacy-row'"
                    )
                ).one()
        finally:
            engine.dispose()

        self.assertIn("materials.post_type", first_added)
        self.assertEqual(second_added, [])
        self.assertTrue(
            {"post_type", "quantity_level", "usage_purpose", "expires_at"}
            <= material_columns
        )
        self.assertTrue(
            {"business_name", "user_category", "area"} <= user_columns
        )
        self.assertEqual(legacy_row.post_type, "offer")
        self.assertEqual(legacy_row.expires_at, "")

    def test_optional_user_profile_fields_are_saved(self):
        self.authenticate("profile-fields-user")
        response = self.post_form(
            "/users/me/save",
            {
                "line_user_id": "profile-fields-user",
                "display_name": "山田",
                "business_name": "山田木工",
                "user_category": "島内事業者",
                "area": "和泊町",
                "address": "和泊町手々知名",
                "transport_info": "軽トラック",
            },
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db_service.get_user_by_line_user_id("profile-fields-user")
        self.assertEqual(user["business_name"], "山田木工")
        self.assertEqual(user["user_category"], "島内事業者")
        self.assertEqual(user["area"], "和泊町")

    def test_owner_can_close_and_renew_post(self):
        self.add_user("status-owner", "投稿者")
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "status-owner",
                    "title": "終了確認用",
                    "post_type": "offer",
                    "material_type": "木材",
                    "location": "和泊町",
                }
            )
        self.authenticate("status-owner")

        close_response = self.post_form(
            f"/materials/{material_id}/close",
            {"line_user_id": "status-owner"},
        )
        self.assertEqual(close_response.status_code, 302)
        with self.app.app_context():
            closed = db_service.get_material_by_id(material_id)
            public_ids = {
                item["material_id"] for item in db_service.get_materials()
            }
        self.assertEqual(closed["effective_status"], "closed")
        self.assertNotIn(material_id, public_ids)

        renew_response = self.post_form(
            f"/materials/{material_id}/renew",
            {"line_user_id": "status-owner"},
        )
        self.assertEqual(renew_response.status_code, 302)
        with self.app.app_context():
            renewed = db_service.get_material_by_id(material_id)
        self.assertEqual(renewed["effective_status"], "active")
        self.assertTrue(renewed["expires_at"])

    def test_non_owner_cannot_close_post(self):
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "real-owner",
                    "title": "所有者確認用",
                    "post_type": "request",
                    "material_type": "木材",
                    "description": "木材を探しています",
                }
            )
        self.authenticate("other-user")

        response = self.post_form(
            f"/materials/{material_id}/close",
            {"line_user_id": "other-user"},
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            record = db_service.get_material_by_id(material_id)
        self.assertEqual(record["effective_status"], "active")

    def test_expired_post_is_hidden_but_remains_on_my_page(self):
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "expired-owner",
                    "title": "期限切れ投稿",
                    "post_type": "request",
                    "material_type": "木材",
                    "description": "材を探しています",
                    "expires_at": "2000-01-01 00:00:00",
                }
            )
            public_ids = {
                item["material_id"] for item in db_service.get_materials()
            }
            own_records = db_service.get_materials_by_line_user_id(
                "expired-owner"
            )

        self.assertNotIn(material_id, public_ids)
        self.assertEqual(len(own_records), 1)
        self.assertEqual(own_records[0]["effective_status"], "expired")

    def test_request_inquiry_records_supplier_and_notifies_request_owner(self):
        self.add_user("wanted-owner", "探している人")
        self.add_user("supplier-user", "提供できる人")
        with self.app.app_context():
            material_id = db_service.append_material(
                {
                    "line_user_id": "wanted-owner",
                    "title": "角材を探しています",
                    "post_type": "request",
                    "material_type": "木材",
                    "description": "2m程度の角材",
                }
            )
        self.authenticate("supplier-user")

        with patch(
            "app.routes.materials.send_line_message",
            return_value=True,
        ) as send:
            response = self.post_form(
                "/materials/interest",
                {
                    "line_user_id": "supplier-user",
                    "material_id": material_id,
                    "message": "提供できる材があります",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(send.call_args.args[0], "wanted-owner")
        with self.app.app_context():
            history = db_service.get_matching_history_by_user("wanted-owner")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["match_type"], "request")
        self.assertEqual(history[0]["provider_user_id"], "supplier-user")
        self.assertEqual(history[0]["requester_user_id"], "wanted-owner")


if __name__ == "__main__":
    unittest.main()
