"""Create the operational tables before release; safe to run repeatedly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from app.services.db_service import metadata, operations, image_upload_jobs
from scripts.migrate_posts_v2 import database_url


def migrate(engine):
    import time
    with engine.begin() as conn:
        metadata.create_all(conn, tables=[operations, image_upload_jobs], checkfirst=True)
        for index in operations.indexes:
            index.create(conn, checkfirst=True)
        revision = 'schema-20260909-operations'
        if not conn.execute(select(operations.c.event_id).where(operations.c.event_id == revision)).scalar():
            conn.execute(operations.insert().values(event_id=revision, kind='schema_migration',
                subject_id='20260909-operations', actor_id='', detail='Operational tables created', created_at=int(time.time())))


if __name__ == '__main__':
    load_dotenv()
    engine = create_engine(database_url(), pool_pre_ping=True, future=True)
    try:
        migrate(engine)
        print('operations migration complete')
    finally:
        engine.dispose()
