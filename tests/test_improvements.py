import time
import os
import unittest
from io import BytesIO
from unittest.mock import patch
from sqlalchemy import select, create_engine, inspect
from werkzeug.datastructures import FileStorage
import test_workflows as fixtures
from app.services import db_service as db
from app.services.admin_service import change_post_status
from app.services.notification_service import drain_notifications
from app.routes.materials import _upload_images, clean_upload_jobs
from scripts.migrate_operations import migrate


class ImprovementsTestCase(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.WorkflowTestCase.setUpClass())
    setUp = fixtures.WorkflowTestCase.setUp
    tearDown = fixtures.WorkflowTestCase.tearDown
    authenticate = fixtures.WorkflowTestCase.authenticate
    post_form = fixtures.WorkflowTestCase.post_form
    add_user = fixtures.WorkflowTestCase.add_user

    def create_match(self):
        self.add_user('owner', '投稿者')
        self.add_user('visitor', '希望者')
        with self.app.app_context():
            entry = db.append_material({'line_user_id': 'owner', 'title': '角材', 'location': '和泊町 字手々知名123番地'})
            match = db.append_matching_history({'material_id': entry, 'provider_user_id': 'owner', 'requester_user_id': 'visitor'}, prevent_duplicate=True)
        return entry, match

    def test_exact_location_is_private_on_all_public_surfaces(self):
        entry, _ = self.create_match()
        with self.app.app_context():
            building = db.append_demolition_property({'line_user_id': 'owner', 'property_name': '倉庫',
                'location': '知名町 字住吉987番地', 'owner_name': '非公開の所有者'})
        for path in ('/materials/list', f'/materials/{entry}', f'/materials/demolitions/{building}'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertNotIn('123番地', text)
            self.assertNotIn('987番地', text)
            self.assertNotIn('非公開の所有者', text)
        self.authenticate('owner')
        response = self.client.post('/users/me/data', json={'userId': 'owner', 'scope': 'activity'}, headers={'X-CSRF-Token': self.csrf_token})
        self.assertIn('123番地', response.get_json()['materials'][0]['location'])

    def test_load_failure_is_not_an_empty_search_result(self):
        with patch('app.routes.materials.get_public_listing_page', side_effect=RuntimeError('database unavailable')):
            response = self.client.get('/materials/list?q=角材&area=和泊町')
        self.assertEqual(response.status_code, 503)
        self.assertIn('再読み込みする', response.get_data(as_text=True))
        self.assertNotIn('この条件の投稿は見つかりませんでした', response.get_data(as_text=True))

    def test_notification_links_to_matching_history(self):
        _, match = self.create_match()
        with self.app.app_context(), db._engine().connect() as conn:
            message = conn.execute(select(db.notification_outbox.c.message)).scalar()
        self.assertIn(f'match={match}', message)
        self.assertIn('tab=matches', message)

    def test_owner_can_complete_and_close_atomically(self):
        entry, match = self.create_match()
        with self.app.app_context():
            changed = db.update_matching_status(match, 'material', 'owner', '成立', '未対応', 'close')
            self.assertEqual(changed['status'], '成立')
            self.assertEqual(db.get_material_by_id(entry)['effective_status'], 'closed')
            with db._engine().connect() as conn:
                self.assertEqual(len(conn.execute(select(db.operations).where(db.operations.c.kind == 'match_status')).all()), 1)

    def test_counterparty_cannot_close_post_and_stale_updates_do_not_notify(self):
        entry, match = self.create_match()
        with self.app.app_context():
            self.assertIsNone(db.update_matching_status(match, 'material', 'visitor', '成立', '未対応', 'close'))
            db.update_matching_status(match, 'material', 'owner', '連絡・調整中', '未対応')
            self.assertIsNone(db.update_matching_status(match, 'material', 'visitor', '辞退', '未対応'))
            self.assertEqual(db.get_matching_history_by_id(match)[1]['status'], '連絡・調整中')
            self.assertEqual(db.get_material_by_id(entry)['effective_status'], 'active')
            with db._engine().connect() as conn:
                self.assertEqual(len(conn.execute(select(db.notification_outbox)).all()), 2)

    def test_partial_upload_failure_leaves_recoverable_jobs(self):
        def upload(file, public_id, **kwargs):
            if file.filename == 'second.png':
                raise RuntimeError('upload failed')
            return {'secure_url': f'https://res.cloudinary.com/demo/image/upload/{public_id}.png'}
        with self.app.test_request_context('/'), patch('cloudinary.uploader.upload', side_effect=upload), patch('cloudinary.uploader.destroy', return_value={'result': 'ok'}) as destroy:
            files = [FileStorage(stream=BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 24), filename=name) for name in ('first.png', 'second.png')]
            with self.assertRaises(RuntimeError):
                _upload_images(files)
            with db._engine().connect() as conn:
                ids = conn.execute(select(db.image_upload_jobs.c.public_id)).scalars().all()
            self.assertEqual(len(ids), 2)
            self.assertEqual(clean_upload_jobs(ids), 2)
            self.assertEqual(destroy.call_count, 2)

    def test_upload_cleanup_preserves_referenced_images_and_retries_failure(self):
        public_id = 'erabu-zai-spot/uploads/retained'
        with self.app.app_context(), patch.dict(os.environ, {'CLOUDINARY_CLOUD_NAME': 'demo'}), patch('cloudinary.uploader.destroy', return_value={'result': 'error'}) as destroy:
            with db._engine().begin() as conn:
                conn.execute(db.image_upload_jobs.insert().values(public_id=public_id, created_at=1))
                conn.execute(db.image_upload_jobs.insert().values(public_id='orphan', created_at=1))
            db.append_material({'line_user_id': 'owner', 'image_url': f'https://res.cloudinary.com/demo/image/upload/{public_id}.png'})
            self.assertEqual(clean_upload_jobs(), 1)
            destroy.assert_called_once_with('orphan', resource_type='image', invalidate=True)
            with db._engine().connect() as conn:
                self.assertEqual(conn.execute(select(db.image_upload_jobs.c.public_id)).scalars().all(), ['orphan'])

    def test_admin_auth_pagination_audit_and_demolition_close(self):
        self.app.config['ADMIN_LINE_USER_ID'] = 'admin'
        self.assertEqual(self.client.get('/admin/').status_code, 401)
        self.authenticate('admin')
        with self.app.app_context():
            for i in range(26):
                db.append_material({'line_user_id': 'owner', 'title': f'材{i}'})
            building = db.append_demolition_property({'line_user_id': 'owner', 'property_name': '閉じる物件'})
            self.assertTrue(change_post_status('demolition', building, '受付終了', 'admin'))
        page = self.client.get('/admin/')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertIn('次へ', page.get_data(as_text=True))
        self.assertNotIn('閉じる物件', self.client.get('/materials/list').get_data(as_text=True))
        self.assertIn('受付を終了', self.client.get(f'/materials/demolitions/{building}').get_data(as_text=True))

    def test_report_and_job_heartbeat_are_visible_to_admin(self):
        entry, _ = self.create_match()
        self.authenticate('visitor')
        self.post_form(f'/materials/report/material/{entry}', {'reason': '個人情報が公開されている'})
        with self.app.app_context(), patch('app.services.notification_service.send_line_message', return_value=True):
            drain_notifications()
        self.app.config['ADMIN_LINE_USER_ID'] = 'admin'
        self.authenticate('admin')
        response = self.client.get('/admin/')
        self.assertIn('個人情報が公開されている', response.get_data(as_text=True))
        self.assertNotIn('5分以上', response.get_data(as_text=True))

    def test_operational_migration_is_repeatable_and_retains_existing_data(self):
        engine = create_engine('sqlite://')
        try:
            migrate(engine)
            migrate(engine)
            self.assertEqual(set(inspect(engine).get_table_names()), {'operations', 'image_upload_jobs'})
            with engine.connect() as conn:
                self.assertEqual(len(conn.execute(select(db.operations)).all()), 1)
        finally:
            engine.dispose()

    def test_same_status_after_intervening_changes_is_still_stale(self):
        _, match = self.create_match()
        with self.app.app_context():
            original = db.get_matching_history_by_id(match)[1]
            db.update_matching_status(match, 'material', 'owner', '連絡・調整中')
            db.update_matching_status(match, 'material', 'owner', '未対応')
            self.assertIsNone(db.update_matching_status(match, 'material', 'visitor', '成立',
                expected_status='未対応', expected_updated_at=original['updated_at']))


if __name__ == '__main__':
    unittest.main()
