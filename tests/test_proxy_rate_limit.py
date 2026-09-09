import unittest
from unittest.mock import patch
from app import create_app
from app.config import Config
import test_workflows as fixtures


class ProxyRateLimitTestCase(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.WorkflowTestCase.setUpClass())

    def exercise(self, hops, check):
        with patch.object(Config, 'TRUSTED_PROXY_HOPS', hops):
            app = create_app()
        app.config.update(TESTING=True)
        app.view_functions['link.liff_link'] = lambda: ('ok', 200)
        try:
            with patch('app.services.rate_limit_service.time.time', return_value=125):
                check(app.test_client())
        finally:
            app.extensions['database_engine'].dispose()

    def test_render_clients_do_not_share_the_loopback_quota(self):
        def check(client):
            first = {'X-Forwarded-For': '198.51.100.1'}
            for _ in range(30):
                self.assertEqual(client.post('/link/liff', headers=first).status_code, 200)
            blocked = client.post('/link/liff', headers=first)
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.get_json()['code'], 'rate_limited')
            self.assertEqual(blocked.headers['Retry-After'], '55')
            self.assertEqual(blocked.get_json()['retry_after'], 55)
            self.assertEqual(client.post('/link/liff', headers={'X-Forwarded-For': '198.51.100.2'}).status_code, 200)
        self.exercise(1, check)

    def test_spoofed_leftmost_address_cannot_reset_the_limit(self):
        def check(client):
            for index in range(30):
                self.assertEqual(client.post('/link/liff', headers={
                    'X-Forwarded-For': f'203.0.113.{index + 1}, 198.51.100.1'
                }).status_code, 200)
            self.assertEqual(client.post('/link/liff', headers={
                'X-Forwarded-For': '203.0.113.200, 198.51.100.1'
            }).status_code, 429)
        self.exercise(1, check)

    def test_direct_deployment_does_not_trust_forwarded_headers(self):
        def check(client):
            for index in range(30):
                self.assertEqual(client.post('/link/liff', headers={'X-Forwarded-For': f'198.51.100.{index + 1}'}).status_code, 200)
            self.assertEqual(client.post('/link/liff', headers={'X-Forwarded-For': '198.51.100.100'}).status_code, 429)
        self.exercise(0, check)

    def test_missing_header_remains_limited(self):
        def check(client):
            for _ in range(30):
                self.assertEqual(client.post('/link/liff').status_code, 200)
            self.assertEqual(client.post('/link/liff').status_code, 429)
        self.exercise(1, check)
