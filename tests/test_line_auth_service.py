import json
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from app.services.line_auth_service import LineAuthError, extract_id_token, verify_id_token


class LineAuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(LINE_CHANNEL_ID="channel", LIFF_DEBUG_LOGGING=True)

    def test_timeout_is_handled_without_logging_credentials(self):
        with self.app.test_request_context(headers={"X-LIFF-Trace-ID": "trace-123"}):
            with patch("app.services.line_auth_service.urlopen", side_effect=TimeoutError("secret-token")):
                with self.assertLogs(self.app.logger, level="WARNING") as logs:
                    with self.assertRaises(LineAuthError):
                        verify_id_token("secret-token")
            output = " ".join(logs.output)
            self.assertIn("verification_unavailable", output)
            self.assertIn("trace=trace-123", output)
            self.assertNotIn("secret-token", output)

    def test_invalid_claims_and_subject_mismatch_are_rejected(self):
        for claims in ([], None, {"sub": 123}, {"sub": " "}, {"sub": "other"}):
            with self.subTest(claims=claims), self.app.app_context():
                response = MagicMock()
                response.__enter__.return_value.read.return_value = json.dumps(claims).encode()
                with patch("app.services.line_auth_service.urlopen", return_value=response):
                    with self.assertRaises(LineAuthError):
                        verify_id_token("token", expected_user_id="expected")

    def test_success_logs_metadata_only(self):
        with self.app.test_request_context(headers={"X-LIFF-Trace-ID": "trace-ok"}):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"sub":"private-user"}'
            with patch("app.services.line_auth_service.urlopen", return_value=response):
                with self.assertLogs(self.app.logger, level="INFO") as logs:
                    self.assertEqual(verify_id_token("secret-token")["sub"], "private-user")
            output = " ".join(logs.output)
            self.assertIn("verification_succeeded", output)
            self.assertNotIn("private-user", output)
            self.assertNotIn("secret-token", output)

    def test_invalid_json_token_input_is_handled(self):
        for payload in ([1], {"idToken": 123}, {"idToken": ["token"]}):
            with self.subTest(payload=payload), self.app.test_request_context(json=payload):
                with self.assertRaises(LineAuthError):
                    extract_id_token()
