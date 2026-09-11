import unittest
from io import BytesIO
from threading import Barrier, Lock
from unittest.mock import patch

from sqlalchemy import select
from werkzeug.datastructures import FileStorage

import test_workflows as fixtures
from app.services import db_service as db
from app.services.image_service import image_delivery_url
from app.routes.materials import _upload_images


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


class RegistrationPerformanceTests(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.WorkflowTestCase.setUpClass())
    setUp = fixtures.WorkflowTestCase.setUp
    tearDown = fixtures.WorkflowTestCase.tearDown
    authenticate = fixtures.WorkflowTestCase.authenticate
    add_user = fixtures.WorkflowTestCase.add_user

    @staticmethod
    def photo(name='photo.png'):
        return FileStorage(stream=BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 24), filename=name)

    def test_uploads_overlap_with_at_most_two_workers_and_keep_order(self):
        barrier, lock = Barrier(2), Lock()
        active = peak = 0
        def upload(file, public_id, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=3)
            with lock:
                active -= 1
            return {'secure_url': f'https://res.cloudinary.com/demo/image/upload/{file.filename}'}
        with self.app.test_request_context('/'), patch('cloudinary.uploader.upload', side_effect=upload):
            urls = _upload_images([self.photo(f'{i}.png') for i in range(6)])
        self.assertEqual(peak, 2)
        self.assertEqual([url.rsplit('/', 1)[-1] for url in urls], [f'{i}.png' for i in range(6)])

    def test_validate_all_files_before_starting_uploads(self):
        with self.app.test_request_context('/'), patch('cloudinary.uploader.upload') as upload:
            with self.assertRaises(ValueError):
                _upload_images([self.photo(), self.photo('invalid.jpg')])
            upload.assert_not_called()
            with db._engine().connect() as conn:
                self.assertEqual(conn.execute(select(db.image_upload_jobs)).all(), [])

    def test_saved_post_skips_full_scan_and_acknowledges_jobs(self):
        self.add_user('owner', 'Owner')
        self.authenticate('owner')
        def upload(file, public_id, **kwargs):
            return {'secure_url': f'https://res.cloudinary.com/demo/image/upload/{public_id}.png'}
        with patch('cloudinary.uploader.upload', side_effect=upload), patch('app.routes.materials._active_cloudinary_image_urls') as scan, patch('cloudinary.uploader.destroy') as destroy:
            response = self.client.post('/materials/submit', data={
                '_csrf_token': self.csrf_token, 'line_user_id': 'owner',
                'material_type': '木材', 'quantity_level': '少量', 'location': '和泊町',
                'image_files': self.photo(),
            })
            self.assertIn('/materials/list', response.location)
            scan.assert_not_called()
            destroy.assert_not_called()
        with self.app.app_context(), db._engine().connect() as conn:
            self.assertEqual(conn.execute(select(db.image_upload_jobs)).all(), [])
            self.assertEqual(len(conn.execute(select(db.materials)).all()), 1)

    def test_registration_check_includes_only_own_location_on_request(self):
        self.add_user('owner', 'Owner')
        self.authenticate('owner')
        ordinary = self.client.get('/users/check/owner').get_json()
        self.assertNotIn('profile_location', ordinary)
        response = self.client.get('/users/check/owner?include=location')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(set(response.get_json()['profile_location']), {'area', 'address'})
        self.assertEqual(self.client.get('/users/check/another?include=location').status_code, 401)
