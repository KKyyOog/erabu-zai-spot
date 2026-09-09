"""Shared, bounded rate limits for SQLite and PostgreSQL workers."""
import hashlib
import time

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.services.db_service import _engine, request_buckets


def allow_request(scope, principal, limit, seconds):
    now = int(time.time())
    window = now // seconds
    key = hashlib.sha256(f"{scope}:{principal}:{window}".encode()).hexdigest()
    engine = _engine()
    insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    stmt = insert(request_buckets).values(
        bucket_key=key, count=1, expires_at=(window + 1) * seconds,
    ).on_conflict_do_update(
        index_elements=[request_buckets.c.bucket_key],
        set_={"count": request_buckets.c.count + 1},
        where=request_buckets.c.count < limit,
    )
    with engine.begin() as conn:
        conn.execute(delete(request_buckets).where(request_buckets.c.expires_at <= now))
        return conn.execute(stmt).rowcount == 1
