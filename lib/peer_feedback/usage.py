# -*- coding: utf-8 -*-
"""Button usage for the group's table (stage 3): one row per day, person,
computer and button with the number of runs and failures.

Source: PEER runs in pyRevit's file telemetry (runs.py). Only finished
days are sent - yesterday and older, never today - so a day is complete
when it goes and is sent once. On every Revit start, in the background:

    queue_pending()  finished days not sent yet -> outbox (action 'usage')
                     + this PEER's button list  -> outbox (action 'buttons')
    client.flush()   outbox -> receiver ("Usage" / "Buttons" sheets)

The outbox keeps the items until the receiver took them, and the receiver
drops rows it already has (row id = hash of date|user|computer|button).
What is sent: date, Revit user name, computer name, button, counts, the
one-line name of the last error, Revit and PEER versions. No project
names, no file paths, no texts.
"""

import datetime
import hashlib
import io
import json
import os
import threading

from peer_feedback import config, outbox, payload, runs

STATE_FILE = 'usage_state.json'
FIRST_DAYS = 30        # first upload: at most this many days back
MAX_ROWS = 500         # rows in one outbox item


def _hash(*parts):
    raw = u'|'.join(payload.u(p) for p in parts).encode('utf-8')
    return payload.u(hashlib.sha1(raw).hexdigest()[:32])


def local_day(utc):
    return runs.to_local(utc).date()


def day_rows(day_runs, day, machine, peer_version, user_fallback=u''):
    """Runs of one local day -> rows, one per (user, button), sorted."""
    groups = {}
    for r in day_runs:
        user = r.get('user') or user_fallback
        key = (user, r['button'] or r['script'])
        g = groups.setdefault(key, {'runs': 0, 'failures': 0, 'last_error': u'',
                                    'last_fail': None, 'revit': u''})
        g['runs'] += 1
        g['revit'] = g['revit'] or r.get('revit', u'')
        if r['code'] not in runs.OK_CODES:
            g['failures'] += 1
            if g['last_fail'] is None or r['time'] > g['last_fail']:
                g['last_fail'] = r['time']
                g['last_error'] = runs.summary(r['error'])
    date = day.strftime('%Y-%m-%d')
    rows = []
    for (user, button), g in sorted(groups.items()):
        rows.append({
            'id': _hash(date, user, machine, button),
            'date': payload.u(date),
            'user': payload.clip(user, payload.MAX_FIELD),
            'machine': payload.clip(machine, payload.MAX_FIELD),
            'button': payload.clip(button, payload.MAX_FIELD),
            'runs': g['runs'],
            'failures': g['failures'],
            'last_error': payload.clip(g['last_error'], payload.MAX_FIELD),
            'revit_version': payload.u(g['revit']),
            'peer_version': payload.u(peer_version),
        })
    return rows


# ------------------------------------------------------------------ state --
def _state_path(base=None):
    return os.path.join(base or config.local_dir(), STATE_FILE)


def read_state(base=None):
    try:
        with io.open(_state_path(base), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def write_state(state, base=None):
    d = os.path.dirname(_state_path(base))
    if not os.path.isdir(d):
        os.makedirs(d)
    text = json.dumps(state, sort_keys=True)
    if not isinstance(text, type(u'')):
        text = text.decode('utf-8')
    with io.open(_state_path(base), 'w', encoding='utf-8') as f:
        f.write(text)


def _parse_day(text):
    try:
        return datetime.datetime.strptime(text, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- pending --
def pending(all_runs, today, last_day, machine, peer_version, user_fallback=u''):
    """[(day, rows)] for finished days after last_day (None = first time).

    Days without runs give no rows but still count as done.
    """
    first = today - datetime.timedelta(days=FIRST_DAYS)
    if last_day is not None and last_day + datetime.timedelta(days=1) > first:
        first = last_day + datetime.timedelta(days=1)
    by_day = {}
    for r in all_runs:
        d = local_day(r['time'])
        if first <= d < today:
            by_day.setdefault(d, []).append(r)
    return [(d, day_rows(by_day[d], d, machine, peer_version, user_fallback))
            for d in sorted(by_day)]


def machine_name():
    return payload.u(os.environ.get('COMPUTERNAME') or os.environ.get('HOSTNAME') or u'')


def user_name():
    return payload.u(os.environ.get('USERNAME') or os.environ.get('USER') or u'')


def queue_pending(folder=None, base=None, today=None, tab_dir=None):
    """Put finished days and the button list into the outbox. -> rows queued."""
    today = today or local_day(datetime.datetime.utcnow())
    state = read_state(base)
    last_day = _parse_day(state.get('last_day'))
    yesterday = today - datetime.timedelta(days=1)
    if last_day is not None and last_day >= yesterday:
        return 0
    since = datetime.datetime.utcnow() - datetime.timedelta(days=FIRST_DAYS + 2)
    all_runs = runs.load_runs(folder or runs.telemetry_dir(), since)
    machine, peer = machine_name(), config.peer_version()
    n = 0
    done = yesterday
    for day, rows in pending(all_runs, today, last_day, machine, peer, user_name()):
        queued = True
        for k in range(0, len(rows), MAX_ROWS):
            chunk = rows[k:k + MAX_ROWS]
            item_id = _hash(u'usage', day.isoformat(), machine, k)
            if outbox.put({'action': 'usage', 'data': {'id': item_id, 'rows': chunk}}, base) is None:
                queued = False      # outbox full: this day goes next time
                break
            n += len(chunk)
        if not queued:
            done = day - datetime.timedelta(days=1)
            break
    if not tab_dir:
        tab_dir = os.path.join(config.ext_dir(), 'PEER.tab')
        if not os.path.isdir(tab_dir) and os.path.isdir(os.path.join(config.ext_dir(), 'PEER_dev.tab')):
            tab_dir = os.path.join(config.ext_dir(), 'PEER_dev.tab')
    names = payload.list_buttons(tab_dir)
    if names:
        item_id = _hash(u'buttons', today.isoformat(), machine)
        outbox.put({'action': 'buttons', 'data': {'id': item_id, 'names': names}}, base)
    state['last_day'] = done.isoformat()
    write_state(state, base)
    return n


def upload_async():
    """queue_pending() + flush() in a background thread (Revit start)."""
    from peer_feedback import client

    def run():
        try:
            queue_pending()
        except Exception as ex:
            client._log(u'usage queue failed: {0}'.format(ex))
        try:
            client.flush()
        except Exception as ex:
            client._log(u'flush failed: {0}'.format(ex))

    t = threading.Thread(target=run, name='peer_feedback_usage')
    t.daemon = True
    t.start()
    return t
