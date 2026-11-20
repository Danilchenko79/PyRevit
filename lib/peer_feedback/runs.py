# -*- coding: utf-8 -*-
"""PEER button runs from pyRevit's own file telemetry.

pyRevit catches script exceptions itself (C#), so a script cannot hand its
error to anyone. But with file telemetry on, pyRevit writes one record per
run into <dir>/pyRevit_<session>_telemetry.json (a JSON array rewritten
after each run), with:
    commandextension  'PEER'
    scriptpath        ...\\PEER.tab\\Walls.panel\\WallRebar2D.pushbutton\\script.py
    resultcode        0 ok, 1 sys.exit, 11 delayed run requested, else failed
    trace.message     full IronPython + CLR traceback of a failure
    timestamp         2026-11-19T16:15:56.9528+02:00 or ...Z (UTC)
    docname           project title

ensure_telemetry() (from startup.py) switches it on. The rest is pure
python, IronPython 2.7 and CPython 3. Nothing here is sent anywhere: only
an error the person picks in Contact goes out with a bug report.
"""

import datetime
import io
import json
import os
import re

from peer_feedback import config, payload

EXTENSION = u'PEER'
TAB = u'PEER.tab'
OK_CODES = (0, 1, 11)
KEEP_DAYS = 90
_TS = re.compile(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?$')


def own_dir():
    return os.path.join(config.local_dir(), 'telemetry')


# ------------------------------------------------------------- in pyRevit --
def _user_config():
    from pyrevit.userconfig import user_config
    return user_config


def telemetry_dir():
    """Folder pyRevit writes telemetry files to (configured one, else ours)."""
    try:
        d = _user_config().telemetry_file_dir
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    return own_dir()


def ensure_telemetry():
    """Turn pyRevit file telemetry on (once per computer). -> folder used.

    A folder somebody already configured is kept. Applied to the running
    session too, so the first Revit start already records runs.
    """
    from pyrevit import telemetry
    cfg = _user_config()
    folder = None
    try:
        d = cfg.telemetry_file_dir
        if d and os.path.isdir(d):
            folder = d
    except Exception:
        pass
    changed = False
    if folder is None:
        folder = own_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        try:
            telemetry.set_telemetry_file_dir(folder)
        except TypeError:  # older signature
            cfg.telemetry_file_dir = folder
        changed = True
    try:
        active = bool(cfg.telemetry_status)
    except Exception:
        active = False
    if not active:
        telemetry.set_telemetry_state(True)
        changed = True
    if changed:
        try:
            cfg.save_changes()
        except Exception:
            pass
        try:
            telemetry.setup_telemetry()
        except Exception:
            pass
    cleanup(own_dir())
    return folder


def cleanup(folder, keep_days=KEEP_DAYS):
    """Delete our telemetry files older than keep_days. -> count deleted."""
    if not os.path.isdir(folder):
        return 0
    limit = _now_ts() - keep_days * 86400
    n = 0
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if name.endswith('_telemetry.json') and os.path.getmtime(path) < limit:
                os.remove(path)
                n += 1
        except OSError:
            pass
    return n


# ------------------------------------------------------------------- pure --
def _now_ts():
    import time
    return time.time()


def parse_time(ts):
    """pyRevit timestamp -> naive UTC datetime, or None."""
    m = _TS.match(payload.u(ts).strip())
    if not m:
        return None
    t = datetime.datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S')
    tz = m.group(2)
    if tz is None:
        # no zone: local time
        return t - (datetime.datetime.now() - datetime.datetime.utcnow())
    if tz == 'Z':
        return t
    sign = -1 if tz[0] == '-' else 1
    hh, mm = int(tz[1:3]), int(tz[-2:])
    return t - sign * datetime.timedelta(hours=hh, minutes=mm)


def to_local(utc):
    delta = datetime.datetime.now() - datetime.datetime.utcnow()
    # round to whole minutes: the two clock reads differ by microseconds
    delta = datetime.timedelta(minutes=int(round(delta.total_seconds() / 60.0)))
    return utc + delta


def _files(folder, since_ts=None):
    try:
        names = [n for n in os.listdir(folder) if n.endswith('_telemetry.json')]
    except OSError:
        return []
    out = []
    for n in names:
        path = os.path.join(folder, n)
        try:
            mt = os.path.getmtime(path)
        except OSError:
            continue
        if since_ts is None or mt >= since_ts:
            out.append((mt, path))
    out.sort(reverse=True)
    return [p for _, p in out]


def _is_peer(rec):
    """A run of a PEER button: script under PEER.tab, or extension named PEER.

    The extension name depends on the install folder: PEER.extension at the
    colleagues (install.bat), PyRevitV2.extension in the author's copy - so
    the script path decides first.
    """
    parts = payload.u(rec.get('scriptpath')).replace(u'\\', u'/').lower().split(u'/')
    if TAB.lower() in parts or u'peer_dev.tab' in parts:
        return True
    ext = payload.u(rec.get('commandextension')).strip().lower()
    return ext in (EXTENSION.lower(), u'peer_dev')


def load_runs(folder, since=None, max_files=200):
    """PEER run records newer than `since` (naive UTC), newest first.

    Each: {'time' (UTC), 'button', 'script', 'doc', 'user', 'revit', 'code', 'error'}.
    A file pyRevit is rewriting right now may be half written: skipped.
    """
    since_ts = None
    if since is not None:
        epoch = datetime.datetime(1970, 1, 1)
        since_ts = (since - epoch).total_seconds() - 86400  # mtime is local; 1 day slack
    runs = []
    for path in _files(folder, since_ts)[:max_files]:
        try:
            with io.open(path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
        except (IOError, OSError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        for rec in data:
            if not isinstance(rec, dict) or not _is_peer(rec):
                continue
            t = parse_time(rec.get('timestamp'))
            if t is None or (since is not None and t < since):
                continue
            trace = rec.get('trace') or {}
            try:
                code = int(rec.get('resultcode', 0))
            except (TypeError, ValueError):
                code = 0
            script = payload.u(rec.get('scriptpath'))
            runs.append({
                'time': t,
                'button': payload.button_from_script(script) or payload.u(rec.get('commandname')),
                'script': _short_script(script),
                'doc': payload.u(rec.get('docname')),
                'user': payload.u(rec.get('username')),
                'revit': payload.u(rec.get('revit')),
                'code': code,
                'error': payload.u(trace.get('message') if isinstance(trace, dict) else u''),
            })
    runs.sort(key=lambda r: r['time'], reverse=True)
    return runs


def _short_script(path):
    """Path from the .tab folder on: no user name / install folder."""
    parts = [p for p in payload.u(path).replace(u'\\', u'/').split(u'/') if p]
    for i, p in enumerate(parts):
        if p.endswith(u'.tab'):
            return u'/'.join(parts[i:])
    return parts[-1] if parts else u''


def failures(runs):
    return [r for r in runs if r['code'] not in OK_CODES]


def recent_failures(folder=None, days=7, limit=10):
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    return failures(load_runs(folder or telemetry_dir(), since))[:limit]


# 'ImportError: ...', 'Exception: ...', 'Autodesk.Revit.Exceptions.X: ...'
_ERR_LINE = re.compile(r'^[\w.]*(?:Error|Exception|Exit|Warning|Interrupt)(?::|$)')
# section headers of pyRevit / IronPython traces, never the error itself
_HEADER = re.compile(r'^(IronPython |CPython |Script Executor |\w+ )?Traceback\b|:\s*$')


def summary(error):
    """'Exception: boom' - the line that names the error, for a list.

    First the first unindented 'SomethingError: ...' line, else the first
    unindented line that is not a 'Traceback' header.
    """
    lines = [l for l in payload.u(error).splitlines() if l.strip() and not l[:1].isspace()]
    for line in lines:
        s = line.strip()
        if _ERR_LINE.match(s):
            return s[:200]
    for line in lines:
        s = line.strip()
        if not _HEADER.search(s):
            return s[:200]
    return u''


def report_text(error, limit=payload.MAX_TEXT):
    """Error text for a bug report, at most `limit` chars.

    A long trace is cut in the middle (head = IronPython frames, tail = the
    innermost .NET frames) and starts with the summary line, so the error
    itself is never cut off.
    """
    text = payload.u(error).strip()
    if len(text) <= limit:
        return text
    head = summary(text)
    body = payload.clip_middle(text, limit - len(head) - 2)
    return head + u'\n\n' + body if head else body


def label(fail):
    """'14:32  Walls / WallRebar2D - Exception: boom' (local time)."""
    t = to_local(fail['time'])
    today = to_local(datetime.datetime.utcnow()).date()
    when = t.strftime('%H:%M') if t.date() == today else t.strftime('%d.%m %H:%M')
    s = summary(fail['error'])
    return u'{0}  {1}{2}'.format(when, fail['button'] or fail['script'],
                                 u' - ' + s if s else u'')
