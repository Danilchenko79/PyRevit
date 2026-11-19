// Runs Code.gs in node against fake Google services. `node test_receiver.js`
// Exit code 0 = all checks passed. Called from lib/peer_feedback/tests.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function fakeSheet(name) {
  const rows = [];
  const sheet = {
    name, rows,
    getName: () => name,
    getLastRow: () => rows.length,
    getMaxRows: () => 1000,
    appendRow: (r) => { rows.push(r.slice()); },
    setFrozenRows: () => {},
    setColumnWidth: () => {},
    getRange: (row, col, nRows, nCols) => ({
      getValues: () => rows.slice(row - 1, row - 1 + nRows).map((r) => r.slice(col - 1, col - 1 + nCols)),
      setFontWeight: () => {},
      setDataValidation: () => {},
      setNote: () => {},
      getRow: () => row,
      getColumn: () => col,
      getSheet: () => sheet,
      setValue: (v) => { rows[row - 1][col - 1] = v; },
      createTextFinder: (text) => ({
        matchEntireCell: () => ({
          findNext: () => {
            for (let i = row - 1; i < row - 1 + nRows; i++) {
              if (String(rows[i][col - 1]) === text) return { getRow: () => i + 1 };
            }
            return null;
          },
        }),
      }),
    }),
  };
  return sheet;
}

const sheets = {};
const props = {};
const ctx = {
  PropertiesService: { getScriptProperties: () => ({
    getProperty: (k) => (k in props ? props[k] : null),
    setProperty: (k, v) => { props[k] = v; },
  }) },
  LockService: { getScriptLock: () => ({ waitLock: () => {}, releaseLock: () => {} }) },
  SpreadsheetApp: {
    getActiveSpreadsheet: () => ({
      getSheetByName: (n) => sheets[n] || null,
      insertSheet: (n) => (sheets[n] = fakeSheet(n)),
    }),
    newDataValidation: () => {
      const b = { requireValueInList: () => b, setAllowInvalid: () => b, build: () => ({}) };
      return b;
    },
  },
  ContentService: {
    MimeType: { JSON: 'json' },
    createTextOutput: (t) => ({ text: t, setMimeType() { return this; } }),
  },
  Utilities: { getUuid: () => '11111111-2222-3333-4444-555555555555' },
  Logger: { log: () => {} },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'Code.gs'), 'utf8'), ctx);

// Dates come from the vm realm: instanceof Date is false there
const isDate = (v) => Object.prototype.toString.call(v) === '[object Date]';
const post = (body) => JSON.parse(ctx.doPost({ postData: { contents: JSON.stringify(body) } }).text);
const req = (over) => Object.assign({
  id: 'a'.repeat(32), topic: 'automation', text: 'Хочу кнопку', project: 'בניין A',
  user: 'Дима', created_at: '2026-11-19T10:00:00Z',
}, over || {});

// no key configured yet -> everything refused
assert.strictEqual(post({ key: '', action: 'ping' }).error, 'bad_key');

ctx.setup();
const key = props.PEER_KEY;
assert.strictEqual(key, '11111111222233334444555555555555');
const sh = sheets.Requests;
assert.strictEqual(sh.rows.length, 1, 'header row');
const header = sh.rows[0];
const col = (title) => header.indexOf(title);

assert.strictEqual(post({ key: 'wrong', action: 'ping' }).error, 'bad_key');
assert.strictEqual(post({ key, action: 'ping' }).ok, true);
assert.strictEqual(post({ key, action: 'drop_table' }).error, 'bad_request');
assert.strictEqual(JSON.parse(ctx.doPost({ postData: { contents: '{x' } }).text).error, 'bad_request');

// one request -> one row with the right cells
let a = post({ key, action: 'request', data: req() });
assert.deepStrictEqual([a.ok, a.duplicate], [true, undefined]);
assert.strictEqual(sh.rows.length, 2);
const row = sh.rows[1];
assert.strictEqual(row[col('ID')], 'a'.repeat(32));
assert.strictEqual(row[col('Text')], 'Хочу кнопку');
assert.strictEqual(row[col('Project')], 'בניין A');
assert.strictEqual(row[col('Status')], 'New');
assert.ok(isDate(row[col('Received')]));
assert.strictEqual(row.length, header.length);

// retry of the same id -> no second row
a = post({ key, action: 'request', data: req({ text: 'changed' }) });
assert.deepStrictEqual([a.ok, a.duplicate], [true, true]);
assert.strictEqual(sh.rows.length, 2);

// broken items are refused as bad_request (client drops them)
for (const bad of [req({ id: 'x' }), req({ id: 'b'.repeat(32), text: '  ' }),
                   req({ id: 'b'.repeat(32), topic: 'spam' })]) {
  assert.strictEqual(post({ key, action: 'request', data: bad }).error, 'bad_request');
}
assert.strictEqual(sh.rows.length, 2);

// formula injection is neutralised, long text clipped
post({ key, action: 'request', data: req({ id: 'c'.repeat(32), text: '=IMPORTXML("x")',
                                          error_text: 'e'.repeat(9000) }) });
const r3 = sh.rows[2];
assert.strictEqual(r3[col('Text')], "'=IMPORTXML(\"x\")");
assert.strictEqual(r3[col('Error text')].length, 5000);

// manual status change stamps the time
ctx.onEdit({ range: sh.getRange(2, col('Status') + 1) });
assert.ok(isDate(sh.rows[1][col('Status changed')]));

// status: only the ids asked, never other rows; junk ids ignored
sh.rows[1][col('Status')] = 'Accepted';
sh.rows[1][col('Comment for the author')] = 'Next week';
let st = post({ key, action: 'status', data: { ids: ['a'.repeat(32), 'f'.repeat(32), '../x'] } });
assert.strictEqual(st.ok, true);
assert.deepStrictEqual(Object.keys(st.statuses), ['a'.repeat(32)]);
assert.strictEqual(st.statuses['a'.repeat(32)].status, 'Accepted');
assert.strictEqual(st.statuses['a'.repeat(32)].comment, 'Next week');
assert.ok(/^\d{4}-\d\d-\d\dT/.test(st.statuses['a'.repeat(32)].changed));
assert.strictEqual(JSON.stringify(st).indexOf('Хочу'), -1, 'no request text leaks');
assert.deepStrictEqual(post({ key, action: 'status', data: {} }).statuses, {});
assert.strictEqual(post({ key: 'wrong', action: 'status', data: { ids: ['a'.repeat(32)] } }).error, 'bad_key');

console.log('receiver: all checks passed');
