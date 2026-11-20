// PEER Library access service - Cloudflare Worker.
//
// Files live in R2 (binding BUCKET), keys / proposals / audit in D1 (binding DB).
// Every request except GET / carries "Authorization: Bearer peer_..."; the role
// of the key is checked here, never in the plugin.
//
//   GET    /auth                 name and role of the key            any key
//   GET    /index                index.json (ETag; 304 if unchanged) any key
//   GET    /changelog            changelog.json (ETag)               any key
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
//   GET    /boot/manifest, /boot/file/<v>  the PEER loader             no key (public)
//   GET    /release/<p>/manifest           channels + versions (ETag)  any key   p = ext | boot | template
//   GET    /release/<p>/file/<version>     the package / the template  any key
//   PUT    /release/<p>/file/<version>     upload (raw body, x-sha1)   admin
//   POST   /release/<p>/publish            {version, channel, note}    admin
//   POST   /release/<p>/promote            {version, channel}          admin  (beta -> stable, roll back)
//
// Publishing is all-or-nothing: new files go to new version keys
// (<group>/<ID>/v<N>.rfa), index.json is written last (the commit point),
// old version files are deleted after that.

const LIB = 'PEER-Library/';
const INBOX = 'PEER-Inbox/';
const MAX_FILE = 25 * 1024 * 1024;
const LOCK_SECONDS = 120;
const KEEP_VERSIONS = 5;          // files of the last N versions stay (admins can restore them)
const CHANGELOG_KEEP = 1000;
const LAST_USED_EVERY_MS = 60 * 60 * 1000;
const AUDIT_KEEP_DAYS = 400;
const GROUPS = ['01_Framing', '02_Foundations', '03_Rebar_2D', '04_Rebar_3D_Embeds', '05_Details',
                '06_Tags', '07_Sheets', '08_Steel', '09_Openings'];
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9 _\-.()+,&]*$/;
const CARD_FIELDS = ['id', 'name', 'group', 'revit_category', 'tags', 'revit', 'description',
                     'help_url', 'types', 'checks'];

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
  const row = await env.DB.prepare('SELECT id, name, role, active, last_used, version FROM keys WHERE hash = ?')
    .bind(await digestHex('SHA-256', m[1])).first();
  if (!row || !row.active) throw new HttpError(401, 'This library key is not valid any more - ask an admin.');
  const now = Date.now();
  // which PEER this person runs (sent with the key check) - the admin sees who is on which version
  const ver = clientVersion(request);
  if (ver && ver !== (row.version || '')) {
    await env.DB.prepare('UPDATE keys SET version = ?, last_used = ? WHERE id = ?').bind(ver, nowIso(), row.id).run();
    row.version = ver;
  } else if (!row.last_used || now - Date.parse(row.last_used + 'Z') > LAST_USED_EVERY_MS) {
    await env.DB.prepare('UPDATE keys SET last_used = ? WHERE id = ?').bind(nowIso(), row.id).run();
  }
  return row;
}

function clientVersion(request) {
  const v = (request.headers.get('x-peer-version') || '').trim();
  return /^[A-Za-z0-9 ._()-]{1,40}$/.test(v) ? v : '';
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

// A JSON file of the library as stored, with its ETag: a client that already has
// this version (If-None-Match) gets an empty 304 - the window opens without
// downloading the whole index again. (Cloudflare may weaken the tag to W/"...".)
const bareTag = (t) => String(t || '').trim().replace(/^W\//, '');

async function storedJson(request, env, key, fallback) {
  const obj = await env.BUCKET.get(key);
  if (!obj) return json(fallback);
  const etag = obj.httpEtag || (obj.etag ? `"${obj.etag}"` : '');
  const headers = { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' };
  if (etag) headers.etag = etag;
  const asked = (request.headers.get('if-none-match') || '').split(',').map(bareTag);
  if (etag && asked.includes(bareTag(etag))) return new Response(null, { status: 304, headers });
  return new Response(obj.body, { headers });
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
    next.name = String(next.name || next.id).slice(0, 120);
    next.tags = (Array.isArray(next.tags) ? next.tags : []).slice(0, 50).map(t => String(t).slice(0, 60));
    next.types = (Array.isArray(next.types) ? next.types : []).slice(0, 2000).map(String);
    next.description = String(next.description || '').slice(0, 4000);
    next.checks = (Array.isArray(card.checks) ? card.checks : []).slice(0, 20)
      .map(c => ({ code: String((c && c.code) || '').slice(0, 30), text: String((c && c.text) || '').slice(0, 300) }));
    next.version = expected;
    next.status = 'active';
    next.updated = today();
    next.author = (cur && cur.author) || who.name;
    next.sha1 = await digestHex('SHA-1', rfa);
    next.size = rfa.length;
    next.png_sha1 = png ? await digestHex('SHA-1', png) : '';
    next.catalog_sha1 = txt ? await digestHex('SHA-1', txt) : '';
    next.type_catalog = !!txt;
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
    // each history entry keeps the addresses of its files, so an admin can restore
    // one of the last KEEP_VERSIONS versions; older files are deleted
    const history = (cur && cur.history ? cur.history : []).map(h => ({ ...h }));
    const prev = cur ? history.find(h => h.v === cur.version) : null;
    if (prev && !prev.files && cur.files) { prev.files = cur.files; prev.sha1 = cur.sha1; }   // cards from before
    history.push({ v: expected, date: next.updated, note: note || (cur ? '' : 'First version'),
      by: who.name, sha1: next.sha1, files });
    const keep = new Set();
    for (const h of history.slice(-KEEP_VERSIONS)) for (const f of Object.values(h.files || {})) keep.add(f);
    const stale = [];
    for (const h of history.slice(0, -KEEP_VERSIONS)) {
      for (const f of Object.values(h.files || {})) if (!keep.has(f)) stale.push(LIB + f);
      delete h.files;
    }
    if (cur && cur.files) for (const f of Object.values(cur.files)) if (!keep.has(f) && !stale.includes(LIB + f)) stale.push(LIB + f);
    next.history = history;
    await putJson(env, LIB + `${next.group}/${next.id}/card.json`, next);

    if (pos >= 0) families[pos] = next; else families.push(next);
    await writeIndex(env, families);                       // commit point

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
const INFO_FIELDS = ['name', 'tags', 'description', 'help_url', 'group', 'types', 'revit_category', 'companions'];

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
      if (k === 'companions') {            // IDs loaded together with this family (a pile -> its tag)
        if (!Array.isArray(changes[k])) throw new HttpError(400, 'companions must be a list');
        const ids = [...new Set(changes[k].map(x => String(x).trim()).filter(Boolean))].slice(0, 20);
        const bad = ids.filter(x => !NAME_RE.test(x) || x.length > 80 || x.toLowerCase() === fam.id.toLowerCase());
        if (bad.length) throw new HttpError(400, 'Not a family ID: ' + bad.join(', '));
        fam[k] = ids;
        continue;
      }
      if (k === 'types') fam[k] = changes[k].slice(0, 2000).map(String);
      else if (k === 'tags') fam[k] = changes[k].slice(0, 50).map(t => String(t).slice(0, 60));
      else if (k === 'name' && !String(changes[k]).trim()) throw new HttpError(400, 'name is empty');
      else fam[k] = String(changes[k]).slice(0, k === 'description' ? 4000 : 500);
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
  const keepFrom = new Date(Date.now() - AUDIT_KEEP_DAYS * 86400000).toISOString().slice(0, 19);
  await env.DB.prepare('DELETE FROM audit WHERE time < ?').bind(keepFrom).run();   // keep the log small
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

// ---- releases: the PEER package and the project template ---------------------------
// PEER-Releases/<product>/manifest.json  {format, product, channels: {stable, beta}, versions: [...]}
// PEER-Releases/<product>/<version>      the file (zip of the extension / the .rte)
// A version is uploaded once and never changes; a channel is a pointer to a version, so
// "roll back" = point the channel at an older version. Every file needs a key.
const REL = 'PEER-Releases/';
const PRODUCTS = {
  ext: { max: 40 * 1024 * 1024, type: 'application/zip' },
  boot: { max: 10 * 1024 * 1024, type: 'application/zip' },     // the loader: Account + updater, public
  template: { max: 95 * 1024 * 1024, type: 'application/octet-stream' },
};
const CHANNELS = ['stable', 'beta'];
const VERSION_RE = /^[0-9]{1,4}(\.[0-9]{1,4}){0,3}$/;
const SHA1_RE = /^[0-9a-f]{40}$/;

const emptyManifest = (product) => ({ format: 1, product, channels: { stable: '', beta: '' }, versions: [] });

function productOf(name) {
  if (!Object.prototype.hasOwnProperty.call(PRODUCTS, name)) throw new HttpError(404, 'Unknown product');
  return PRODUCTS[name];
}

function versionOf(text) {
  const v = String(text || '');
  if (!VERSION_RE.test(v)) throw new HttpError(400, 'Bad version (digits and dots, like 2026.11.20.1 or 14)');
  return v;
}

async function releaseUpload(request, env, who, product, version) {
  needAdmin(who);
  const spec = productOf(product);
  versionOf(version);
  const sha1 = (request.headers.get('x-sha1') || '').trim().toLowerCase();
  if (!SHA1_RE.test(sha1)) throw new HttpError(400, 'Header x-sha1 (SHA-1 of the file) is missing');
  const size = parseInt(request.headers.get('content-length') || '', 10);
  if (!Number.isFinite(size) || size <= 0) throw new HttpError(411, 'Content-Length is missing');
  if (size > spec.max) throw new HttpError(413, `The file is larger than ${spec.max / 1048576} MB`);
  const manifest = await readJson(env, REL + product + '/manifest.json', emptyManifest(product));
  if ((manifest.versions || []).some(v => v.version === version)) {
    throw new HttpError(409, `Version ${version} is already published - a published version never changes.`);
  }
  try {
    await env.BUCKET.put(REL + product + '/' + version, request.body, {
      sha1, httpMetadata: { contentType: spec.type }, customMetadata: { sha1 },
    });
  } catch (e) {
    throw new HttpError(400, 'The file did not arrive whole (SHA-1 differs) - send it again.');
  }
  await audit(env, who, 'release_upload', product + ' ' + version, String(size));
  return json({ product, version, size, sha1 });
}

async function releasePublish(request, env, who, product) {
  needAdmin(who);
  productOf(product);
  const body = await request.json().catch(() => ({}));
  const version = versionOf(body.version);
  const channel = String(body.channel || '');
  const note = String(body.note || '').trim();
  if (!CHANNELS.includes(channel)) throw new HttpError(400, 'Channel must be stable or beta');
  if (!note) throw new HttpError(400, 'Write what changed in this version.');
  const key = REL + product + '/' + version;
  const obj = await env.BUCKET.head(key);
  if (!obj) throw new HttpError(404, `Upload the file of version ${version} first.`);
  const sha1 = (obj.customMetadata && obj.customMetadata.sha1) || '';
  if (body.sha1 && String(body.sha1).toLowerCase() !== sha1) {
    throw new HttpError(409, 'The uploaded file is not the one you describe (SHA-1 differs).');
  }
  return withLock(env, 'release-' + product, who.id, async () => {
    const manifest = await readJson(env, REL + product + '/manifest.json', emptyManifest(product));
    manifest.versions = manifest.versions || [];
    if (manifest.versions.some(v => v.version === version)) {
      throw new HttpError(409, `Version ${version} is already published.`);
    }
    manifest.versions.push({
      version, size: obj.size, sha1, note: note.slice(0, 4000), time: nowIso(), by: who.name,
      name: String(body.name || '').slice(0, 120),
    });
    manifest.channels = { stable: '', beta: '', ...(manifest.channels || {}) };
    manifest.channels[channel] = version;
    // keep the last versions and whatever a channel points at; delete the files of the rest
    const pinned = new Set(Object.values(manifest.channels).filter(Boolean));
    const keep = manifest.versions.slice(-KEEP_VERSIONS).map(v => v.version);
    const gone = manifest.versions.filter(v => !pinned.has(v.version) && !keep.includes(v.version));
    manifest.versions = manifest.versions.filter(v => !gone.includes(v));
    await putJson(env, REL + product + '/manifest.json', manifest);
    if (gone.length) await env.BUCKET.delete(gone.map(v => REL + product + '/' + v.version));
    await audit(env, who, 'release_publish', product + ' ' + version, channel);
    return json({ product, version, channel, channels: manifest.channels });
  });
}

async function releasePromote(request, env, who, product) {
  needAdmin(who);
  productOf(product);
  const body = await request.json().catch(() => ({}));
  const version = versionOf(body.version);
  const channel = String(body.channel || '');
  if (!CHANNELS.includes(channel)) throw new HttpError(400, 'Channel must be stable or beta');
  return withLock(env, 'release-' + product, who.id, async () => {
    const manifest = await readJson(env, REL + product + '/manifest.json', emptyManifest(product));
    if (!(manifest.versions || []).some(v => v.version === version)) {
      throw new HttpError(404, `Version ${version} is not published (or its file was already removed).`);
    }
    manifest.channels = { stable: '', beta: '', ...(manifest.channels || {}) };
    manifest.channels[channel] = version;
    await putJson(env, REL + product + '/manifest.json', manifest);
    await audit(env, who, 'release_promote', product + ' ' + version, channel);
    return json({ product, version, channel, channels: manifest.channels });
  });
}

async function releaseRoute(request, env, who, method, path) {
  let m;
  if (method === 'GET' && (m = /^\/release\/([a-z]+)\/manifest$/.exec(path))) {
    productOf(m[1]);
    return storedJson(request, env, REL + m[1] + '/manifest.json', emptyManifest(m[1]));
  }
  if ((m = /^\/release\/([a-z]+)\/file\/([0-9.]+)$/.exec(path))) {
    productOf(m[1]);
    const version = versionOf(m[2]);
    if (method === 'PUT') return releaseUpload(request, env, who, m[1], version);
    if (method === 'GET') {
      const obj = await env.BUCKET.get(REL + m[1] + '/' + version);
      if (!obj) throw new HttpError(404, `No such version: ${m[1]} ${version}`);
      await audit(env, who, 'release_download', m[1] + ' ' + version, '');
      return fileResponse(obj);
    }
  }
  if (method === 'POST' && (m = /^\/release\/([a-z]+)\/publish$/.exec(path))) return releasePublish(request, env, who, m[1]);
  if (method === 'POST' && (m = /^\/release\/([a-z]+)\/promote$/.exec(path))) return releasePromote(request, env, who, m[1]);
  return null;
}

// ---- router ---------------------------------------------------------------------
async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';
  const method = request.method.toUpperCase();
  if (path === '/' && method === 'GET') return json({ service: 'peer-library', ok: true });
  if (path === '/access/request' && method === 'POST') return requestAccess(request, env);
  if (path === '/access/status' && method === 'POST') return accessStatus(request, env);
  // The loader is public: anybody installs it, the rest of PEER comes after signing in.
  // It holds no tools - only the Account button, the library client and the updater.
  if (method === 'GET' && path === '/boot/manifest') {
    return storedJson(request, env, REL + 'boot/manifest.json', emptyManifest('boot'));
  }
  let b;
  if (method === 'GET' && (b = /^\/boot\/file\/([0-9.]+)$/.exec(path))) {
    const obj = await env.BUCKET.get(REL + 'boot/' + versionOf(b[1]));
    if (!obj) throw new HttpError(404, 'No such version of the PEER loader: ' + b[1]);
    return fileResponse(obj);
  }

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
    return storedJson(request, env, LIB + 'index.json', { format: 1, built: '', count: 0, families: [] });
  }
  if (method === 'GET' && path === '/changelog') {
    return storedJson(request, env, LIB + 'changelog.json', { format: 1, entries: [] });
  }
  if (method === 'GET' && (m = /^\/file\/(.+)$/.exec(url.pathname))) {
    const p = safePath(m[1]);
    const obj = await env.BUCKET.get(LIB + p);
    if (!obj) throw new HttpError(404, 'Not in the library: ' + p);
    if (p.endsWith('.rfa')) await audit(env, who, 'download', p, '');
    return fileResponse(obj);
  }
  if (path.startsWith('/release/')) {
    const r = await releaseRoute(request, env, who, method, path);
    if (r) return r;
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
    const r = await env.DB.prepare('SELECT id, name, role, active, created, created_by, last_used, version FROM keys ORDER BY active DESC, name').all();
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
