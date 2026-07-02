# Supabase migration

## 1. Create a Supabase database

Create a Supabase project, then copy the Postgres connection string from the database settings.

Use the session pooler connection string for deployed Flask apps when possible.

## 2. Add environment variables

Add these values to `.env` locally and to the deployment environment:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres
DATABASE_SSLMODE=require
AUTO_CREATE_TABLES=true
```

The app converts `postgresql://` to the SQLAlchemy `postgresql+psycopg://` driver internally.

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Create tables

Tables are created automatically when the Flask app starts while `AUTO_CREATE_TABLES=true`.

To avoid automatic schema changes in production later, set:

```env
AUTO_CREATE_TABLES=false
```

after the initial tables exist.

## 5. Copy existing Google Sheets data

Keep the existing Google Sheets environment variables available, then run:

```bash
python scripts/migrate_sheets_to_db.py
```

The script upserts existing rows into Supabase and preserves IDs such as `material_id`, `property_id`, and `match_id`.
