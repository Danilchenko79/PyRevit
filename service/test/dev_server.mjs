// Local copy of the service for tests and trials: the real worker code over
// node:http with an in-memory (or folder) R2 and a node:sqlite D1.
//
//   node test/dev_server.mjs [port] [data-folder]
// Prints "READY <port>" and the seeded test keys on stdout.
import http from 'node:http';
import worker from '../src/worker.js';
import { MockBucket, MockD1, seedKey } from './mocks.mjs';

const port = parseInt(process.argv[2] || '8787', 10);
const folder = process.argv[3] || null;
const env = { BUCKET: new MockBucket(folder), DB: new MockD1() };
const ADMIN = 'peer_' + 'a'.repeat(40);
const USER = 'peer_' + 'u'.repeat(40);
await seedKey(env.DB, { id: 'adm1', key: ADMIN, name: 'Dima', role: 'admin' });
await seedKey(env.DB, { id: 'usr1', key: USER, name: 'Anna', role: 'user' });

const server = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) if (typeof v === 'string') headers.set(k, v);
  const request = new Request(`http://127.0.0.1:${port}${req.url}`, {
    method: req.method, headers, body: ['GET', 'HEAD'].includes(req.method) ? undefined : body });
  const out = await worker.fetch(request, env);
  const buf = Buffer.from(await out.arrayBuffer());
  const h = Object.fromEntries(out.headers.entries());
  h['content-length'] = String(buf.length);
  res.writeHead(out.status, h);
  res.end(buf);
});
server.listen(port, '127.0.0.1', () => {
  console.log(`READY ${port}`);
  console.log(`ADMIN ${ADMIN}`);
  console.log(`USER ${USER}`);
});
