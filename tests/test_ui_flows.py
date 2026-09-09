import re
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from sqlalchemy import select

import test_workflows as fixtures
from app.services import db_service as db


class UiFlowTestCase(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.WorkflowTestCase.setUpClass())
    setUp = fixtures.WorkflowTestCase.setUp
    tearDown = fixtures.WorkflowTestCase.tearDown
    authenticate = fixtures.WorkflowTestCase.authenticate
    post_form = fixtures.WorkflowTestCase.post_form
    add_user = fixtures.WorkflowTestCase.add_user

    def prepare_match(self):
        self.add_user("owner", "投稿者")
        self.add_user("visitor", "問い合わせ相手")
        with self.app.app_context():
            entry = db.append_material({"line_user_id": "owner", "title": "木製ドア"})
            match_id = db.append_matching_history({"material_id": entry, "provider_user_id": "owner", "requester_user_id": "visitor"})
            db.upsert_contact_card("owner", {"contact_value": "090-1234-5678", "contact_method": "電話", "display_name": "投稿者"})
        self.authenticate("owner")
        return f"/users/matches/material/{match_id}/share-contact"

    def shares(self):
        with self.app.app_context(), db._engine().connect() as conn:
            return conn.execute(select(db.contact_share_logs)).all()

    def test_share_preview_does_not_send_or_save_until_confirmed(self):
        route = self.prepare_match()
        with patch("app.routes.users.send_line_message", return_value=True) as send:
            preview = self.client.get(route)
            text = preview.get_data(as_text=True)
            self.assertIn("問い合わせ相手", text)
            self.assertIn("090-1234-5678", text)
            self.assertEqual(preview.headers["Cache-Control"], "no-store")
            self.assertEqual(self.shares(), [])
            send.assert_not_called()
            version = re.search(r'name="contact_version" value="([a-f0-9]+)"', text).group(1)
            response = self.post_form(route, {"contact_version": version})
        self.assertEqual(len(self.shares()), 1)
        self.assertIn("tab=matches", response.location)
        send.assert_called_once()

    def test_direct_post_without_confirmation_does_not_share(self):
        response = self.post_form(self.prepare_match(), {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("この内容で共有する", response.get_data(as_text=True))
        self.assertEqual(self.shares(), [])

    def test_changed_contact_requires_new_confirmation(self):
        route = self.prepare_match()
        preview = self.client.get(route).get_data(as_text=True)
        version = re.search(r'name="contact_version" value="([a-f0-9]+)"', preview).group(1)
        with self.app.app_context():
            db.upsert_contact_card("owner", {"contact_value": "new@example.com", "contact_method": "メール"})
        response = self.post_form(route, {"contact_version": version})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/share-contact"))
        self.assertEqual(self.shares(), [])

    def test_other_user_cannot_see_contact_preview(self):
        route = self.prepare_match()
        self.authenticate("stranger")
        response = self.client.get(route)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("090-1234-5678", response.get_data(as_text=True))

    def test_search_area_and_pagination_preserve_conditions(self):
        with self.app.app_context():
            for _ in range(25):
                db.append_material({"line_user_id": "owner", "title": "木製ドア", "location": "和泊町 現場"})
            db.append_material({"line_user_id": "owner", "title": "木製ドア", "location": "知名町"})
            found = db.get_public_listing_page("all", "all", 1, area="和泊町", query="ドア")
            self.assertEqual(len(found[2]), 24)
            self.assertTrue(found[3])
            self.assertEqual(db.get_public_listing_page("all", "all", 1, query="%")[2], [])
        response = self.client.get("/materials/list", query_string={"q": "ドア", "area": "和泊町"})
        text = response.get_data(as_text=True)
        self.assertEqual(text.count('aria-label="一覧のページ切り替え"'), 2)
        self.assertIn('name="return_q" value="ドア"', text)
        self.assertIn('name="return_area" value="和泊町"', text)

    def test_inquiry_returns_to_original_page_with_next_step(self):
        with self.app.app_context():
            entry = db.append_material({"line_user_id": "owner", "title": "角材"})
        self.authenticate("visitor")
        with patch("app.routes.materials._redirect_unavailable_notifications_to_user_page", return_value=None), patch("app.routes.materials.send_line_message", return_value=False):
            response = self.post_form("/materials/interest", {"material_id": entry, "return_page": "2", "return_q": "角材", "return_area": "知名町", "return_type": "offer"})
        query = parse_qs(urlsplit(response.location).query)
        self.assertEqual(query["page"], ["2"])
        self.assertEqual(query["q"], ["角材"])
        self.assertEqual(query["area"], ["知名町"])
        page = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("問い合わせの履歴を見る", page)
        self.assertIn("送り直す必要はありません", page)
        self.assertNotIn("問い合わせを受け付けました", self.client.get(response.location).get_data(as_text=True))

    def test_draft_completion_is_only_signalled_after_save(self):
        self.add_user("owner", "投稿者")
        self.authenticate("owner")
        self.post_form("/materials/requests/submit", {})
        with self.client.session_transaction() as session:
            self.assertNotIn("completed_draft", session)
        self.post_form("/materials/requests/submit", {"material_type": "木材", "description": "角材を探しています"})
        with self.client.session_transaction() as session:
            self.assertEqual(session["completed_draft"], {"kind": "request", "owner": "owner"})
        self.client.get("/materials/list")
        with self.client.session_transaction() as session:
            self.assertNotIn("completed_draft", session)
