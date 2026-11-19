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

  sheet_(SHEET_USAGE, USAGE_COLUMNS);
  var buttons = sheet_(SHEET_BUTTONS, BUTTON_COLUMNS);
  buttons.setColumnWidth(1, 280);
  buttons.getRange(1, 2).setNote('How many minutes one run of this button saves compared with doing it by hand. Used for "time saved" in the weekly summary.');

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
  s.blocks.forEach(function (b) {
    out.push(['']);
    out.push([b.title]);
    if (b.note) out.push([b.note]);
    if (b.header.length) {
      out.push(b.header);
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
  sheet.getRange(1, 1).setFontWeight('bold').setFontSize(13);
}
