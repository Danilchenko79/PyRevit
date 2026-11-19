# -*- coding: utf-8 -*-
"""Stage 3: daily button usage from telemetry -> outbox -> receiver."""
import datetime
import os

from peer_feedback import client, outbox, runs, usage

from test_feedback import FakeReceiver, home, receiver  # noqa: F401  (fixtures)
from test_stage2 import PEER_SCRIPT, TRACE, iso, rec, write

WINTAG = u'C:\\x\\PEER.tab\\Documentation.panel\\Tools.stack\\WinTag.pushbutton\\script.py'


def run(t, code=0, path=PEER_SCRIPT, user=u'dima', error=u''):
    return {'time': t, 'button': u'', 'script': u'', 'doc': u'', 'user': user,
            'revit': u'2024', 'code': code, 'error': error,
            **({'button': u'Walls / WallRebar2D'} if path == PEER_SCRIPT else {'button': u'Documentation / WinTag'})}


def test_day_rows_counts_and_last_error():
    day = datetime.date(2026, 11, 18)
    t = datetime.datetime(2026, 11, 18, 9, 0)
    rows = usage.day_rows([
        run(t), run(t + datetime.timedelta(hours=1), code=2, error=u'Traceback...\nException: old'),
        run(t + datetime.timedelta(hours=2), code=2, error=TRACE),
        run(t, path=WINTAG), run(t, path=WINTAG, user=u'anna'),
    ], day, u'PC-01', u'9b6bdda')
    by = dict(((r['user'], r['button']), r) for r in rows)
    w = by[(u'dima', u'Walls / WallRebar2D')]
    assert (w['runs'], w['failures'], w['last_error']) == (3, 2, u'Exception: no wall selected')
    assert w['date'] == u'2026-11-18' and w['machine'] == u'PC-01' and w['peer_version'] == u'9b6bdda'
    assert by[(u'anna', u'Documentation / WinTag')]['runs'] == 1
    assert len(rows) == 3
    # same key -> same id, so a resend never doubles a row
    again = usage.day_rows([run(t)], day, u'PC-01', u'x')
    assert again[0]['id'] == w['id'] and len(w['id']) == 32
    assert usage.day_rows([run(t)], day, u'PC-02', u'x')[0]['id'] != w['id']


def test_pending_only_finished_days_after_watermark():
    today = datetime.date(2026, 11, 19)
    def at(d, h=12):
        # midday local -> UTC; the day must survive the conversion
        local = datetime.datetime(2026, 11, d, h)
        return local - (runs.to_local(datetime.datetime(2026, 1, 1)) - datetime.datetime(2026, 1, 1))
    all_runs = [run(at(15)), run(at(17)), run(at(18)), run(at(19))]
    days = [d for d, _ in usage.pending(all_runs, today, None, u'PC', u'v')]
    assert days == [datetime.date(2026, 11, d) for d in (15, 17, 18)]       # never today
    days = [d for d, _ in usage.pending(all_runs, today, datetime.date(2026, 11, 17), u'PC', u'v')]
    assert days == [datetime.date(2026, 11, 18)]
    long_ago = [run(at(1) - datetime.timedelta(days=60))]
    assert usage.pending(long_ago, today, None, u'PC', u'v') == []


def test_queue_pending_once_per_day(home, tmp_path):
    tele = tmp_path / 'tele'
    tele.mkdir()
    now = datetime.datetime.utcnow()
    write(str(tele), 'pyRevit_s_telemetry.json', [
        dict(rec(iso(now - datetime.timedelta(days=2)), code=2, trace=TRACE), username=u'dima'),
        dict(rec(iso(now - datetime.timedelta(days=2)), path=WINTAG), username=u'dima'),
        rec(iso(now)),                                                       # today: not yet
    ])
    tab = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'PEER.tab')
    n = usage.queue_pending(folder=str(tele), tab_dir=tab)
    assert n == 2
    items = [it for _, it in outbox.items()]
    acts = sorted(it['action'] for it in items)
    assert acts == ['buttons', 'usage']
    rows = [it for it in items if it['action'] == 'usage'][0]['data']['rows']
    assert sorted(r['button'] for r in rows) == [u'Documentation / WinTag', u'Walls / WallRebar2D']
    assert all(set(r) >= {'id', 'date', 'user', 'machine', 'runs', 'failures'} for r in rows)
    names = [it for it in items if it['action'] == 'buttons'][0]['data']['names']
    assert u'Feedback / Contact' in names and u'Feedback / MyRequests' in names
    # second start the same day: nothing new
    assert usage.queue_pending(folder=str(tele), tab_dir=tab) == 0
    assert outbox.count() == 2


def test_old_receiver_keeps_usage_and_does_not_block_requests(receiver):
    """A receiver without 'usage' refuses it; requests behind it still go out."""
    outbox.put({'action': 'usage', 'data': {'id': 'e' * 32, 'rows': []}})
    os.utime(outbox.items()[0][0], (1, 1))                     # oldest in the queue
    orig = receiver.server.RequestHandlerClass.do_POST

    def do_post(handler):
        import json
        n = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(n)
        if json.loads(body.decode('utf-8'))['action'] == 'usage':
            out = b'{"ok": false, "error": "bad_request", "detail": "unknown action"}'
            handler.send_response(200)
            handler.send_header('Content-Length', str(len(out)))
            handler.end_headers()
            handler.wfile.write(out)
            return
        import io
        handler.rfile = io.BytesIO(body)
        orig(handler)
    receiver.server.RequestHandlerClass.do_POST = do_post
    from peer_feedback import payload
    from test_feedback import CTX
    req = payload.make_request({'topic': 'idea', 'text': u'x'}, CTX)
    outbox.put({'action': 'request', 'data': req})
    sent, left = client.flush(receiver.cfg())
    assert (sent, left) == (1, 1)                              # usage kept, request delivered
    assert req['id'] in receiver.rows
