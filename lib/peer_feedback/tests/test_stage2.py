# -*- coding: utf-8 -*-
"""Stage 2: errors from pyRevit telemetry, sent log, statuses."""
import datetime
import io
import json
import os

import pytest

from peer_feedback import client, payload, runs, sent
from peer_feedback.transport import SendError

from test_feedback import CTX, FakeReceiver, home, receiver  # noqa: F401  (fixtures)

PEER_SCRIPT = (u'C:\\Users\\dima\\AppData\\Roaming\\pyRevit\\Extensions\\PEER.extension\\'
               u'PEER.tab\\Walls.panel\\WallRebar2D.pushbutton\\script.py')
TRACE = (u'Traceback (most recent call last):\n'
         u'  File "...\\WallRebar2D.pushbutton\\script.py", line 120, in <module>\n'
         u'Exception: no wall selected\n\n'
         u'System.Exception: no wall selected\n   at Microsoft.Scripting...')


def rec(ts, code=0, ext=u'PEER', path=PEER_SCRIPT, trace=u''):
    return {'timestamp': ts, 'commandextension': ext, 'commandname': u'Wall Rebar 2D',
            'scriptpath': path, 'docname': u'בניין A', 'resultcode': code,
            'trace': {'engine': {'type': 'ironpython'}, 'message': trace}}


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.1234Z')


def write(folder, name, records):
    with io.open(os.path.join(folder, name), 'w', encoding='utf-8') as f:
        f.write(json.dumps(records, ensure_ascii=False))


# ---------------------------------------------------------------- naming --

@pytest.mark.parametrize('path, name', [
    (PEER_SCRIPT, u'Walls / WallRebar2D'),
    (u'/x/PEER.tab/Documentation.panel/Tools.stack/WinTag.pushbutton/script.py',
     u'Documentation / WinTag'),
    (u'C:\\x\\PEER.tab\\Reinforcement.panel\\RebarShape.pulldown\\PulldownButton03.pushbutton\\script.py',
     u'Reinforcement / RebarShape / PulldownButton03'),
    (u'C:\\pyRevit\\pyRevitTools.extension\\pyRevit.tab\\Tools.panel\\Sync.pushbutton\\script.py',
     u'Tools / Sync'),
    (u'C:\\somewhere\\script.py', u''),
])
def test_button_from_script(path, name):
    assert payload.button_from_script(path) == name


def test_button_names_match_list():
    """A failure's button must be found in Contact's button list."""
    tab = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'PEER.tab')
    assert u'Walls / WallRebar2D' in payload.list_buttons(tab)


# ------------------------------------------------------------------ times --

def test_parse_time_zones():
    assert runs.parse_time(u'2026-11-19T10:00:00.1234Z') == datetime.datetime(2026, 11, 19, 10, 0, 0)
    assert runs.parse_time(u'2026-11-19T12:00:00.1234+02:00') == datetime.datetime(2026, 11, 19, 10, 0, 0)
    assert runs.parse_time(u'2026-11-19T05:00:00-05:00') == datetime.datetime(2026, 11, 19, 10, 0, 0)
    assert runs.parse_time(u'garbage') is None
    assert runs.parse_time(None) is None


OTHER = u'C:\\pyRevit\\pyRevitTools.extension\\pyRevit.tab\\Tools.panel\\Sync.pushbutton\\script.py'


# ------------------------------------------------------------------- runs --

def test_load_runs_and_failures(tmp_path):
    now = datetime.datetime.utcnow()
    d = str(tmp_path)
    write(d, 'pyRevit_s1_telemetry.json', [
        rec(iso(now - datetime.timedelta(minutes=30))),                          # ok
        rec(iso(now - datetime.timedelta(minutes=20)), code=2, trace=TRACE),     # failure
        rec(iso(now - datetime.timedelta(minutes=10)), code=2, ext=u'pyRevitTools', path=OTHER),
        rec(iso(now - datetime.timedelta(minutes=5)), code=1),                   # sys.exit = ok
        rec(iso(now - datetime.timedelta(days=30)), code=2, trace=TRACE),        # too old
    ])
    with open(os.path.join(d, 'pyRevit_s2_telemetry.json'), 'w') as f:
        f.write('[{"timestamp": "2026-')                                         # half written
    write(d, 'notes.json', [rec(iso(now), code=2)])                              # not telemetry

    since = now - datetime.timedelta(days=7)
    all_runs = runs.load_runs(d, since)
    assert [r['code'] for r in all_runs] == [1, 2, 0]                            # newest first
    fails = runs.failures(all_runs)
    assert len(fails) == 1
    f = fails[0]
    assert f['button'] == u'Walls / WallRebar2D'
    assert f['script'] == u'PEER.tab/Walls.panel/WallRebar2D.pushbutton/script.py'   # no user path
    assert f['doc'] == u'בניין A'
    assert f['error'] == TRACE
    assert runs.summary(f['error']) == u'Exception: no wall selected'
    assert u'Walls / WallRebar2D - Exception: no wall selected' in runs.label(f)
    assert runs.recent_failures(d) == fails


def test_recent_failures_empty_folder(tmp_path):
    assert runs.recent_failures(str(tmp_path / 'missing')) == []


def test_cleanup_deletes_only_old_telemetry(tmp_path, monkeypatch):
    d = str(tmp_path)
    write(d, 'pyRevit_old_telemetry.json', [])
    write(d, 'pyRevit_new_telemetry.json', [])
    write(d, 'other.json', [])
    old = 1000000000
    os.utime(os.path.join(d, 'pyRevit_old_telemetry.json'), (old, old))
    os.utime(os.path.join(d, 'other.json'), (old, old))
    assert runs.cleanup(d) == 1
    assert sorted(os.listdir(d)) == ['other.json', 'pyRevit_new_telemetry.json']


# ---------------------------------------------------- error-only bug report --

def test_bug_with_error_needs_no_text():
    assert payload.validate({'topic': 'bug', 'text': u'', 'button': u'Walls / WallRebar2D',
                             'error_text': TRACE}) == []
    assert payload.validate({'topic': 'bug', 'text': u'', 'button': u'Walls / WallRebar2D',
                             'error_text': u''}) == ['err_text']
    ctx = dict(CTX, error_script=u'PEER.tab/Walls.panel/WallRebar2D.pushbutton/script.py',
               error_text=TRACE)
    r = payload.make_request({'topic': 'bug', 'text': u'', 'button': u'Walls / WallRebar2D'}, ctx)
    assert r['text'] == u'(error report)'
    assert r['error_text'] == TRACE
    assert r['error_script'].startswith(u'PEER.tab/')


# --------------------------------------------------------------- sent log --

def test_sent_log_add_merge_rows(tmp_path):
    base = str(tmp_path)
    a = payload.make_request({'topic': 'automation', 'text': u'x' * 500}, CTX,
                             request_id='a' * 32, created_at=u'2026-11-18T10:00:00Z')
    b = payload.make_request({'topic': 'bug', 'text': u'crash', 'button': u'Walls / WallRebar2D'},
                             CTX, request_id='b' * 32, created_at=u'2026-11-19T10:00:00Z')
    sent.add(a, base)
    sent.add(b, base)
    sent.add(b, base)                                     # same id once
    items = sent.items(base)
    assert [x['id'] for x in items] == ['b' * 32, 'a' * 32]
    assert len(items[1]['text']) == sent.TEXT

    changed = sent.merge({'a' * 32: {'status': u'Accepted', 'comment': u'Next week',
                                     'changed': u'2026-11-19T12:00:00.000Z'}}, base)
    assert changed == ['a' * 32]
    assert sent.merge({'a' * 32: {'status': u'Accepted', 'comment': u'Next week'}}, base) == []

    rows = sent.table_rows(sent.items(base), {'b' * 32}, {'bug': u'Bug', 'automation': u'Automation'},
                           lambda t: t[:10])
    assert rows[0] == (u'2026-11-19', u'Bug', u'Walls / WallRebar2D', u'crash', sent.WAITING, u'')
    assert rows[1][1] == u'Automation' and rows[1][4:] == (u'Accepted', u'Next week')


def test_sent_log_survives_broken_file(tmp_path):
    base = str(tmp_path)
    with open(sent.path(base), 'w') as f:
        f.write('{broken')
    assert sent.items(base) == []
    sent.add(payload.make_request({'topic': 'idea', 'text': u'y'}, CTX), base)
    assert len(sent.items(base)) == 1


# --------------------------------------------------------------- statuses --

def test_statuses_only_asked_ids(receiver):
    receiver.status = {'a' * 32: {'status': 'Done', 'comment': 'ok', 'changed': ''},
                       'c' * 32: {'status': 'New', 'comment': '', 'changed': ''}}
    got = client.statuses(['a' * 32, 'b' * 32], receiver.cfg())
    assert got == {'a' * 32: {'status': 'Done', 'comment': 'ok', 'changed': ''}}


def test_statuses_batches(receiver):
    receiver.status = dict(('%032x' % i, {'status': 'New'}) for i in range(5))
    calls = receiver.calls
    got = client.statuses(['%032x' % i for i in range(5)], receiver.cfg(), batch=2)
    assert len(got) == 5 and receiver.calls == calls + 3


def test_statuses_old_receiver_raises(receiver):
    receiver.knows_status = False
    with pytest.raises(SendError) as e:
        client.statuses(['a' * 32], receiver.cfg())
    assert 'bad_request' in str(e.value)
