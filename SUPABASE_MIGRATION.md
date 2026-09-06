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

When automatic table creation is disabled, the app still creates the
`line_notification_links` and `line_notification_link_codes` tables when
missing. These tables are required by the guest LINE notification-linking
flow and are created with SQLAlchemy's `checkfirst` protection.

## 5. Copy existing Google Sheets data

Keep the existing Google Sheets environment variables available, then run:

```bash
python scripts/migrate_sheets_to_db.py
```

The script upserts existing rows into Supabase and preserves IDs such as `material_id`, `property_id`, and `match_id`.

## 6. Upgrade an existing database to offer/request posts

Before deploying the offer/request version of the app, run:

```bash
python scripts/migrate_posts_v2.py
```

The idempotent migration adds `post_type`, `quantity_level`, `usage_purpose`,
and `expires_at` to `materials`. It also adds the optional `business_name`,
`user_category`, and `area` profile fields to `users`.

Existing material rows are treated as `offer` posts. Their `expires_at` value
stays empty, so the upgrade does not hide existing posts. New posts receive a
30-day expiry in the application.

`metadata.create_all()` does not add columns to an existing table. Run this
migration before deploying the updated application even when
`AUTO_CREATE_TABLES=true`.
