-- Existing database (created before 20.11.2026): run ONCE, BEFORE deploying the worker that reads it.
--   npx wrangler d1 execute peer-library --remote --file=migrations/001_key_version.sql
ALTER TABLE keys ADD COLUMN version TEXT NOT NULL DEFAULT '';
