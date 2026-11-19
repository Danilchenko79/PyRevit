// Makes the first admin key. The key is printed once and NOT saved anywhere;
// only its SHA-256 goes into the database.
//
//   node scripts/first_key.mjs "Dima"
//   -> run the printed wrangler command, keep the key in a password manager.
import { webcrypto as crypto } from 'node:crypto';

const name = (process.argv[2] || '').trim();
if (!name) { console.error('usage: node scripts/first_key.mjs "<your name>"'); process.exit(1); }
const raw = crypto.getRandomValues(new Uint8Array(32));
const key = 'peer_' + Buffer.from(raw).toString('base64url');
const id = Buffer.from(crypto.getRandomValues(new Uint8Array(6))).toString('base64url');
const hash = Buffer.from(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key))).toString('hex');
const now = new Date().toISOString().slice(0, 19);
const sql = `INSERT INTO keys (id, hash, name, role, active, created, created_by) VALUES ('${id}', '${hash}', '${name.replace(/'/g, "''")}', 'admin', 1, '${now}', 'setup')`;

console.log('\nYour admin key (shown once - paste it into PEER -> Library on first start):\n');
console.log('   ' + key + '\n');
console.log('Now run:\n');
console.log(`   npx wrangler d1 execute peer-library --remote --command "${sql}"\n`);
