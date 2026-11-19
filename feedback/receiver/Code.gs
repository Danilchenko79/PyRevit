/**
 * PEER feedback receiver - Google Apps Script bound to the group's Google Sheet.
 *
 * Accepts POST {v, key, action, data} from PEER (lib/peer_feedback/client.py)
 * and appends one row per request to the "Requests" sheet.
 *
 * It can ONLY:
 *   - answer a ping,
 *   - append a request row (duplicates by id are ignored).
 * It never returns the table's contents, so a leaked address + key lets
 * someone add rows, nothing more. Change the key in Script Properties
 * (PEER_KEY) and in PEER settings to cut them off.
 *
 * Setup: feedback/SETUP.md. Run setup() once from the editor.
 */

var SHEET_REQUESTS = 'Requests';

// Column order on the sheet. Keys = fields of lib/peer_feedback/payload.py.
// The last three are the head's columns: filled by hand in the table.
var REQUEST_COLUMNS = [
  ['id', 'ID'],
  ['received_at', 'Received'],
  ['created_at', 'Created (UTC)'],
  ['topic', 'Topic'],
  ['text', 'Text'],
  ['button', 'Button'],
  ['frequency', 'How often'],
  ['duration', 'Time per occurrence'],
  ['user', 'User'],
  ['machine', 'Computer'],
  ['project', 'Project'],
  ['view', 'View'],
  ['selection', 'Selection'],
  ['revit_version', 'Revit'],
  ['pyrevit_version', 'pyRevit'],
  ['peer_version', 'PEER'],
  ['error_script', 'Error script'],
  ['error_text', 'Error text'],
  ['status', 'Status'],
  ['comment', 'Comment for the author'],
  ['status_changed_at', 'Status changed']
];

var STATUSES = ['New', 'Accepted', 'In progress', 'Done', 'Rejected'];
var TOPICS = ['automation', 'improve', 'bug', 'idea', 'routine', 'template', 'howto', 'standard'];
var MAX_CELL = 5000;

// ------------------------------------------------------------------ entry --

function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return json_({ ok: false, error: 'bad_request', detail: 'not json' });
  }
  var key = PropertiesService.getScriptProperties().getProperty('PEER_KEY');
  if (!key || !body || body.key !== key) {
    return json_({ ok: false, error: 'bad_key' });
  }
  try {
    switch (body.action) {
      case 'ping':
        return json_({ ok: true, pong: true, time: new Date().toISOString() });
      case 'request':
        return json_(saveRequest_(body.data || {}));
      default:
        return json_({ ok: false, error: 'bad_request', detail: 'unknown action' });
    }
  } catch (err) {
    // sheet busy / quota: the client keeps the item and retries later
    return json_({ ok: false, error: 'server', detail: String(err) });
  }
}

function doGet() {
  // open the web app URL in a browser to see that it is deployed
  return ContentService.createTextOutput('PEER receiver is running.');
}

// ---------------------------------------------------------------- request --

function saveRequest_(d) {
  var id = String(d.id || '');
  if (!/^[0-9a-f]{32}$/.test(id)) {
    return { ok: false, error: 'bad_request', detail: 'bad id' };
  }
  if (!String(d.text || '').trim()) {
    return { ok: false, error: 'bad_request', detail: 'empty text' };
  }
  if (TOPICS.indexOf(d.topic) < 0) {
    return { ok: false, error: 'bad_request', detail: 'unknown topic' };
  }

  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sheet = sheet_(SHEET_REQUESTS, REQUEST_COLUMNS);
    if (findRow_(sheet, id) > 0) {
      return { ok: true, id: id, duplicate: true };
    }
    var now = new Date();
    var row = REQUEST_COLUMNS.map(function (c) {
      var k = c[0];
      if (k === 'received_at') return now;
      if (k === 'status') return STATUSES[0];
      if (k === 'status_changed_at') return now;
      if (k === 'comment') return '';
      return cell_(d[k]);
    });
    sheet.appendRow(row);
    return { ok: true, id: id };
  } finally {
    lock.releaseLock();
  }
}

// ---------------------------------------------------------------- helpers --

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Text that the sheet must not read as a formula (=, +, -, @). */
function cell_(v) {
  var s = v === null || v === undefined ? '' : String(v);
  if (s.length > MAX_CELL) s = s.slice(0, MAX_CELL - 1) + '…';
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return s;
}

function book_() {
  var id = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
}

function sheet_(name, columns) {
  var book = book_();
  var sheet = book.getSheetByName(name);
  if (!sheet) {
    sheet = book.insertSheet(name);
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(columns.map(function (c) { return c[1]; }));
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, columns.length).setFontWeight('bold');
  }
  return sheet;
}

/** Row number (2..) of the request id in column A, or 0. */
function findRow_(sheet, id) {
  var last = sheet.getLastRow();
  if (last < 2) return 0;
  var hit = sheet.getRange(2, 1, last - 1, 1)
    .createTextFinder(id).matchEntireCell(true).findNext();
  return hit ? hit.getRow() : 0;
}

function columnOf_(key) {
  for (var i = 0; i < REQUEST_COLUMNS.length; i++) {
    if (REQUEST_COLUMNS[i][0] === key) return i + 1;
  }
  return 0;
}

// ------------------------------------------------------------ setup / ops --

/**
 * Run once from the editor (Run -> setup). Creates the Requests sheet,
 * the Status dropdown and a random key, and prints the key to the log.
 */
function setup() {
  var sheet = sheet_(SHEET_REQUESTS, REQUEST_COLUMNS);
  var statusCol = columnOf_('status');
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(STATUSES, true).setAllowInvalid(false).build();
  sheet.getRange(2, statusCol, sheet.getMaxRows() - 1, 1).setDataValidation(rule);
  sheet.getRange(1, columnOf_('text')).setNote('Request text as the person wrote it.');
  sheet.setColumnWidth(columnOf_('text'), 420);
  sheet.setColumnWidth(columnOf_('error_text'), 300);

  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('PEER_KEY')) {
    props.setProperty('PEER_KEY', Utilities.getUuid().replace(/-/g, ''));
  }
  Logger.log('PEER_KEY = ' + props.getProperty('PEER_KEY'));
}

/** Run from the editor to cut off an old key; then update PEER settings. */
function rotateKey() {
  var key = Utilities.getUuid().replace(/-/g, '');
  PropertiesService.getScriptProperties().setProperty('PEER_KEY', key);
  Logger.log('new PEER_KEY = ' + key);
}

/** Simple trigger: stamps the time when the head changes Status by hand. */
function onEdit(e) {
  var range = e && e.range;
  if (!range || range.getSheet().getName() !== SHEET_REQUESTS || range.getRow() < 2) return;
  if (range.getColumn() !== columnOf_('status')) return;
  range.getSheet().getRange(range.getRow(), columnOf_('status_changed_at')).setValue(new Date());
}
