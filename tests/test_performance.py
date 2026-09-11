import unittest
from unittest.mock import patch

import test_workflows as fixtures
from app.services import db_service as db
from app.services.image_service import image_delivery_url


class ImageDeliveryTests(unittest.TestCase):
    def test_sizes_original_without_changing_asset_path(self):
        original = "https://res.cloudinary.com/demo/image/upload/v123/folder/photo.jpg"
        self.assertEqual(image_delivery_url(original), "https://res.cloudinary.com/demo/image/upload/c_limit,w_640,h_640/q_auto/f_auto/v123/folder/photo.jpg")
        self.assertIn("w_1280", image_delivery_url(original, 1280))

    def test_preserves_external_signed_and_transformed_urls(self):
        for url in ("", "https://example.com/photo.jpg", "https://res.cloudinary.com/demo/image/upload/s--signature--/v123/photo.jpg", "https://res.cloudinary.com/demo/image/upload/c_fill,w_50/v123/photo.jpg"):
            self.assertEqual(image_delivery_url(url), url)


class HistoryPerformanceTests(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.WorkflowTestCase.setUpClass())
    setUp = fixtures.WorkflowTestCase.setUp
    tearDown = fixtures.WorkflowTestCase.tearDown
    add_user = fixtures.WorkflowTestCase.add_user

    def test_history_uses_fixed_query_count_and_keeps_details(self):
        self.add_user("owner", "Owner")
        self.add_user("visitor", "Visitor")
        with self.app.app_context():
            entry = db.append_material({"line_user_id": "owner", "title": "Wood"})
            for _ in range(20):
                db.append_matching_history({"material_id": entry, "provider_user_id": "owner", "requester_user_id": "visitor"})
            with patch.object(db, "_select_many", wraps=db._select_many) as queries:
                history = db.get_matching_history_by_user("visitor")
            self.assertEqual(len(history), 20)
            self.assertEqual(queries.call_count, 4)
            self.assertTrue(all(r["entry_title"] == "Wood" and r["other_display_name"] == "Owner" for r in history))
            self.assertTrue(all(r["received_contact"] is None for r in history))
