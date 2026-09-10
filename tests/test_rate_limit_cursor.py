"""Exercise drivers that discard rowcount when SQLAlchemy closes a cursor."""
import sqlite3
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from app.services.db_service import request_buckets
from app.services.rate_limit_service import allow_request


class ClosingCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    @property
    def rowcount(self):
        # psycopg resets its rowcount to -1 when the cursor closes.
        return -1 if self.closed else self.cursor.rowcount

    def close(self):
        self.closed = True
        self.cursor.close()


class ClosingConnection:
    def __init__(self):
        self.connection = sqlite3.connect(':memory:')

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def cursor(self, *args, **kwargs):
        return ClosingCursor(self.connection.cursor(*args, **kwargs))


class RateLimitCursorTestCase(unittest.TestCase):
    def test_successful_insert_is_not_confused_with_exhausted_quota(self):
        engine = create_engine('sqlite://', creator=ClosingConnection)
        try:
            request_buckets.create(engine)
            with patch('app.services.rate_limit_service._engine', return_value=engine), patch('app.services.rate_limit_service.time.time', return_value=120):
                self.assertTrue(allow_request('login', 'client', 2, 60))
                self.assertTrue(allow_request('login', 'client', 2, 60))
                self.assertFalse(allow_request('login', 'client', 2, 60))
                self.assertTrue(allow_request('login', 'other-client', 2, 60))
            with patch('app.services.rate_limit_service._engine', return_value=engine), patch('app.services.rate_limit_service.time.time', return_value=180):
                self.assertTrue(allow_request('login', 'client', 2, 60))
        finally:
            engine.dispose()
