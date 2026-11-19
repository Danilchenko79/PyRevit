// node --test service/test   (no Cloudflare account, no npm packages)
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';
import { MockBucket, MockD1, seedKey } from './mocks.mjs';

const ADMIN = 'peer_' + 'a'.repeat(40);
const USER = 'peer_' + 'u'.repeat(40);
let env;

beforeEach(async () => {
  env = { BUCKET: new MockBucket(), DB: new MockD1() };
  await seedKey(env.DB, { id: 'adm1', key: ADMIN, name: 'Dima', role: 'admin' });
  await seedKey(env.DB, { id: 'usr1', key: USER, name: 'Anna', role: 'user' });
});

async function call(method, path, key, body) {
  const headers = {};
  if (key) headers.authorization = 'Bearer ' + key;
  let payload = body;
  if (body && !(body instanceof FormData)) { payload = JSON.stringify(body); headers['content-type'] = 'application/json'; }
  const res = await worker.fetch(new Request('https://lib.test' + path, { method, headers, body: payload }), env);
  const type = res.headers.get('content-type') || '';
  const data = type.startsWith('application/json') ? await res.json() : new Uint8Array(await res.arrayBuffer());
  return { status: res.status, data };
}

function publishForm(id, version, extra = {}) {
  const fd = new FormData();
  fd.append('card', JSON.stringify({ id, name: 'Балка', group: '01_Framing', tags: ['балка'], version, ...extra.card }));
  fd.append('rfa', new Blob([extra.rfa || 'rfa-' + version]), id + '.rfa');
  if (extra.png !== false) fd.append('png', new Blob(['png-' + version]), id + '.png');
  if (extra.note) fd.append('note', extra.note);
  if (extra.proposal) fd.append('proposal_id', extra.proposal);
  return fd;
}

test('health without key, 401 without / with a wrong key', async () => {
  assert.equal((await call('GET', '/')).status, 200);
  assert.equal((await call('GET', '/index')).status, 401);
  assert.equal((await call('GET', '/index', 'peer_' + 'x'.repeat(40))).status, 401);
});

test('auth returns name and role', async () => {
  const r = await call('GET', '/auth', USER);
  assert.deepEqual([r.status, r.data.name, r.data.role], [200, 'Anna', 'user']);
});

test('user cannot publish, admin can; files and index', async () => {
  assert.equal((await call('POST', '/publish', USER, publishForm('PEER_Beam', 1))).status, 403);
  const r = await call('POST', '/publish', ADMIN, publishForm('PEER_Beam', 1));
  assert.equal(r.status, 200, JSON.stringify(r.data));
  assert.equal(r.data.version, 1);
  assert.equal(r.data.files['.rfa'], '01_Framing/PEER_Beam/v1.rfa');
  const idx = await call('GET', '/index', USER);
  assert.equal(idx.data.count, 1);
  assert.equal(idx.data.families[0].name, 'Балка');
  const f = await call('GET', '/file/' + encodeURI(r.data.files['.rfa']), USER);
  assert.equal(new TextDecoder().decode(f.data), 'rfa-1');
  const log = await call('GET', '/changelog', USER);
  assert.equal(log.data.entries[0].action, 'added');
});

test('new version: version check, history, old files removed', async () => {
  await call('POST', '/publish', ADMIN, publishForm('PEER_Beam', 1));
  assert.equal((await call('POST', '/publish', ADMIN, publishForm('PEER_Beam', 1))).status, 409);
  const r = await call('POST', '/publish', ADMIN, publishForm('PEER_Beam', 2, { note: 'вут', png: false }));
  assert.equal(r.status, 200);
  assert.deepEqual(r.data.history.map(h => h.v), [1, 2]);
  assert.equal(r.data.history[1].note, 'вут');
  assert.equal(r.data.png_sha1, '');
  const keys = env.BUCKET.keys();
  assert.ok(keys.includes('PEER-Library/01_Framing/PEER_Beam/v2.rfa'));
  assert.ok(!keys.includes('PEER-Library/01_Framing/PEER_Beam/v1.rfa'));
  assert.ok(!keys.includes('PEER-Library/01_Framing/PEER_Beam/v1.png'));
});

test('bad card and path traversal are refused', async () => {
  const fd = publishForm('bad/name', 1);
  assert.equal((await call('POST', '/publish', ADMIN, fd)).status, 400);
  assert.equal((await call('GET', '/file/..%2Fkeys', USER)).status, 400);
});

test('proposal: send, mine, admin list, file, reject needs comment, accept by publish', async () => {
  const fd = new FormData();
  fd.append('meta', JSON.stringify({ name: 'Балка с вутом', group: '01_Framing', kind: 'new', reason: 'нужна', author: 'hacker' }));
  fd.append('rfa', new Blob(['proposal-rfa']), 'family.rfa');
  const sent = await call('POST', '/inbox', USER, fd);
  assert.equal(sent.status, 200);
  const id = sent.data.id;
  const mine = await call('GET', '/inbox/mine', USER);
  assert.equal(mine.data[0].author, 'Anna');            // author from the key, not from the client
  assert.equal(mine.data[0].status, 'pending');
  assert.equal((await call('GET', '/inbox', USER)).status, 403);
  assert.equal((await call('GET', '/inbox', ADMIN)).data.length, 1);
  const file = await call('GET', `/inbox/${id}/family.rfa`, ADMIN);
  assert.equal(new TextDecoder().decode(file.data), 'proposal-rfa');
  assert.equal((await call('POST', '/reject', ADMIN, { id, comment: '' })).status, 400);
  const pub = await call('POST', '/publish', ADMIN, publishForm('PEER_Beam_Haunch', 1, { proposal: id }));
  assert.equal(pub.status, 200);
  const after = await call('GET', '/inbox/mine', USER);
  assert.equal(after.data[0].status, 'accepted');
  assert.equal((await call('GET', '/inbox', ADMIN)).data.length, 0);
});

test('reject with a comment; other users do not see it', async () => {
  const fd = new FormData();
  fd.append('meta', JSON.stringify({ name: 'x' }));
  fd.append('rfa', new Blob(['r']), 'family.rfa');
  const id = (await call('POST', '/inbox', USER, fd)).data.id;
  assert.equal((await call('POST', '/reject', ADMIN, { id, comment: 'уже есть' })).status, 200);
  const mine = await call('GET', '/inbox/mine', USER);
  assert.deepEqual([mine.data[0].status, mine.data[0].comment], ['rejected', 'уже есть']);
  assert.equal((await call('GET', '/inbox/mine', ADMIN)).data.length, 0);
});

test('keys: add, list, revoke -> 401, others still work', async () => {
  assert.equal((await call('POST', '/keys', USER, { name: 'x' })).status, 403);
  const k = await call('POST', '/keys', ADMIN, { name: 'Boris', role: 'user' });
  assert.equal(k.status, 200);
  assert.match(k.data.key, /^peer_[A-Za-z0-9_-]{40,}$/);
  assert.equal((await call('GET', '/auth', k.data.key)).data.name, 'Boris');
  const list = await call('GET', '/keys', ADMIN);
  assert.ok(list.data.every(r => !('hash' in r)));
  assert.equal((await call('DELETE', '/keys/' + k.data.id, ADMIN)).status, 200);
  assert.equal((await call('GET', '/auth', k.data.key)).status, 401);
  assert.equal((await call('GET', '/auth', USER)).status, 200);
  assert.equal((await call('DELETE', '/keys/adm1', ADMIN)).status, 400);
});

test('deprecate keeps the family in the index with status', async () => {
  await call('POST', '/publish', ADMIN, publishForm('PEER_Beam', 1));
  assert.equal((await call('POST', '/deprecate', ADMIN, { id: 'PEER_Beam', note: 'old' })).status, 200);
  const idx = await call('GET', '/index', USER);
  assert.equal(idx.data.families[0].status, 'deprecated');
});

test('audit records downloads and publishes', async () => {
  const r = await call('POST', '/publish', ADMIN, publishForm('PEER_Beam', 1));
  await call('GET', '/file/' + encodeURI(r.data.files['.rfa']), USER);
  const a = await call('GET', '/audit', ADMIN);
  assert.deepEqual(a.data.map(x => x.action).slice(0, 2), ['download', 'publish']);
});
