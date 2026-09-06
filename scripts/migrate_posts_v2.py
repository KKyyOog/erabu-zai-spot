"""Add lightweight offer/request fields to an existing materials table.

Run this once against the deployment database before deploying code that uses
the new columns. The migration is idempotent and keeps legacy posts active as
offers without assigning them an expiry date.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


NEW_COLUMNS = {
    "post_type": "VARCHAR(16) NOT NULL DEFAULT 'offer'",
    "quantity_level": "VARCHAR(64) NOT NULL DEFAULT ''",
    "usage_purpose": "VARCHAR(100) NOT NULL DEFAULT ''",
    "expires_at": "VARCHAR(32) NOT NULL DEFAULT ''",
}

NEW_USER_COLUMNS = {
    "business_name": "TEXT NOT NULL DEFAULT ''",
    "user_category": "VARCHAR(100) NOT NULL DEFAULT ''",
    "area": "VARCHAR(100) NOT NULL DEFAULT ''",
}


def database_url():
    value = os.getenv("DATABASE_URL", "sqlite:///erabu_zai_spot.db")
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://") :]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]

    sslmode = os.getenv("DATABASE_SSLMODE", "require")
    if value.startswith("postgresql+psycopg://") and sslmode and "sslmode=" not in value:
        separator = "&" if "?" in value else "?"
        value = f"{value}{separator}sslmode={sslmode}"
    return value


def migrate(engine):
    table_names = set(inspect(engine).get_table_names())
    missing_tables = {"materials", "users"} - table_names
    if missing_tables:
        raise RuntimeError(
            f"required tables do not exist: {', '.join(sorted(missing_tables))}"
        )

    existing_columns = {
        column["name"] for column in inspect(engine).get_columns("materials")
    }
    existing_user_columns = {
        column["name"] for column in inspect(engine).get_columns("users")
    }
    added = []
    with engine.begin() as connection:
        for name, definition in NEW_COLUMNS.items():
            if name not in existing_columns:
                connection.execute(
                    text(f"ALTER TABLE materials ADD COLUMN {name} {definition}")
                )
                added.append(f"materials.{name}")

        for name, definition in NEW_USER_COLUMNS.items():
            if name not in existing_user_columns:
                connection.execute(
                    text(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                )
                added.append(f"users.{name}")

        connection.execute(
            text(
                "UPDATE materials SET post_type = 'offer' "
                "WHERE post_type IS NULL OR post_type = ''"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_materials_post_type "
                "ON materials (post_type)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_materials_expires_at "
                "ON materials (expires_at)"
            )
        )
    return added


def main():
    load_dotenv()
    engine = create_engine(database_url(), pool_pre_ping=True, future=True)
    try:
        for column_name in migrate(engine):
            print(f"added {column_name}")
        print("posts v2 migration complete")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
