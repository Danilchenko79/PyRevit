// In-memory stand-ins for the Cloudflare bindings, enough for the worker:
// R2 bucket (get / put / delete) and D1 (prepare / bind / first / run / all) on node:sqlite.
import { DatabaseSync } from 'node:sqlite';
import { createHash } from 'node:crypto';
import { readFileSync, mkdirSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

async function toBytes(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (typeof value === 'string') return new TextEncoder().encode(value);
  if (value && typeof value.getReader === 'function') {            // a request body (stream)
    return new Uint8Array(await new Response(value).arrayBuffer());
  }
  throw new Error('mock R2: unsupported value');
}

function r2Object(key, bytes, httpMetadata, customMetadata) {
  const etag = createHash('md5').update(bytes).digest('hex');      // like R2: md5 of the body
  return {
    key, size: bytes.length, httpMetadata: httpMetadata || {}, customMetadata: customMetadata || {},
    etag, httpEtag: `"${etag}"`,
    get body() { return new Blob([bytes]).stream(); },
    async text() { return new TextDecoder().decode(bytes); },
    async json() { return JSON.parse(new TextDecoder().decode(bytes)); },
    async arrayBuffer() { return bytes.slice().buffer; },
  };
}

/** R2 bucket in memory, or on disk when `folder` is given (dev server). */
export class MockBucket {
  constructor(folder) { this.folder = folder; this.mem = new Map(); this.meta = new Map(); this.custom = new Map(); }
  _path(key) { return join(this.folder, ...key.split('/')); }
  async get(key) {
    if (this.folder) {
      const p = this._path(key);
      return existsSync(p) ? r2Object(key, new Uint8Array(readFileSync(p)), this.meta.get(key), this._custom(key)) : null;
    }
    return this.mem.has(key) ? r2Object(key, this.mem.get(key), this.meta.get(key), this.custom.get(key)) : null;
  }
  async head(key) { return this.get(key); }
  // on disk (dev server) the custom metadata survives a restart in a side file
  _custom(key) {
    if (this.custom.has(key)) return this.custom.get(key);
    const p = this._path(key) + '.meta.json';
    return existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : {};
  }
  async put(key, value, opts) {
    const bytes = await toBytes(value);
    if (opts && opts.sha1 && createHash('sha1').update(bytes).digest('hex') !== String(opts.sha1).toLowerCase()) {
      throw new Error('mock R2: sha1 checksum mismatch');      // R2 refuses the upload the same way
    }
    if (this.folder) { const p = this._path(key); mkdirSync(dirname(p), { recursive: true }); writeFileSync(p, bytes); }
    else this.mem.set(key, bytes);
    this.meta.set(key, (opts && opts.httpMetadata) || {});
    const custom = (opts && opts.customMetadata) || {};
    this.custom.set(key, custom);
    if (this.folder && Object.keys(custom).length) writeFileSync(this._path(key) + '.meta.json', JSON.stringify(custom));
    return r2Object(key, bytes, null, custom);
  }
  async delete(keys) {
    for (const k of Array.isArray(keys) ? keys : [keys]) {
      if (this.folder) { const p = this._path(k); if (existsSync(p)) rmSync(p); } else this.mem.delete(k);
    }
  }
  keys() { return [...this.mem.keys()].sort(); }
}

class Stmt {
  constructor(db, sql) { this.db = db; this.sql = sql; this.args = []; }
  bind(...args) { this.args = args; return this; }
  async first() { return this.db.prepare(this.sql).get(...this.args) || null; }
  async run() { const r = this.db.prepare(this.sql).run(...this.args); return { success: true, meta: { changes: Number(r.changes) } }; }
  async all() { return { success: true, results: this.db.prepare(this.sql).all(...this.args) }; }
}

/** D1 database on node:sqlite (file or :memory:) with the service schema. */
export class MockD1 {
  constructor(file = ':memory:') {
    this.db = new DatabaseSync(file);
    this.db.exec(readFileSync(join(HERE, '..', 'schema.sql'), 'utf8'));
  }
  prepare(sql) { return new Stmt(this.db, sql); }
}

export async function sha256hex(text) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/** Put a key straight into the table (like the first admin key at deploy). */
export async function seedKey(d1, { id, key, name, role }) {
  await d1.prepare('INSERT INTO keys (id, hash, name, role, active, created) VALUES (?, ?, ?, ?, 1, ?)')
    .bind(id, await sha256hex(key), name, role, new Date().toISOString().slice(0, 19)).run();
}
