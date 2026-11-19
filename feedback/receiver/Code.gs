/**
 * PEER feedback receiver - Google Apps Script bound to the group's Google Sheet.
 *
 * Accepts POST {v, key, action, data} from PEER (lib/peer_feedback/client.py)
 * and appends one row per request to the "Requests" sheet.
 *
 * It can ONLY:
 *   - answer a ping,
 *   - append a request row (duplicates by id are ignored),
 *   - return status / comment of the request ids it is asked about
 *     (ids are random 128-bit values known only to their author's PEER),
 *   - append daily button usage rows ("Usage") and new button names
 *     ("Buttons"; minutes saved per run are filled in by hand).
 * It never returns other rows or the request texts, so a leaked address +
 * key lets someone add rows, nothing more. Change the key in Script Properties
 * (PEER_KEY) and in PEER settings to cut them off.
 *
 * Sheets:
 *   Inbox     - the page for people: newest first, readable columns, Status and
 *               Comment are edited HERE (copied to Requests by onSheetEdit)
 *   Summary   - weekly summary (weeklySummary)
 *   Buttons   - PEER buttons + minutes saved per run (filled by hand)
 *   Usage     - daily button runs (raw)
 *   Requests  - every request with all fields (raw, for analysis / Claude)
 *
 * Setup: feedback/SETUP.md. Run setup() once from the editor (and again after
 * pasting a new version: it is safe to re-run).
 */

var SHEET_REQUESTS = 'Requests';

// Column order on the sheet. Keys = fields of lib/peer_feedback/payload.py.
// Status / Comment / Status changed are the head's columns, filled by hand.
// New columns are only ever added at the END (an existing sheet gets the
// header cell added by sheet_()), so old rows stay aligned.
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
  ['status_changed_at', 'Status changed'],
  ['attachments', 'Pictures']
];

var SHEET_USAGE = 'Usage';
var USAGE_COLUMNS = [
  ['id', 'ID'],
  ['received_at', 'Received'],
  ['date', 'Date'],
  ['user', 'User'],
  ['machine', 'Computer'],
  ['button', 'Button'],
  ['runs', 'Runs'],
  ['failures', 'Failures'],
  ['last_error', 'Last error'],
  ['revit_version', 'Revit'],
  ['peer_version', 'PEER']
];

var SHEET_BUTTONS = 'Buttons';
var BUTTON_COLUMNS = [
  ['button', 'Button'],
  ['minutes', 'Minutes saved per run'],
  ['notes', 'Notes'],
  ['added_at', 'Added']
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
      case 'status':
        return json_(statuses_(body.data || {}));
      case 'usage':
        return json_(saveUsage_(body.data || {}));
      case 'buttons':
        return json_(saveButtons_(body.data || {}));
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

  var att = d.attachments || [];
  if (!Array.isArray(att) || att.length > MAX_ATTACHMENTS) {
    return { ok: false, error: 'bad_request', detail: 'bad attachments' };
  }

  // a retry of a request that is already in: no second copy of its pictures
  if (findRow_(sheet_(SHEET_REQUESTS, REQUEST_COLUMNS), id) > 0) {
    return { ok: true, id: id, duplicate: true };
  }
  // pictures go to Drive before the lock: it can take a few seconds
  var links = saveAttachments_(id, att);

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
      if (k === 'attachments') return links.join('\n');
      return cell_(d[k]);
    });
    sheet.appendRow(row);
    try {
      addInboxRow_(rowObject_(REQUEST_COLUMNS, row));
    } catch (err) {
      // the raw row is in; the readable page can be rebuilt by setup()
      Logger.log('Inbox row failed: ' + err);
    }
    return { ok: true, id: id };
  } finally {
    lock.releaseLock();
  }
}

// ------------------------------------------------------------ pictures --

var MAX_ATTACHMENTS = 5;
var MAX_ATTACHMENT_B64 = 2000000;
var ATTACH_TYPES = { 'image/jpeg': 'jpg', 'image/png': 'png' };

/** Drive folder for pictures: Script Property ATTACH_FOLDER_ID, else a new one. */
function attachFolder_() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('ATTACH_FOLDER_ID');
  if (id) {
    try { return DriveApp.getFolderById(id); } catch (err) { /* deleted: make a new one */ }
  }
  var folder = DriveApp.createFolder('PEER Feedback pictures');
  props.setProperty('ATTACH_FOLDER_ID', folder.getId());
  return folder;
}

/**
 * [{name, type, data (base64)}] -> list of Drive links. A picture that
 * cannot be saved gives a line "(picture N not saved: ...)" instead: the
 * request itself is never lost because of a picture.
 */
function saveAttachments_(id, att) {
  if (!att.length) return [];
  var out = [];
  var folder;
  try {
    folder = attachFolder_();
  } catch (err) {
    return ['(pictures not saved: ' + String(err).slice(0, 200) + ')'];
  }
  var stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  att.forEach(function (a, i) {
    try {
      var ext = ATTACH_TYPES[a && a.type];
      var data = String((a && a.data) || '');
      if (!ext || !data || data.length > MAX_ATTACHMENT_B64) throw new Error('bad picture');
      var name = stamp + ' ' + id.slice(0, 8) + ' ' + (i + 1) + '.' + ext;
      var blob = Utilities.newBlob(Utilities.base64Decode(data), a.type, name);
      out.push(folder.createFile(blob).getUrl());
    } catch (err) {
      out.push('(picture ' + (i + 1) + ' not saved: ' + String(err).slice(0, 200) + ')');
    }
  });
  return out;
}

// ----------------------------------------------------------------- status --

var MAX_STATUS_IDS = 100;

/** {ids: [...]} -> {ok, statuses: {id: {status, comment, changed}}} for those ids only. */
function statuses_(d) {
  var ids = Array.isArray(d.ids) ? d.ids.slice(0, MAX_STATUS_IDS) : [];
  var wanted = {};
  ids.forEach(function (id) {
    if (/^[0-9a-f]{32}$/.test(String(id))) wanted[id] = true;
  });
  var out = {};
  var sheet = book_().getSheetByName(SHEET_REQUESTS);
  if (!sheet || sheet.getLastRow() < 2 || !Object.keys(wanted).length) {
    return { ok: true, statuses: out };
  }
  var n = sheet.getLastRow() - 1;
  var cId = columnOf_('id'), cSt = columnOf_('status'),
      cCm = columnOf_('comment'), cCh = columnOf_('status_changed_at');
  var rows = sheet.getRange(2, 1, n, REQUEST_COLUMNS.length).getValues();
  rows.forEach(function (r) {
    var id = String(r[cId - 1]);
    if (!wanted[id]) return;
    var ch = r[cCh - 1];
    out[id] = {
      status: String(r[cSt - 1] || ''),
      comment: String(r[cCm - 1] || ''),
      changed: Object.prototype.toString.call(ch) === '[object Date]' ? ch.toISOString() : String(ch || '')
    };
  });
  return { ok: true, statuses: out };
}

// ------------------------------------------------------------------ usage --

var MAX_USAGE_ROWS = 500;
var MAX_BUTTONS = 500;

/** {rows: [...]} -> appends rows whose id is not on "Usage" yet. */
function saveUsage_(d) {
  if (!Array.isArray(d.rows) || d.rows.length > MAX_USAGE_ROWS) {
    return { ok: false, error: 'bad_request', detail: 'bad rows' };
  }
  var good = d.rows.filter(function (r) {
    return r && /^[0-9a-f]{32}$/.test(String(r.id)) &&
      /^\d{4}-\d\d-\d\d$/.test(String(r.date)) && String(r.button || '').trim();
  });
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sheet = sheet_(SHEET_USAGE, USAGE_COLUMNS);
    var have = columnSet_(sheet, 1);
    var now = new Date();
    var add = [];
    good.forEach(function (r) {
      if (have[r.id]) return;
      have[r.id] = true;
      add.push(USAGE_COLUMNS.map(function (c) {
        var k = c[0];
        if (k === 'received_at') return now;
        if (k === 'runs' || k === 'failures') return Math.max(0, parseInt(r[k], 10) || 0);
        return cell_(r[k]);
      }));
    });
    if (add.length) {
      sheet.getRange(sheet.getLastRow() + 1, 1, add.length, USAGE_COLUMNS.length).setValues(add);
    }
    return { ok: true, added: add.length, skipped: d.rows.length - add.length };
  } finally {
    lock.releaseLock();
  }
}

/** {names: [...]} -> adds button names missing on "Buttons" (minutes stay empty). */
function saveButtons_(d) {
  if (!Array.isArray(d.names) || d.names.length > MAX_BUTTONS) {
    return { ok: false, error: 'bad_request', detail: 'bad names' };
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sheet = sheet_(SHEET_BUTTONS, BUTTON_COLUMNS);
    var have = columnSet_(sheet, 1);
    var now = new Date();
    var add = [];
    d.names.forEach(function (n) {
      var name = cell_(n).trim();
      if (!name || have[name]) return;
      have[name] = true;
      add.push([name, '', '', now]);
    });
    if (add.length) {
      sheet.getRange(sheet.getLastRow() + 1, 1, add.length, BUTTON_COLUMNS.length).setValues(add);
    }
    return { ok: true, added: add.length };
  } finally {
    lock.releaseLock();
  }
}

/** {value: true} for the values of one column below the header. */
function columnSet_(sheet, col) {
  var out = {};
  var last = sheet.getLastRow();
  if (last < 2) return out;
  sheet.getRange(2, col, last - 1, 1).getValues().forEach(function (r) {
    out[String(r[0])] = true;
  });
  return out;
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
    sheet.getRange(1, 1, 1, columns.length).setFontWeight('bold').setBackground('#F3F4F6');
  } else if (sheet.getLastColumn() < columns.length) {
    // a column added in a newer version: give it its header
    for (var i = sheet.getLastColumn(); i < columns.length; i++) {
      sheet.getRange(1, i + 1).setValue(columns[i][1]).setFontWeight('bold');
    }
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
  sheet.setTabColor('#9CA3AF');
  sheet.getRange(1, 1).setNote('Raw data: every field of every request, for analysis. ' +
    'Read and answer requests on the Inbox sheet - Status and Comment are copied here.');
  var statusCol = columnOf_('status');
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(STATUSES, true).setAllowInvalid(false).build();
  sheet.getRange(2, statusCol, sheet.getMaxRows() - 1, 1).setDataValidation(rule);
  sheet.getRange(1, columnOf_('text')).setNote('Request text as the person wrote it.');
  sheet.setColumnWidth(columnOf_('text'), 420);
  sheet.setColumnWidth(columnOf_('error_text'), 300);

  sheet_(SHEET_USAGE, USAGE_COLUMNS);
  attachFolder_();   // asks for the Drive permission now, not on the first picture
  var buttons = sheet_(SHEET_BUTTONS, BUTTON_COLUMNS);
  buttons.setColumnWidth(1, 280);
  buttons.getRange(1, 2).setNote('How many minutes one run of this button saves compared with doing it by hand. Used for "time saved" in the weekly summary.');

  var inbox = inbox_();
  formatInbox_(inbox);
  if (inbox.getLastRow() < 2) rebuildInbox_();
  orderSheets_();

  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('PEER_KEY')) {
    props.setProperty('PEER_KEY', Utilities.getUuid().replace(/-/g, ''));
  }
  Logger.log('PEER_KEY = ' + props.getProperty('PEER_KEY'));

  installEditTrigger();
}

/**
 * Installable "on edit" trigger for onSheetEdit (a simple onEdit does not run
 * in a standalone script). Google sometimes answers "server error" here: three
 * tries, then the manual steps in the log - setup never fails because of it.
 * Can be run on its own from the editor.
 */
function installEditTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'onSheetEdit') ScriptApp.deleteTrigger(t);
  });
  var id = book_().getId();
  var last;
  for (var i = 0; i < 3; i++) {
    try {
      ScriptApp.newTrigger('onSheetEdit').forSpreadsheet(id).onEdit().create();
      Logger.log('Edit trigger installed.');
      return true;
    } catch (err) {
      last = err;
      Utilities.sleep(2000);
    }
  }
  Logger.log('Edit trigger NOT installed (' + last + '). Run installEditTrigger again in a ' +
    'few minutes, or add it by hand: Triggers (clock icon) -> Add trigger -> function ' +
    'onSheetEdit, event source "From spreadsheet", event type "On edit" -> Save.');
  return false;
}

/** Run from the editor to cut off an old key; then update PEER settings. */
function rotateKey() {
  var key = Utilities.getUuid().replace(/-/g, '');
  PropertiesService.getScriptProperties().setProperty('PEER_KEY', key);
  Logger.log('new PEER_KEY = ' + key);
}

/**
 * Installed by setup(). Status / Comment edited on Inbox -> copied to the
 * request's row on Requests with the time of the change. (Status edited on
 * Requests directly still gets its time stamp.)
 */
function onSheetEdit(e) {
  var range = e && e.range;
  if (!range || range.getRow() < 2) return;
  var sheet = range.getSheet();
  var name = sheet.getName();
  var first = range.getRow(), last = range.getLastRow ? range.getLastRow() : first;
  var c1 = range.getColumn(), c2 = range.getLastColumn ? range.getLastColumn() : c1;
  if (name === SHEET_INBOX) {
    var cSt = inboxCol_('status'), cCm = inboxCol_('comment');
    if (c2 < Math.min(cSt, cCm) || c1 > Math.max(cSt, cCm)) return;
    var raw = book_().getSheetByName(SHEET_REQUESTS);
    if (!raw) return;
    for (var r = first; r <= last; r++) {
      var vals = sheet.getRange(r, 1, 1, INBOX_COLUMNS.length).getValues()[0];
      var id = String(vals[0]);
      var rr = findRow_(raw, id);
      if (!rr) continue;
      raw.getRange(rr, columnOf_('status')).setValue(vals[cSt - 1] || STATUSES[0]);
      raw.getRange(rr, columnOf_('comment')).setValue(vals[cCm - 1] || '');
      raw.getRange(rr, columnOf_('status_changed_at')).setValue(new Date());
    }
  } else if (name === SHEET_REQUESTS) {
    var col = columnOf_('status');
    if (col < c1 || col > c2) return;
    for (var q = first; q <= last; q++) {
      sheet.getRange(q, columnOf_('status_changed_at')).setValue(new Date());
    }
  }
}

// ================================================================= Inbox --
//
// The readable page. One row per request, NEWEST ON TOP, labels instead of
// codes, the error as one line, pictures as links. Column A (ID) is hidden:
// it ties the row to Requests.

var SHEET_INBOX = 'Inbox';
var INBOX_COLUMNS = [
  ['id', 'ID', 60],
  ['received_at', 'Received', 115],
  ['user', 'From', 140],
  ['topic', 'Topic', 130],
  ['button', 'Button', 170],
  ['text', 'Request', 380],
  ['pictures', 'Pictures', 95],
  ['error', 'Error', 220],
  ['frequency', 'How often', 95],
  ['duration', 'Time each time', 110],
  ['project', 'Project', 150],
  ['status', 'Status', 110],
  ['comment', 'Comment for the author', 240]
];
var FREQ_LABELS = { daily: 'Every day', weekly: 'Every week', rare: 'Rarely' };
var DUR_LABELS = { lt5: 'Up to 5 min', '5to30': '5-30 min', gt30: 'More than 30 min' };
var STATUS_COLORS = {
  'New': '#F3F4F6', 'Accepted': '#DBEAFE', 'In progress': '#FEF3C7',
  'Done': '#DCFCE7', 'Rejected': '#FEE2E2'
};

function inboxCol_(key) {
  for (var i = 0; i < INBOX_COLUMNS.length; i++) {
    if (INBOX_COLUMNS[i][0] === key) return i + 1;
  }
  return 0;
}

function inbox_() {
  return sheet_(SHEET_INBOX, INBOX_COLUMNS);
}

function rowObject_(columns, row) {
  var o = {};
  columns.forEach(function (c, i) { o[c[0]] = row[i]; });
  return o;
}

/** The line that names the error: 'Exception: no wall selected'. */
function errorLine_(text) {
  var lines = String(text || '').split('\n');
  for (var i = 0; i < lines.length; i++) {
    var l = lines[i];
    if (l.trim() && !/^\s/.test(l) && !/^Traceback/.test(l)) return l.trim().slice(0, 200);
  }
  return '';
}

/** Raw request (column keys of REQUEST_COLUMNS) -> Inbox cell values. */
function inboxValues_(r) {
  var links = String(r.attachments || '').split('\n').filter(function (x) { return x; });
  var text = String(r.text || '');
  if (text === '(error report)') text = '';
  return INBOX_COLUMNS.map(function (c) {
    switch (c[0]) {
      case 'id': return String(r.id);
      case 'received_at': return r.received_at;
      case 'user': return String(r.user || '').replace(/\s*\(.*\)$/, '');
      case 'topic': return TOPIC_LABELS[r.topic] || String(r.topic || '');
      case 'pictures': return links.length ? links.length + (links.length === 1 ? ' picture' : ' pictures') : '';
      case 'error': return errorLine_(r.error_text);
      case 'frequency': return FREQ_LABELS[r.frequency] || '';
      case 'duration': return DUR_LABELS[r.duration] || '';
      case 'status': return r.status || STATUSES[0];
      case 'text': return text;
      default: return r[c[0]] === undefined ? '' : r[c[0]];
    }
  });
}

/** Insert one request under the header (newest on top) and style the row. */
function addInboxRow_(raw) {
  var sh = inbox_();
  sh.insertRowAfter(1);
  var n = INBOX_COLUMNS.length;
  var range = sh.getRange(2, 1, 1, n);
  // the new row copies the header's look: reset it
  range.setFontWeight('normal').setFontColor('#1F2937').setBackground(null)
    .setFontSize(10).setVerticalAlignment('top').setWrap(true);
  range.setValues([inboxValues_(raw)]);
  sh.getRange(2, inboxCol_('received_at')).setNumberFormat('dd.mm.yyyy hh:mm');
  sh.getRange(2, inboxCol_('status')).setDataValidation(statusRule_())
    .setHorizontalAlignment('center');
  var links = String(raw.attachments || '').split('\n').filter(function (x) { return /^https?:/.test(x); });
  if (links.length) {
    // "1  2  3": each number opens its picture
    var label = links.map(function (x, i) { return String(i + 1); }).join('  ');
    var b = SpreadsheetApp.newRichTextValue().setText(label);
    var pos = 0;
    links.forEach(function (url, i) {
      var t = String(i + 1);
      b = b.setLinkUrl(pos, pos + t.length, url);
      pos += t.length + 2;
    });
    sh.getRange(2, inboxCol_('pictures')).setRichTextValue(b.build());
  }
  if (raw.topic === 'bug') {
    sh.getRange(2, inboxCol_('topic')).setFontColor('#B91C1C').setFontWeight('bold');
  }
}

function statusRule_() {
  return SpreadsheetApp.newDataValidation()
    .requireValueInList(STATUSES, true).setAllowInvalid(false).build();
}

/** Header, widths, hidden ID, frozen header, filter, status colours. Safe to re-run. */
function formatInbox_(sh) {
  var n = INBOX_COLUMNS.length;
  var header = sh.getRange(1, 1, 1, n);
  header.setValues([INBOX_COLUMNS.map(function (c) { return c[1]; })]);
  header.setBackground('#1F2937').setFontColor('#FFFFFF').setFontWeight('bold')
    .setFontSize(10).setVerticalAlignment('middle').setWrap(true);
  sh.setRowHeight(1, 34);
  sh.setFrozenRows(1);
  INBOX_COLUMNS.forEach(function (c, i) { sh.setColumnWidth(i + 1, c[2]); });
  sh.hideColumns(1);
  sh.setTabColor('#2563EB');
  var rows = Math.max(sh.getMaxRows() - 1, 1);
  sh.getRange(2, inboxCol_('status'), rows, 1).setDataValidation(statusRule_());
  var statusRange = sh.getRange(2, inboxCol_('status'), rows, 1);
  sh.setConditionalFormatRules(Object.keys(STATUS_COLORS).map(function (st) {
    return SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(st)
      .setBackground(STATUS_COLORS[st]).setRanges([statusRange]).build();
  }));
  if (!sh.getFilter()) sh.getRange(1, 1, sh.getMaxRows(), n).createFilter();
}

/** Fill Inbox from Requests (first setup on a table that already has requests). */
function rebuildInbox_() {
  var raw = readSheet_(SHEET_REQUESTS, REQUEST_COLUMNS);
  raw.forEach(function (r) { addInboxRow_(r); });   // oldest first -> newest ends on top
}

function orderSheets_() {
  var book = book_();
  [SHEET_INBOX, SHEET_SUMMARY, SHEET_BUTTONS, SHEET_USAGE, SHEET_REQUESTS].forEach(function (name, i) {
    var sh = book.getSheetByName(name);
    if (!sh) return;
    book.setActiveSheet(sh);
    book.moveActiveSheet(i + 1);
  });
  var inbox = book.getSheetByName(SHEET_INBOX);
  if (inbox) book.setActiveSheet(inbox);
}

// ======================================================== weekly summary --
//
// weeklySummary() runs every Monday morning (setupWeeklySummary() installs
// the trigger): reads Requests, Usage and Buttons, writes the "Summary"
// sheet and e-mails it to the owner (or to Script Property SUMMARY_EMAIL,
// comma separated). Numbers are for the group: no ranking of people.

var SHEET_SUMMARY = 'Summary';
var DAY_MS = 24 * 3600 * 1000;
// "how often" -> times per week; "time per occurrence" -> minutes
var FREQ_PER_WEEK = { daily: 5, weekly: 1, rare: 0.25, '': 1 };
var DURATION_MIN = { lt5: 3, '5to30': 15, gt30: 45, '': 10 };
var TOPIC_LABELS = {
  automation: 'Automation', improve: 'Improve a button', bug: 'Bug', idea: 'Idea',
  routine: 'Routine', template: 'Template & families', howto: 'How-to question',
  standard: 'Office standard'
};
var CLOSED = { Done: true, Rejected: true };

/** Run once from the editor: Monday 07:00 (project time zone) trigger. */
function setupWeeklySummary() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'weeklySummary') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('weeklySummary').timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(7).create();
  Logger.log('Weekly summary: every Monday at 07:00. Sending a test now.');
  weeklySummary();
}

function weeklySummary() {
  var data = {
    requests: readSheet_(SHEET_REQUESTS, REQUEST_COLUMNS),
    usage: readSheet_(SHEET_USAGE, USAGE_COLUMNS),
    buttons: readSheet_(SHEET_BUTTONS, BUTTON_COLUMNS)
  };
  var s = buildSummary_(data, new Date());
  writeSummarySheet_(s);
  var to = PropertiesService.getScriptProperties().getProperty('SUMMARY_EMAIL') ||
    Session.getEffectiveUser().getEmail();
  if (to) {
    MailApp.sendEmail({ to: to, subject: s.title, htmlBody: renderHtml_(s) });
  }
  return s;
}

function readSheet_(name, columns) {
  var sheet = book_().getSheetByName(name);
  if (!sheet || sheet.getLastRow() < 2) return [];
  return sheet.getRange(2, 1, sheet.getLastRow() - 1, columns.length).getValues()
    .map(function (r) {
      var o = {};
      columns.forEach(function (c, i) { o[c[0]] = r[i]; });
      return o;
    });
}

// ------------------------------------------------------------- pure part --

function asDate_(v) {
  if (Object.prototype.toString.call(v) === '[object Date]') return v;
  var d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
}

function short_(text, n) {
  var s = String(text || '').replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function lastLine_(button) {
  var parts = String(button || '').split(' / ');
  return parts[parts.length - 1];
}

function count_(list, key) {
  var out = {};
  list.forEach(function (x) { var k = key(x); out[k] = (out[k] || 0) + 1; });
  return out;
}

function distinct_(list, key) {
  var seen = {};
  list.forEach(function (x) { seen[key(x)] = true; });
  return Object.keys(seen).length;
}

function fmtH_(h) { return (Math.round(h * 10) / 10).toString(); }

/**
 * data: {requests, usage, buttons} as row objects (column keys);
 * -> {title, period, blocks: [{title, note, header, rows}]}.
 */
function buildSummary_(data, now) {
  var weekAgo = new Date(now.getTime() - 7 * DAY_MS);
  var monthAgo = new Date(now.getTime() - 30 * DAY_MS);
  var reqs = data.requests.map(function (r) {
    var o = {}; for (var k in r) o[k] = r[k];
    o.received = asDate_(r.received_at);
    o.changed = asDate_(r.status_changed_at) || o.received;
    return o;
  });
  var week = reqs.filter(function (r) { return r.received && r.received >= weekAgo; });
  var usage = data.usage.map(function (u) {
    return { date: asDate_(u.date), button: String(u.button), user: String(u.user),
             runs: Number(u.runs) || 0, failures: Number(u.failures) || 0,
             last_error: String(u.last_error || '') };
  }).filter(function (u) { return u.date; });
  var usageWeek = usage.filter(function (u) { return u.date >= weekAgo; });
  var usageMonth = usage.filter(function (u) { return u.date >= monthAgo; });
  var minutes = {};
  data.buttons.forEach(function (b) {
    var m = Number(b.minutes);
    if (String(b.minutes) !== '' && !isNaN(m)) minutes[String(b.button)] = m;
  });
  var blocks = [];

  // 1. requests this week
  var byTopic = count_(week, function (r) { return r.topic; });
  blocks.push({
    title: '1. Requests this week',
    note: week.length + ' requests from ' + distinct_(week, function (r) { return r.user; }) + ' people.',
    header: ['Topic', 'Requests'],
    rows: Object.keys(byTopic).sort(function (a, b) { return byTopic[b] - byTopic[a]; })
      .map(function (t) { return [TOPIC_LABELS[t] || t, byTopic[t]]; })
  });

  // 2. top-3 to automate: open requests by lost hours a week
  var groups = {};
  reqs.filter(function (r) {
    return !CLOSED[r.status] && (r.topic === 'automation' || r.topic === 'routine' || r.topic === 'improve');
  }).forEach(function (r) {
    var key = r.topic === 'improve' && r.button ? 'improve|' + r.button : 'req|' + r.id;
    var g = groups[key] || (groups[key] = { what: '', users: {}, hours: 0, n: 0 });
    g.what = r.topic === 'improve' && r.button ? 'Improve ' + r.button + ': ' + short_(r.text, 80)
      : (TOPIC_LABELS[r.topic] || r.topic) + ': ' + short_(r.text, 100);
    g.users[r.user] = true;
    g.n += 1;
    g.hours += (FREQ_PER_WEEK[r.frequency] !== undefined ? FREQ_PER_WEEK[r.frequency] : 1) *
      (DURATION_MIN[r.duration] !== undefined ? DURATION_MIN[r.duration] : 10) / 60;
  });
  var top = Object.keys(groups).map(function (k) { return groups[k]; })
    .sort(function (a, b) { return b.hours - a.hours; }).slice(0, 3);
  blocks.push({
    title: '2. Top 3 to automate',
    note: 'Open requests, lost hours a week = how often × time per occurrence, summed over the people asking.',
    header: ['Request', 'People', 'Hours lost / week'],
    rows: top.map(function (g) { return [g.what, Object.keys(g.users).length, fmtH_(g.hours)]; })
  });

  // 3. bugs this week by button
  var bugs = {};
  week.filter(function (r) { return r.topic === 'bug'; }).forEach(function (r) {
    var k = r.button || '(no button)';
    var g = bugs[k] || (bugs[k] = { n: 0, users: {}, error: '' });
    g.n += 1; g.users[r.user] = true;
    g.error = g.error || short_(String(r.error_text || '').split('\n').filter(function (l) {
      return l && !/^\s/.test(l) && !/^Traceback/.test(l);
    })[0] || '', 120);
  });
  blocks.push({
    title: '3. Bugs this week',
    note: 'Urgent = reported by 2+ people or 3+ times.',
    header: ['Button', 'Reports', 'People', 'Urgent', 'Error'],
    rows: Object.keys(bugs).sort(function (a, b) { return bugs[b].n - bugs[a].n; }).map(function (k) {
      var g = bugs[k], p = Object.keys(g.users).length;
      return [k, g.n, p, (p >= 2 || g.n >= 3) ? 'yes' : '', g.error];
    })
  });

  // 4. usage, last 30 days
  var runs = {}, people = {};
  usageMonth.forEach(function (u) {
    runs[u.button] = (runs[u.button] || 0) + u.runs;
    (people[u.button] = people[u.button] || {})[u.user] = true;
  });
  var unused = data.buttons.map(function (b) { return String(b.button); })
    .filter(function (b) { return b && !runs[b]; });
  blocks.push({
    title: '4. Usage, last 30 days',
    note: unused.length ? 'No runs in 30 days: ' + unused.join(', ') + '.' : 'Every button was used.',
    header: ['Button', 'Runs', 'People'],
    rows: Object.keys(runs).sort(function (a, b) { return runs[b] - runs[a]; }).slice(0, 10)
      .map(function (b) { return [b, runs[b], Object.keys(people[b]).length]; })
  });

  // 5. errors nobody reported this week
  var reported = {};
  week.filter(function (r) { return r.topic === 'bug'; }).forEach(function (r) { reported[r.button] = true; });
  var silent = {};
  usageWeek.filter(function (u) { return u.failures > 0 && !reported[u.button]; }).forEach(function (u) {
    var g = silent[u.button] || (silent[u.button] = { f: 0, users: {}, error: '' });
    g.f += u.failures; g.users[u.user] = true; g.error = g.error || u.last_error;
  });
  blocks.push({
    title: '5. Errors without a bug report',
    note: 'Buttons that failed this week and nobody sent a bug.',
    header: ['Button', 'Failures', 'People', 'Last error'],
    rows: Object.keys(silent).sort(function (a, b) { return silent[b].f - silent[a].f; }).map(function (k) {
      return [k, silent[k].f, Object.keys(silent[k].users).length, short_(silent[k].error, 120)];
    })
  });

  // 6. hidden signals
  var names = data.buttons.map(function (b) { return lastLine_(b.button); })
    .filter(function (n) { return n && n.length >= 4; });
  var signals = [];
  week.forEach(function (r) {
    if (r.topic !== 'automation' && r.topic !== 'idea' && r.topic !== 'routine') return;
    var text = String(r.text || '').toLowerCase();
    names.forEach(function (n) {
      if (text.indexOf(n.toLowerCase()) >= 0) {
        signals.push(['Asks for what may exist', n, short_(r.text, 100)]);
      }
    });
  });
  week.filter(function (r) { return r.topic === 'howto'; }).forEach(function (r) {
    signals.push(['How-to question', r.button || '', short_(r.text, 100)]);
  });
  week.filter(function (r) { return r.topic === 'template' || r.topic === 'standard'; }).forEach(function (r) {
    signals.push([TOPIC_LABELS[r.topic], '', short_(r.text, 100)]);
  });
  blocks.push({
    title: '6. Signals',
    note: 'Requests that mention an existing button, how-to questions, template and standard gaps.',
    header: ['Signal', 'Button', 'Request'],
    rows: signals
  });

  // 7. time saved this week
  var saved = 0, noMinutes = {};
  usageWeek.forEach(function (u) {
    if (minutes[u.button] === undefined) { if (u.runs) noMinutes[u.button] = true; return; }
    saved += Math.max(0, u.runs - u.failures) * minutes[u.button];
  });
  var nm = Object.keys(noMinutes);
  blocks.push({
    title: '7. Time saved this week',
    note: fmtH_(saved / 60) + ' hours (successful runs × "Minutes saved per run" on the Buttons sheet).' +
      (nm.length ? ' No minutes set for: ' + nm.join(', ') + '.' : ''),
    header: [], rows: []
  });

  // 8. status of requests
  var byStatus = count_(reqs, function (r) { return r.status || 'New'; });
  var stale = reqs.filter(function (r) {
    return (r.status || 'New') === 'New' && r.received && r.received < weekAgo;
  });
  blocks.push({
    title: '8. Status of requests',
    note: STATUSES.map(function (s) { return s + ': ' + (byStatus[s] || 0); }).join(' · ') +
      '. No answer for more than 7 days: ' + stale.length + '.',
    header: ['Received', 'Topic', 'Request'],
    rows: stale.map(function (r) {
      return [Utilities.formatDate(r.received, Session.getScriptTimeZone(), 'dd.MM.yyyy'),
              TOPIC_LABELS[r.topic] || r.topic, short_(r.text, 100)];
    })
  });

  var period = Utilities.formatDate(weekAgo, Session.getScriptTimeZone(), 'dd.MM') + '–' +
    Utilities.formatDate(now, Session.getScriptTimeZone(), 'dd.MM.yyyy');
  return { title: 'PEER weekly summary ' + period, period: period, blocks: blocks };
}

function esc_(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderHtml_(s) {
  var h = ['<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#222">',
           '<h2 style="margin:0 0 12px">' + esc_(s.title) + '</h2>'];
  s.blocks.forEach(function (b) {
    h.push('<h3 style="margin:18px 0 4px">' + esc_(b.title) + '</h3>');
    if (b.note) h.push('<p style="margin:0 0 6px;color:#555">' + esc_(b.note) + '</p>');
    if (b.header.length && b.rows.length) {
      h.push('<table style="border-collapse:collapse">');
      h.push('<tr>' + b.header.map(function (c) {
        return '<th style="text-align:left;border-bottom:1px solid #999;padding:3px 10px 3px 0">' + esc_(c) + '</th>';
      }).join('') + '</tr>');
      b.rows.forEach(function (r) {
        h.push('<tr>' + r.map(function (c) {
          return '<td style="border-bottom:1px solid #eee;padding:3px 10px 3px 0;vertical-align:top">' + esc_(c) + '</td>';
        }).join('') + '</tr>');
      });
      h.push('</table>');
    } else if (b.header.length) {
      h.push('<p style="margin:0;color:#888">Nothing this week.</p>');
    }
  });
  h.push('</div>');
  return h.join('\n');
}

function writeSummarySheet_(s) {
  var book = book_();
  var sheet = book.getSheetByName(SHEET_SUMMARY) || book.insertSheet(SHEET_SUMMARY);
  sheet.clear();
  var out = [[s.title]];
  var titles = [], headers = [], notes = [];
  s.blocks.forEach(function (b) {
    out.push(['']);
    out.push([b.title]); titles.push(out.length);
    if (b.note) { out.push([b.note]); notes.push(out.length); }
    if (b.header.length) {
      out.push(b.header); headers.push([out.length, b.header.length]);
      if (!b.rows.length) out.push(['Nothing this week.']);
      b.rows.forEach(function (r) { out.push(r); });
    }
  });
  var width = out.reduce(function (m, r) { return Math.max(m, r.length); }, 1);
  out = out.map(function (r) {
    var row = r.map(function (c) { return cell_(c); });
    while (row.length < width) row.push('');
    return row;
  });
  sheet.getRange(1, 1, out.length, width).setValues(out);
  sheet.getRange(1, 1, out.length, width).setFontSize(10).setVerticalAlignment('top').setWrap(true);
  sheet.getRange(1, 1).setFontWeight('bold').setFontSize(15);
  titles.forEach(function (r) { sheet.getRange(r, 1).setFontWeight('bold').setFontSize(12).setFontColor('#1D4ED8'); });
  notes.forEach(function (r) { sheet.getRange(r, 1).setFontColor('#6B7280').setFontStyle('italic'); });
  headers.forEach(function (h) {
    sheet.getRange(h[0], 1, 1, h[1]).setFontWeight('bold').setBackground('#F3F4F6');
  });
  sheet.setColumnWidth(1, 380);
  for (var c = 2; c <= width; c++) sheet.setColumnWidth(c, 140);
  sheet.setTabColor('#16A34A');
  // notes and titles are long single cells: let them run over the empty cells
  titles.concat(notes).concat([1]).forEach(function (r) { sheet.getRange(r, 1).setWrap(false); });
}
