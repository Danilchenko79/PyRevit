// PEER Library access service - Cloudflare Worker.
//
// Files live in R2 (binding BUCKET), keys / proposals / audit in D1 (binding DB).
// Every request except GET / carries "Authorization: Bearer peer_..."; the role
// of the key is checked here, never in the plugin.
//
//   GET    /auth                 name and role of the key            any key
//   GET    /index                index.json                          any key
//   GET    /changelog            changelog.json                      any key
//   GET    /file/<path>          .rfa / .png / .txt                  any key
//   POST   /inbox                send a proposal (multipart)         any key
//   GET    /inbox/mine           own proposals                       any key
//   GET    /inbox[?done=1]       all proposals                       admin
//   GET    /inbox/<id>/<file>    family.rfa / screenshot.png         admin or author
//   POST   /reject               {id, comment}                       admin
//   POST   /publish              card + files (multipart)            admin
//   POST   /deprecate            {id, note}                          admin
//   GET    /keys                 list keys                           admin
//   POST   /keys                 {name, role} -> key shown once      admin
//   DELETE /keys/<id>            revoke                              admin
//   GET    /audit?limit=N        last actions                        admin
//   POST   /card                 {id, fields} info w/o new version   admin
//   GET    /collections          kits of families                    any key
//   PUT    /collections          {collections: [...]}                admin
//   GET    /stats?days=90        downloads per family                any key
//   POST   /resolve              {id, status, comment} request/issue admin
//   POST   /access/request       {name, note} -> {id, token}         no key (sign-in window)
//   POST   /access/status        {id, token} -> status / key once    no key
//   GET    /access               waiting access requests             admin
//   POST   /access/approve       {id, role}                          admin
//   POST   /access/reject        {id}                                admin
//
// Publishing is all-or-nothing: new files go to new version keys
// (<group>/<ID>/v<N>.rfa), index.json is written last (the commit point),
// old version files are deleted after that.

const LIB = 'PEER-Library/';
const INBOX = 'PEER-Inbox/';
const MAX_FILE = 25 * 1024 * 1024;
const LOCK_SECONDS = 120;
const CHANGELOG_KEEP = 1000;
const LAST_USED_EVERY_MS = 60 * 60 * 1000;
const GROUPS = ['01_Framing', '02_Foundations', '03_Rebar_2D', '04_Rebar_3D_Embeds', '05_Details',
                '06_Tags', '07_Sheets', '08_Steel', '09_Openings'];
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9 _\-.()+,&]*$/;
const CARD_FIELDS = ['id', 'name', 'group', 'revit_category', 'tags', 'revit', 'description',
                     'help_url', 'types'];

export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
});
const nowIso = () => new Date().toISOString().slice(0, 19);
const today = () => new Date().toISOString().slice(0, 10);

async function digestHex(algo, data) {
  const buf = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  const h = await crypto.subtle.digest(algo, buf);
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function randomToken(bytes) {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  let s = '';
  for (const b of a) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// ---- auth -------------------------------------------------------------------
async function authenticate(request, env) {
  const h = (request.headers.get('authorization') || '').trim();
  const m = /^Bearer\s+(peer_[A-Za-z0-9_-]{20,})$/.exec(h);
  if (!m) throw new HttpError(401, 'No library key - sign in with your PEER key.');
  const row = await env.DB.prepare('SELECT id, name, role, active, last_used FROM keys WHERE hash = ?')
    .bind(await digestHex('SHA-256', m[1])).first();
  if (!row || !row.active) throw new HttpError(401, 'This library key is not valid any more - ask an admin.');
  const now = Date.now();
  if (!row.last_used || now - Date.parse(row.last_used + 'Z') > LAST_USED_EVERY_MS) {
    await env.DB.prepare('UPDATE keys SET last_used = ? WHERE id = ?').bind(nowIso(), row.id).run();
  }
  return row;
}

function needAdmin(who) {
  if (who.role !== 'admin') throw new HttpError(403, 'Only library admins can do this.');
}

async function audit(env, who, action, target, detail) {
  await env.DB.prepare('INSERT INTO audit (time, key_id, name, action, target, detail) VALUES (?, ?, ?, ?, ?, ?)')
    .bind(nowIso(), who ? who.id : null, who ? who.name : null, action, target || '', detail || '').run();
}

// ---- storage helpers ----------------------------------------------------------
async function readJson(env, key, fallback) {
  const obj = await env.BUCKET.get(key);
  if (!obj) return fallback;
  try { return JSON.parse(await obj.text()); } catch (e) { return fallback; }
}

const putJson = (env, key, data) => env.BUCKET.put(key, JSON.stringify(data, null, 1),
  { httpMetadata: { contentType: 'application/json; charset=utf-8' } });

async function withLock(env, name, owner, fn) {
  const now = nowIso();
  const until = new Date(Date.now() + LOCK_SECONDS * 1000).toISOString().slice(0, 19);
  await env.DB.prepare('DELETE FROM locks WHERE name = ? AND expires < ?').bind(name, now).run();
  const res = await env.DB.prepare('INSERT OR IGNORE INTO locks (name, owner, expires) VALUES (?, ?, ?)')
    .bind(name, owner, until).run();
  if (!res.meta || res.meta.changes !== 1) {
    throw new HttpError(409, 'Another admin is publishing right now - try again in a minute.');
  }
  try {
    return await fn();
  } finally {
    await env.DB.prepare('DELETE FROM locks WHERE name = ? AND owner = ?').bind(name, owner).run();
  }
}

function safePath(rest) {
  const parts = decodeURIComponent(rest).split('/').filter(Boolean);
  if (!parts.length || parts.some(p => p === '.' || p === '..' || p.includes('\\'))) {
    throw new HttpError(400, 'Bad path');
  }
  return parts.join('/');
}

function fileResponse(obj, name) {
  const headers = new Headers();
  headers.set('content-type', (obj.httpMetadata && obj.httpMetadata.contentType) || 'application/octet-stream');
  headers.set('content-length', String(obj.size));
  headers.set('cache-control', 'no-store');
  if (name) headers.set('content-disposition', `attachment; filename="${name.replace(/"/g, '')}"`);
  return new Response(obj.body, { headers });
}

function validateCard(card) {
  const p = [];
  if (!card || typeof card !== 'object') return ['card is missing'];
  if (!card.id || !NAME_RE.test(card.id) || card.id !== card.id.trim() || card.id.endsWith('.') ||
      card.id.length > 80) p.push('bad id');
  if (!GROUPS.includes(card.group)) p.push('unknown group');
  if (!Number.isInteger(card.version) || card.version < 1) p.push('version must be an integer >= 1');
  if (card.tags !== undefined && !Array.isArray(card.tags)) p.push('tags must be a list');
  return p;
}

async function fileOf(form, field, required) {
  const f = form.get(field);
  if (f === null || f === undefined || typeof f === 'string') {
    if (required) throw new HttpError(400, `File "${field}" is missing`);
    return null;
  }
  if (f.size > MAX_FILE) throw new HttpError(413, `File "${field}" is larger than ${MAX_FILE / 1048576} MB`);
  return new Uint8Array(await f.arrayBuffer());
}

function sortFamilies(list) {
  const order = (c) => { const i = GROUPS.indexOf(c.group); return i < 0 ? 99 : i; };
  list.sort((a, b) => (order(a) - order(b)) || a.id.toLowerCase().localeCompare(b.id.toLowerCase()));
  return list;
}

async function writeIndex(env, families) {
  sortFamilies(families);
  await putJson(env, LIB + 'index.json', { format: 1, built: nowIso(), count: families.length, families });
}

async function changelogAdd(env, entry) {
  const log = await readJson(env, LIB + 'changelog.json', { format: 1, entries: [] });
  const entries = (log.entries || []).concat([{ ...entry, time: nowIso() }]).slice(-CHANGELOG_KEEP);
  await putJson(env, LIB + 'changelog.json', { format: 1, entries });
}

// ---- publish ------------------------------------------------------------------
async function publish(request, env, who) {
  needAdmin(who);
  const form = await request.formData();
  let card;
  try { card = JSON.parse(form.get('card') || ''); } catch (e) { throw new HttpError(400, 'card is not JSON'); }
  const problems = validateCard(card);
  if (problems.length) throw new HttpError(400, 'Card is not valid: ' + problems.join('; '));
  const note = String(form.get('note') || '');
  const proposalId = String(form.get('proposal_id') || '');
  const rfa = await fileOf(form, 'rfa', true);
  const png = await fileOf(form, 'png', false);
  const txt = await fileOf(form, 'catalog', false);

  return withLock(env, 'publish', `${who.id}:${randomToken(6)}`, async () => {
    const index = await readJson(env, LIB + 'index.json', { format: 1, families: [] });
    const families = index.families || [];
    const pos = families.findIndex(c => c.id.toLowerCase() === card.id.toLowerCase());
    const cur = pos >= 0 ? families[pos] : null;
    if (cur && cur.id !== card.id) {
      throw new HttpError(409, `"${card.id}" exists as "${cur.id}" - IDs differ only in case.`);
    }
    const expected = (cur ? cur.version : 0) + 1;
    if (card.version !== expected) {
      throw new HttpError(409, `"${card.id}" was published by someone else meanwhile ` +
        `(expected version ${expected}, got ${card.version}). Publish again.`);
    }
    const next = { ...(cur || {}) };
    for (const k of CARD_FIELDS) if (card[k] !== undefined) next[k] = card[k];
    next.name = next.name || next.id;
    next.tags = next.tags || [];
    next.version = expected;
    next.status = 'active';
    next.updated = today();
    next.author = (cur && cur.author) || who.name;
    next.sha1 = await digestHex('SHA-1', rfa);
    next.size = rfa.length;
    next.png_sha1 = png ? await digestHex('SHA-1', png) : '';
    next.catalog_sha1 = txt ? await digestHex('SHA-1', txt) : '';
    next.type_catalog = !!txt;
    next.history = (cur && cur.history ? cur.history.slice() : []).concat([{
      v: expected, date: next.updated, note: note || (cur ? '' : 'First version'), by: who.name }]);

    const base = `${next.group}/${next.id}/v${expected}`;
    const files = { '.rfa': base + '.rfa' };
    await env.BUCKET.put(LIB + files['.rfa'], rfa, { httpMetadata: { contentType: 'application/octet-stream' } });
    if (png) {
      files['.png'] = base + '.png';
      await env.BUCKET.put(LIB + files['.png'], png, { httpMetadata: { contentType: 'image/png' } });
    }
    if (txt) {
      files['.txt'] = base + '.txt';
      await env.BUCKET.put(LIB + files['.txt'], txt, { httpMetadata: { contentType: 'text/plain' } });
    }
    next.files = files;
    await putJson(env, LIB + `${next.group}/${next.id}/card.json`, next);

    if (pos >= 0) families[pos] = next; else families.push(next);
    await writeIndex(env, families);                       // commit point

    const stale = [];
    if (cur && cur.files) for (const p of Object.values(cur.files)) if (!Object.values(files).includes(p)) stale.push(LIB + p);
    if (cur && cur.group !== next.group) stale.push(LIB + `${cur.group}/${cur.id}/card.json`);
    if (stale.length) await env.BUCKET.delete(stale);

    await changelogAdd(env, { id: next.id, name: next.name, group: next.group, version: next.version,
      action: cur ? 'updated' : 'added', note, by: who.name, date: next.updated });
    if (proposalId) {
      try {   // the family is already published; a resolved proposal is not an error
        await resolveProposal(env, who, proposalId, 'accepted', `Published as ${next.id} v${next.version}`);
      } catch (e) { console.error('proposal', proposalId, e && e.message); }
    }
    await audit(env, who, 'publish', next.id, `v${next.version}`);
    return json(next);
  });
}

async function deprecate(request, env, who) {
  needAdmin(who);
  const body = await request.json().catch(() => ({}));
  return withLock(env, 'publish', `${who.id}:${randomToken(6)}`, async () => {
    const index = await readJson(env, LIB + 'index.json', { format: 1, families: [] });
    const fam = (index.families || []).find(c => c.id.toLowerCase() === String(body.id || '').toLowerCase());
    if (!fam) throw new HttpError(404, 'Not in the library: ' + body.id);
    if (fam.status !== 'deprecated') {
      fam.status = 'deprecated';
      fam.history = (fam.history || []).concat([{ v: fam.version, date: today(), note: body.note || 'Deprecated', by: who.name }]);
      await putJson(env, LIB + `${fam.group}/${fam.id}/card.json`, fam);
      await writeIndex(env, index.families);
      await changelogAdd(env, { id: fam.id, name: fam.name, group: fam.group, version: fam.version,
        action: 'deprecated', note: body.note || '', by: who.name, date: today() });
      await audit(env, who, 'deprecate', fam.id, body.note || '');
    }
    return json(fam);
  });
}

// ---- card info without a new version (admin) --------------------------------------
const INFO_FIELDS = ['name', 'tags', 'description', 'help_url', 'group', 'types', 'revit_category'];

async function updateCardInfo(request, env, who) {
  needAdmin(who);
  const body = await request.json().catch(() => ({}));
  const changes = body.fields || {};
  return withLock(env, 'publish', `${who.id}:${randomToken(6)}`, async () => {
    const index = await readJson(env, LIB + 'index.json', { format: 1, families: [] });
    const fam = (index.families || []).find(c => c.id === String(body.id || ''));
    if (!fam) throw new HttpError(404, 'Not in the library: ' + body.id);
    for (const k of INFO_FIELDS) {
      if (changes[k] === undefined) continue;
      if (k === 'group' && !GROUPS.includes(changes[k])) throw new HttpError(400, 'unknown group');
      if ((k === 'tags' || k === 'types') && !Array.isArray(changes[k])) throw new HttpError(400, k + ' must be a list');
      fam[k] = k === 'types' ? changes[k].slice(0, 2000).map(String) : changes[k];
    }
    fam.info_updated = nowIso();
    await putJson(env, LIB + `${fam.group}/${fam.id}/card.json`, fam);
    await writeIndex(env, index.families);
    await audit(env, who, 'card_info', fam.id, Object.keys(changes).join(','));
    return json(fam);
  });
}

// ---- collections (kits) ----------------------------------------------------------
async function putCollections(request, env, who) {
  needAdmin(who);
  const body = await request.json().catch(() => null);
  const list = body && Array.isArray(body.collections) ? body.collections : null;
  if (!list) throw new HttpError(400, 'collections must be a list');
  const out = [];
  const seen = new Set();
  for (const c of list.slice(0, 200)) {
    const name = String(c.name || '').trim().slice(0, 80);
    if (!name) continue;
    const id = String(c.id || name).replace(/[^A-Za-z0-9_-]+/g, '-').slice(0, 60) || randomToken(6);
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({ id, name, description: String(c.description || '').slice(0, 500),
               families: (Array.isArray(c.families) ? c.families : []).slice(0, 500).map(String),
               updated: nowIso(), by: who.name });
  }
  await putJson(env, LIB + 'collections.json', { format: 1, collections: out });
  await audit(env, who, 'collections', '', String(out.length));
  return json({ format: 1, collections: out });
}

// ---- popularity --------------------------------------------------------------------
function familyOfPath(p) {
  const parts = String(p || '').split('/');
  if (parts.length >= 3) return parts[1];                       // <group>/<ID>/v<N>.rfa
  return (parts[parts.length - 1] || '').replace(/\.rfa$/i, '');  // <group>/<ID>.rfa
}

async function stats(env, url) {
  const days = Math.max(1, Math.min(365, parseInt(url.searchParams.get('days') || '90', 10) || 90));
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 19);
  const r = await env.DB.prepare(
    "SELECT target, COUNT(*) AS n, COUNT(DISTINCT key_id) AS u FROM audit WHERE action = 'download' AND time >= ? GROUP BY target")
    .bind(since).all();
  const out = {};
  for (const row of r.results || []) {
    const id = familyOfPath(row.target);
    const cur = out[id] || { downloads: 0, users: 0 };
    cur.downloads += row.n;
    cur.users = Math.max(cur.users, row.u);
    out[id] = cur;
  }
  return json({ days, families: out });
}

// ---- proposals ----------------------------------------------------------------
function proposalOut(row) {
  const data = JSON.parse(row.data || '{}');
  return { ...data, id: row.id, author: row.author, status: row.status, sent: row.sent,
           comment: row.comment, resolved_by: row.resolved_by, resolved: row.resolved,
           done: row.status !== 'pending' };
}

async function sendProposal(request, env, who) {
  const form = await request.formData();
  let meta;
  try { meta = JSON.parse(form.get('meta') || '{}'); } catch (e) { throw new HttpError(400, 'meta is not JSON'); }
  const fileless = meta.kind === 'request' || meta.kind === 'issue';   // "need a family" / "problem with one"
  const rfa = await fileOf(form, 'rfa', !fileless);
  const shot = await fileOf(form, 'screenshot', false);
  const slug = (String(meta.family_id || meta.name || 'family').replace(/[^A-Za-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '').slice(0, 40)) || 'family';
  const user = String(who.name).replace(/[^A-Za-z0-9_-]+/g, '').slice(0, 20) || 'user';
  const stamp = nowIso().replace('T', '_').replace(/:/g, '');
  const id = `${stamp}_${user}_${slug}_${randomToken(3)}`;
  if (rfa) await env.BUCKET.put(INBOX + id + '/family.rfa', rfa);
  if (shot) await env.BUCKET.put(INBOX + id + '/screenshot.png', shot, { httpMetadata: { contentType: 'image/png' } });
  const data = { ...meta, has_screenshot: !!shot, has_file: !!rfa };
  delete data.author; delete data.status; delete data.comment;
  await env.DB.prepare('INSERT INTO proposals (id, author, author_key, status, sent, data) VALUES (?, ?, ?, ?, ?, ?)')
    .bind(id, who.name, who.id, 'pending', nowIso(), JSON.stringify(data)).run();
  await audit(env, who, 'propose', id, meta.name || '');
  return json({ id });
}

async function resolveProposal(env, who, id, status, comment) {
  const res = await env.DB.prepare(
    "UPDATE proposals SET status = ?, comment = ?, resolved_by = ?, resolved = ? WHERE id = ? AND status = 'pending'")
    .bind(status, comment || '', who.name, nowIso(), id).run();
  if (!res.meta || res.meta.changes !== 1) throw new HttpError(404, 'No pending proposal ' + id);
}

// ---- keys -----------------------------------------------------------------------
async function addKey(request, env, who) {
  needAdmin(who);
  const body = await request.json().catch(() => ({}));
  const name = String(body.name || '').trim().slice(0, 60);
  const role = body.role === 'admin' ? 'admin' : 'user';
  if (!name) throw new HttpError(400, 'Name is required');
  const key = 'peer_' + randomToken(32);
  const id = randomToken(6);
  await env.DB.prepare('INSERT INTO keys (id, hash, name, role, active, created, created_by) VALUES (?, ?, ?, ?, 1, ?, ?)')
    .bind(id, await digestHex('SHA-256', key), name, role, nowIso(), who.name).run();
  await audit(env, who, 'key_add', id, `${name} (${role})`);
  return json({ id, name, role, key });
}

async function revokeKey(env, who, id) {
  needAdmin(who);
  if (id === who.id) throw new HttpError(400, 'You cannot revoke your own key.');
  const res = await env.DB.prepare('UPDATE keys SET active = 0 WHERE id = ?').bind(id).run();
  if (!res.meta || res.meta.changes !== 1) throw new HttpError(404, 'No such key');
  await audit(env, who, 'key_revoke', id, '');
  return json({ id, active: false });
}

// ---- access requests (no key yet) ----------------------------------------------------
const MAX_PENDING_REQUESTS = 20;
const REQUEST_DAYS = 14;

async function requestAccess(request, env) {
  const body = await request.json().catch(() => ({}));
  const name = String(body.name || '').trim().slice(0, 60);
  const note = String(body.note || '').trim().slice(0, 300);
  if (name.length < 2) throw new HttpError(400, 'Write your name.');
  const old = new Date(Date.now() - REQUEST_DAYS * 86400000).toISOString().slice(0, 19);
  await env.DB.prepare("DELETE FROM access_requests WHERE status IN ('pending', 'rejected') AND created < ?")
    .bind(old).run();
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM access_requests WHERE status = 'pending'").first();
  if (n && n.n >= MAX_PENDING_REQUESTS) {
    throw new HttpError(429, 'Too many requests are waiting - ask a library admin directly.');
  }
  const id = randomToken(9);
  const token = randomToken(24);
  await env.DB.prepare('INSERT INTO access_requests (id, name, note, created, token_hash) VALUES (?, ?, ?, ?, ?)')
    .bind(id, name, note, nowIso(), await digestHex('SHA-256', token)).run();
  await audit(env, null, 'access_request', id, name);
  return json({ id, token, status: 'pending' });
}

async function accessStatus(request, env) {
  const body = await request.json().catch(() => ({}));
  const row = await env.DB.prepare('SELECT * FROM access_requests WHERE id = ?').bind(String(body.id || '')).first();
  if (!row || row.token_hash !== await digestHex('SHA-256', String(body.token || ''))) {
    throw new HttpError(404, 'No such request - send a new one.');
  }
  if (row.status !== 'approved') return json({ status: row.status, name: row.name });
  // approved: create the key now and hand it over exactly once
  const key = 'peer_' + randomToken(32);
  const keyId = randomToken(6);
  await env.DB.prepare('INSERT INTO keys (id, hash, name, role, active, created, created_by) VALUES (?, ?, ?, ?, 1, ?, ?)')
    .bind(keyId, await digestHex('SHA-256', key), row.name, row.role, nowIso(), row.resolved_by).run();
  const res = await env.DB.prepare("UPDATE access_requests SET status = 'delivered', key_id = ? WHERE id = ? AND status = 'approved'")
    .bind(keyId, row.id).run();
  if (!res.meta || res.meta.changes !== 1) {       // picked up twice at the same moment
    await env.DB.prepare('DELETE FROM keys WHERE id = ?').bind(keyId).run();
    throw new HttpError(409, 'Already delivered.');
  }
  await audit(env, { id: keyId, name: row.name }, 'key_delivered', keyId, row.role);
  return json({ status: 'delivered', name: row.name, role: row.role, key });
}

async function resolveAccess(request, env, who, approve) {
  needAdmin(who);
  const body = await request.json().catch(() => ({}));
  const role = body.role === 'admin' ? 'admin' : 'user';
  const res = await env.DB.prepare(
    "UPDATE access_requests SET status = ?, role = ?, resolved_by = ?, resolved = ? WHERE id = ? AND status = 'pending'")
    .bind(approve ? 'approved' : 'rejected', role, who.name, nowIso(), String(body.id || '')).run();
  if (!res.meta || res.meta.changes !== 1) throw new HttpError(404, 'No pending request ' + body.id);
  await audit(env, who, approve ? 'access_approve' : 'access_reject', body.id, role);
  return json({ id: body.id, status: approve ? 'approved' : 'rejected' });
}

// ---- router ---------------------------------------------------------------------
async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';
  const method = request.method.toUpperCase();
  if (path === '/' && method === 'GET') return json({ service: 'peer-library', ok: true });
  if (path === '/access/request' && method === 'POST') return requestAccess(request, env);
  if (path === '/access/status' && method === 'POST') return accessStatus(request, env);

  const who = await authenticate(request, env);

  if (method === 'GET' && path === '/access') {
    needAdmin(who);
    const r = await env.DB.prepare(
      "SELECT id, name, note, created, status FROM access_requests WHERE status = 'pending' ORDER BY created").all();
    return json(r.results || []);
  }
  if (method === 'POST' && path === '/access/approve') return resolveAccess(request, env, who, true);
  if (method === 'POST' && path === '/access/reject') return resolveAccess(request, env, who, false);
  let m;

  if (method === 'GET' && path === '/auth') return json({ id: who.id, name: who.name, role: who.role });
  if (method === 'GET' && path === '/index') {
    return json(await readJson(env, LIB + 'index.json', { format: 1, built: '', count: 0, families: [] }));
  }
  if (method === 'GET' && path === '/changelog') {
    return json(await readJson(env, LIB + 'changelog.json', { format: 1, entries: [] }));
  }
  if (method === 'GET' && (m = /^\/file\/(.+)$/.exec(url.pathname))) {
    const p = safePath(m[1]);
    const obj = await env.BUCKET.get(LIB + p);
    if (!obj) throw new HttpError(404, 'Not in the library: ' + p);
    if (p.endsWith('.rfa')) await audit(env, who, 'download', p, '');
    return fileResponse(obj);
  }
  if (method === 'POST' && path === '/publish') return publish(request, env, who);
  if (method === 'POST' && path === '/deprecate') return deprecate(request, env, who);

  if (method === 'POST' && path === '/inbox') return sendProposal(request, env, who);
  if (method === 'GET' && path === '/inbox/mine') {
    const r = await env.DB.prepare('SELECT * FROM proposals WHERE author_key = ? ORDER BY sent DESC').bind(who.id).all();
    return json((r.results || []).map(proposalOut));
  }
  if (method === 'GET' && path === '/inbox') {
    needAdmin(who);
    const done = url.searchParams.get('done') === '1';
    const r = await env.DB.prepare(done ? 'SELECT * FROM proposals ORDER BY sent DESC'
      : "SELECT * FROM proposals WHERE status = 'pending' ORDER BY sent").all();
    return json((r.results || []).map(proposalOut));
  }
  if (method === 'GET' && (m = /^\/inbox\/([^/]+)\/(family\.rfa|screenshot\.png)$/.exec(path))) {
    const row = await env.DB.prepare('SELECT author_key FROM proposals WHERE id = ?').bind(m[1]).first();
    if (!row) throw new HttpError(404, 'No such proposal');
    if (who.role !== 'admin' && row.author_key !== who.id) throw new HttpError(403, 'Not your proposal.');
    const obj = await env.BUCKET.get(INBOX + m[1] + '/' + m[2]);
    if (!obj) throw new HttpError(404, 'No such file');
    return fileResponse(obj, m[2]);
  }
  if (method === 'POST' && path === '/resolve') {          // requests / issues: done or declined
    needAdmin(who);
    const body = await request.json().catch(() => ({}));
    const status = body.status === 'accepted' ? 'accepted' : 'rejected';
    if (status === 'rejected' && !String(body.comment || '').trim()) {
      throw new HttpError(400, 'Write why the proposal is rejected.');
    }
    await resolveProposal(env, who, String(body.id || ''), status, String(body.comment || ''));
    await audit(env, who, 'resolve', body.id, status);
    return json({ id: body.id, status });
  }
  if (method === 'POST' && path === '/card') return updateCardInfo(request, env, who);
  if (method === 'GET' && path === '/collections') {
    return json(await readJson(env, LIB + 'collections.json', { format: 1, collections: [] }));
  }
  if (method === 'PUT' && path === '/collections') return putCollections(request, env, who);
  if (method === 'GET' && path === '/stats') return stats(env, url);
  if (method === 'POST' && path === '/reject') {
    needAdmin(who);
    const body = await request.json().catch(() => ({}));
    if (!String(body.comment || '').trim()) throw new HttpError(400, 'Write why the proposal is rejected.');
    await resolveProposal(env, who, String(body.id || ''), 'rejected', String(body.comment));
    await audit(env, who, 'reject', body.id, body.comment);
    return json({ id: body.id, status: 'rejected' });
  }

  if (method === 'GET' && path === '/keys') {
    needAdmin(who);
    const r = await env.DB.prepare('SELECT id, name, role, active, created, created_by, last_used FROM keys ORDER BY active DESC, name').all();
    return json(r.results || []);
  }
  if (method === 'POST' && path === '/keys') return addKey(request, env, who);
  if (method === 'DELETE' && (m = /^\/keys\/([A-Za-z0-9_-]+)$/.exec(path))) return revokeKey(env, who, m[1]);

  if (method === 'GET' && path === '/audit') {
    needAdmin(who);
    const n = Math.max(1, Math.min(1000, parseInt(url.searchParams.get('limit') || '200', 10) || 200));
    const r = await env.DB.prepare('SELECT * FROM audit ORDER BY id DESC LIMIT ?').bind(n).all();
    return json(r.results || []);
  }
  throw new HttpError(404, 'Unknown address');
}

export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message }, e.status);
      console.error(e && e.stack || e);
      return json({ error: 'Server error' }, 500);
    }
  },
};
