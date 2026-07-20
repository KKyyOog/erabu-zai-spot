import json
import os
import unittest
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.services import db_service


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

    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.csrf_token = "test-csrf-token"

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
