# -*- coding: utf-8 -*-
"""Fixes of 2026-11-19: PEER runs by path, error summary / clipping, usage state."""
import datetime
import os

from peer_feedback import outbox, payload, runs, sent, usage

from test_feedback import home  # noqa: F401  (fixture)
from test_stage2 import PEER_SCRIPT, iso, rec, write

AUTHOR_SCRIPT = (u'C:\\Users\\user\\Desktop\\Plagin PEER v2.0\\PyRevitV2.extension\\'
                 u'PEER.tab\\Feedback.panel\\MyRequests.pushbutton\\script.py')

# as pyRevit 5.2 writes it for an IronPython import failure (shortened)
REAL_TRACE = (u'Traceback (most recent call last):\n'
              u'  File "C:\\...\\MyRequests.pushbutton\\script.py", line 16, in <module>\n'
              u'ImportError: No module named Data\n'
              u'IronPython.Runtime.Exceptions.ImportException: No module named Data\n'
              u'   at IronPython.Runtime.Importer.Import(CodeContext context)\n')
PYREVIT_TRACE = (u'IronPython Traceback:\n'
                 u'Traceback (most recent call last):\n'
                 u'  File "C:\\...\\script.py", line 5, in <module>\n'
                 u'Exception: boom\n\n'
                 u'Script Executor Traceback:\n'
                 u'System.Exception: boom\n   at x.y()\n')


def test_peer_run_found_by_path_whatever_the_extension_name(tmp_path):
    now = datetime.datetime.utcnow()
    d = str(tmp_path)
    write(d, 'pyRevit_s_telemetry.json', [
        rec(iso(now - datetime.timedelta(minutes=3)), code=2, ext=u'PyRevitV2',
            path=AUTHOR_SCRIPT, trace=REAL_TRACE),
        rec(iso(now - datetime.timedelta(minutes=2)), code=2, ext=u'PEER', path=PEER_SCRIPT),
        rec(iso(now - datetime.timedelta(minutes=1)), code=2, ext=u'pyRevitTools',
            path=u'C:\\x\\pyRevit.tab\\Tools.panel\\Sync.pushbutton\\script.py'),
    ])
    fails = runs.recent_failures(d)
    assert [f['button'] for f in fails] == [u'Walls / WallRebar2D', u'Feedback / MyRequests']


def test_summary_real_formats():
    assert runs.summary(REAL_TRACE) == u'ImportError: No module named Data'
    assert runs.summary(PYREVIT_TRACE) == u'Exception: boom'
    assert runs.summary(u'IronPython Traceback:\nsomething odd') == u'something odd'
    assert runs.summary(u'') == u''


def test_report_text_keeps_the_error_line_and_the_end():
    long_trace = (u'Traceback (most recent call last):\n'
                  + u''.join(u'  File "f%d.py", line 1, in g\n' % i for i in range(400))
                  + u'ValueError: the real problem\n'
                  + u''.join(u'   at Frame%d()\n' % i for i in range(400))
                  + u'   at TheInnermost()')
    out = runs.report_text(long_trace, 3000)
    assert len(out) <= 3000
    assert out.startswith(u'ValueError: the real problem')
    assert out.endswith(u'TheInnermost()')
    assert u'[...]' in out
    assert runs.report_text(REAL_TRACE) == REAL_TRACE.strip()


def test_make_request_clips_error_in_the_middle():
    req = payload.make_request({'topic': 'bug', 'text': u''},
                               {'error_text': u'A' * 6000 + u'END'})
    assert len(req['error_text']) <= payload.MAX_TEXT
    assert req['error_text'].startswith(u'A') and req['error_text'].endswith(u'END')


def test_rejected_shows_as_not_delivered():
    entries = [{'id': 'a', 'created_at': u'2026-11-19T10:00:00Z', 'topic': 'bug', 'text': u't'}]
    rows = sent.table_rows(entries, set(), {}, lambda x: x, rejected_ids=set(['a']))
    assert rows[0][4] == sent.REJECTED


def test_usage_full_outbox_does_not_skip_days(home, tmp_path, monkeypatch):
    tele = tmp_path / 'tele'
    tele.mkdir()
    now = datetime.datetime.utcnow()
    write(str(tele), 'pyRevit_s_telemetry.json', [
        dict(rec(iso(now - datetime.timedelta(days=3))), username=u'dima'),
        dict(rec(iso(now - datetime.timedelta(days=2))), username=u'dima'),
    ])
    monkeypatch.setattr(outbox, 'MAX_ITEMS', 0)          # queue full
    today = usage.local_day(now)
    usage.queue_pending(folder=str(tele), today=today, tab_dir=str(tmp_path))
    first = usage.local_day(now - datetime.timedelta(days=3))
    # nothing could be queued: the watermark stays before the first unsent day
    assert usage.read_state()['last_day'] == (first - datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(outbox, 'MAX_ITEMS', 1000)
    n = usage.queue_pending(folder=str(tele), today=today, tab_dir=str(tmp_path))
    assert n == 2
    assert usage.read_state()['last_day'] == (today - datetime.timedelta(days=1)).isoformat()
