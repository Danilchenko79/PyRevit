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
    getLastColumn: () => (rows[0] ? rows[0].length : 0),
    getMaxRows: () => 1000,
    appendRow: (r) => { rows.push(r.slice()); },
    clear: () => { rows.length = 0; },
    setFrozenRows: () => {},
    setColumnWidth: () => {},
    getRange: (row, col, nRows, nCols) => { const range = {
      getValues: () => rows.slice(row - 1, row - 1 + nRows).map((r) => r.slice(col - 1, col - 1 + nCols)),
      setValues: (vals) => { vals.forEach((v, i) => { rows[row - 1 + i] = v.slice(); }); },
      setFontWeight: () => range,
      setValue: (v) => { rows[row - 1] = rows[row - 1] || []; rows[row - 1][col - 1] = v; return range; },
      setFontSize: () => range,
      setDataValidation: () => {},
      setNote: () => {},
      getRow: () => row,
      getColumn: () => col,
      getSheet: () => sheet,
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
    }; return range; },
  };
  return sheet;
}

const sheets = {};
const drive = { created: 0, files: [], folder: null };
drive.folder = {
  getId: () => 'F1',
  createFile: (blob) => { drive.files.push(blob); return { getUrl: () => 'https://drive/' + blob.name }; },
};
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
  Utilities: {
    getUuid: () => '11111111-2222-3333-4444-555555555555',
    formatDate: (d, tz, f) => d.toISOString().slice(0, 10),
    base64Decode: (b64) => Array.from(Buffer.from(b64, 'base64')),
    newBlob: (bytes, type, name) => ({ bytes, type, name }),
  },
  DriveApp: {
    getFolderById: (id) => { if (id !== 'F1') throw new Error('no folder'); return drive.folder; },
    createFolder: (name) => { drive.created += 1; return drive.folder; },
  },
  Session: { getScriptTimeZone: () => 'Asia/Jerusalem', getEffectiveUser: () => ({ getEmail: () => 'me@x' }) },
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

// usage: rows appended once by id, junk rows skipped, counts are numbers
assert.ok(sheets.Usage && sheets.Buttons, 'setup creates Usage and Buttons');
const u1 = { id: '1'.repeat(32), date: '2026-11-18', user: 'dima', machine: 'PC-01',
             button: 'Walls / WallRebar2D', runs: '3', failures: 2, last_error: '=boom' };
let ru = post({ key, action: 'usage', data: { id: 'x', rows: [u1, { id: 'bad', date: 'x', button: 'y' }] } });
assert.deepStrictEqual([ru.ok, ru.added, ru.skipped], [true, 1, 1]);
ru = post({ key, action: 'usage', data: { id: 'x', rows: [u1] } });
assert.deepStrictEqual([ru.added, ru.skipped], [0, 1]);
const uh = sheets.Usage.rows[0];
const urow = sheets.Usage.rows[1];
assert.strictEqual(sheets.Usage.rows.length, 2);
assert.strictEqual(urow[uh.indexOf('Runs')], 3);
assert.strictEqual(urow[uh.indexOf('Last error')], "'=boom");
assert.strictEqual(post({ key, action: 'usage', data: { rows: 'x' } }).error, 'bad_request');

// buttons: only missing names are added, minutes stay for the head
let rb = post({ key, action: 'buttons', data: { id: 'y', names: ['Walls / WallRebar2D', 'Feedback / Contact'] } });
assert.strictEqual(rb.added, 2);
sheets.Buttons.rows[1][1] = 5;
rb = post({ key, action: 'buttons', data: { id: 'y', names: ['Walls / WallRebar2D', 'Piles / PilesCoordinate'] } });
assert.strictEqual(rb.added, 1);
assert.strictEqual(sheets.Buttons.rows[1][1], 5);
assert.strictEqual(sheets.Buttons.rows.length, 4);

// unknown action keeps its own detail, so an old PEER/receiver pair retries instead of dropping
assert.strictEqual(post({ key, action: 'later_feature' }).detail, 'unknown action');

// weekly summary on synthetic data
const NOW = new Date('2026-11-23T07:00:00Z');
const daysAgo = (n) => new Date(NOW.getTime() - n * 86400000);
const R = (o) => Object.assign({ id: Math.random().toString(16).slice(2), status: 'New', frequency: '',
                                 duration: '', button: '', text: '', error_text: '' }, o,
                               { received_at: daysAgo(o.ago), status_changed_at: daysAgo(o.ago) });
const sum = ctx.buildSummary_({
  requests: [
    R({ ago: 1, topic: 'automation', user: 'a', text: 'Sections at beams', frequency: 'daily', duration: 'gt30' }),
    R({ ago: 2, topic: 'improve', user: 'a', button: 'Documentation / WinTag', text: 'units', frequency: 'weekly', duration: 'lt5' }),
    R({ ago: 3, topic: 'improve', user: 'b', button: 'Documentation / WinTag', text: 'faster', frequency: 'daily', duration: '5to30' }),
    R({ ago: 2, topic: 'bug', user: 'a', button: 'Walls / WallRebar2D',
        error_text: 'Traceback (most recent call last):\n  File x\nException: no wall selected' }),
    R({ ago: 2, topic: 'bug', user: 'b', button: 'Walls / WallRebar2D' }),
    R({ ago: 1, topic: 'idea', user: 'c', text: 'Something like WinTag for doors' }),
    R({ ago: 1, topic: 'howto', user: 'c', text: 'How to tag piles?' }),
    R({ ago: 20, topic: 'routine', user: 'd', text: 'old routine', frequency: 'rare' }),
    R({ ago: 30, topic: 'automation', user: 'd', text: 'done one', status: 'Done', frequency: 'daily', duration: 'gt30' }),
  ],
  usage: [
    { date: daysAgo(2), button: 'Walls / WallRebar2D', user: 'a', runs: 10, failures: 2, last_error: 'Exception: x' },
    { date: daysAgo(2), button: 'Documentation / WinTag', user: 'a', runs: 6, failures: 1, last_error: 'Exception: y' },
    { date: daysAgo(3), button: 'Documentation / WinTag', user: 'b', runs: 4, failures: 0, last_error: '' },
    { date: daysAgo(40), button: 'Piles / PilesCoordinate', user: 'a', runs: 9, failures: 0, last_error: '' },
  ],
  buttons: [
    { button: 'Walls / WallRebar2D', minutes: 10 }, { button: 'Documentation / WinTag', minutes: '' },
    { button: 'Piles / PilesCoordinate', minutes: 5 },
  ],
}, NOW);
// arrays from the vm realm fail deepStrictEqual on prototypes: compare plain copies
const plain = JSON.parse(JSON.stringify(sum));
const B = (n) => plain.blocks[n - 1];
assert.strictEqual(sum.blocks.length, 8);
assert.ok(B(1).note.startsWith('7 requests from 3 people'));
assert.deepStrictEqual(B(1).rows[0], ['Improve a button', 2]);
assert.strictEqual(B(2).rows.length, 3);
assert.ok(B(2).rows[0][0].includes('Sections at beams'));                      // 5*45/60 = 3.75 h
assert.deepStrictEqual(B(2).rows[0].slice(1), [1, '3.8']);
assert.ok(B(2).rows[1][0].startsWith('Improve Documentation / WinTag'));      // 2 people grouped
assert.deepStrictEqual(B(2).rows[1].slice(1), [2, '1.3']);                     // 1*3/60 + 5*15/60
assert.ok(B(2).rows[2][0].includes('old routine'));
assert.ok(!B(2).rows.some((r) => r[0].includes('done one')));                  // closed ones out
assert.deepStrictEqual(B(3).rows[0].slice(0, 4), ['Walls / WallRebar2D', 2, 2, 'yes']);
assert.strictEqual(B(3).rows[0][4], 'Exception: no wall selected');
assert.deepStrictEqual(B(4).rows[0], ['Walls / WallRebar2D', 10, 1]);
assert.ok(B(4).note.includes('Piles / PilesCoordinate'));                      // unused in 30 days
assert.deepStrictEqual(B(5).rows.map((r) => r[0]), ['Documentation / WinTag']); // WallRebar2D was reported
assert.ok(B(6).rows.some((r) => r[0] === 'Asks for what may exist' && r[1] === 'WinTag'));
assert.ok(B(6).rows.some((r) => r[0] === 'How-to question'));
assert.ok(B(7).note.startsWith('1.3 hours'));                                  // (10-2)*10 min
assert.ok(B(7).note.includes('No minutes set for: Documentation / WinTag'));
assert.ok(B(8).note.includes('No answer for more than 7 days: 1'));
assert.strictEqual(B(8).rows[0][2], 'old routine');
const html = ctx.renderHtml_(sum);
assert.ok(html.includes('<h3') && !html.includes('<script'));
ctx.writeSummarySheet_(sum);
assert.ok(sheets.Summary.rows[0][0].startsWith('PEER weekly summary'));

// pictures: saved to the Drive folder, links on the row, folder made once
assert.strictEqual(props.ATTACH_FOLDER_ID, 'F1', 'setup made the folder');
assert.strictEqual(drive.created, 1);
const jpg = Buffer.from([0xff, 0xd8, 0xff, 0xd9]).toString('base64');
const withPics = req({ id: '9'.repeat(32), attachments: [
  { name: 'image-1.jpg', type: 'image/jpeg', data: jpg },
  { name: 'x.exe', type: 'application/x-msdownload', data: jpg },
] });
assert.strictEqual(post({ key, action: 'request', data: withPics }).ok, true);
const picRow = sheets.Requests.rows[sheets.Requests.rows.length - 1];
const pics = picRow[col('Pictures')].split('\n');
assert.strictEqual(pics.length, 2);
assert.ok(/^https:\/\/drive\/\d{4}-\d\d-\d\d 99999999 1\.jpg$/.test(pics[0]));
assert.ok(pics[1].startsWith('(picture 2 not saved'));
assert.deepStrictEqual(Array.from(drive.files[0].bytes), [0xff, 0xd8, 0xff, 0xd9]);
// a retry of the same request: no second copy of the pictures
post({ key, action: 'request', data: withPics });
assert.strictEqual(drive.files.length, 1);
assert.strictEqual(drive.created, 1);
assert.strictEqual(post({ key, action: 'request', data: req({ id: '8'.repeat(32),
  attachments: new Array(6).fill({ type: 'image/jpeg', data: jpg }) }) }).error, 'bad_request');

// a sheet made by an older version gets the new column header, old rows untouched
sheets.Requests.rows[0].pop();
post({ key, action: 'request', data: req({ id: '7'.repeat(32) }) });
assert.strictEqual(sheets.Requests.rows[0][sheets.Requests.rows[0].length - 1], 'Pictures');

console.log('receiver: all checks passed');
