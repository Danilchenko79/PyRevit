-- PEER Library access service (Cloudflare D1). Apply once:
--   npx wrangler d1 execute peer-library --remote --file=schema.sql

CREATE TABLE IF NOT EXISTS keys (
    id         TEXT PRIMARY KEY,          -- short public id, used to revoke
    hash       TEXT NOT NULL UNIQUE,      -- SHA-256 of the key; the key itself is never stored
    name       TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    active     INTEGER NOT NULL DEFAULT 1,
    created    TEXT NOT NULL,
    created_by TEXT,
    last_used  TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    id          TEXT PRIMARY KEY,         -- also the folder in R2: PEER-Inbox/<id>/
    author      TEXT NOT NULL,
    author_key  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    sent        TEXT NOT NULL,
    data        TEXT NOT NULL,            -- JSON: name, group, kind, reason, checks, ...
    comment     TEXT NOT NULL DEFAULT '',
    resolved_by TEXT NOT NULL DEFAULT '',
    resolved    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    time    TEXT NOT NULL,
    key_id  TEXT,
    name    TEXT,
    action  TEXT NOT NULL,                -- download / publish / deprecate / propose / reject / key_add / key_revoke
    target  TEXT,
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS audit_time ON audit(time);

-- "Request access" from the sign-in window: no key yet. The key is created only
-- when the requester picks up an approved request (never stored in plain text).
CREATE TABLE IF NOT EXISTS access_requests (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created     TEXT NOT NULL,
    token_hash  TEXT NOT NULL,            -- SHA-256 of the secret the requester polls with
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending / approved / rejected / delivered
    role        TEXT NOT NULL DEFAULT 'user',
    resolved_by TEXT NOT NULL DEFAULT '',
    resolved    TEXT NOT NULL DEFAULT '',
    key_id      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS locks (
    name    TEXT PRIMARY KEY,
    owner   TEXT,
    expires TEXT NOT NULL
);
