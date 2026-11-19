# -*- coding: utf-8 -*-
"""submit / flush / ping: outbox + transport + config.

The receiver answers {"ok": true, ...} or {"ok": false, "error": <code>}:
    bad_key      - key or address is wrong here: keep the item, retry later
    bad_request  - the item itself is broken: drop it (logged), never retry
    anything else / no answer - keep the item, retry later
"""

import datetime
import io
import os
import threading

from peer_feedback import config, outbox, payload
from peer_feedback.transport import SendError, post_json

PROTOCOL = 1
_flush_lock = threading.Lock()

SENT = 'sent'
QUEUED = 'queued'
NOT_CONFIGURED = 'not_configured'


def _log(line):
    try:
        base = os.environ.get('TEMP') or os.path.expanduser('~')
        d = os.path.join(base, 'peer_revit_logs')
        if not os.path.isdir(d):
            os.makedirs(d)
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with io.open(os.path.join(d, 'peer_feedback.log'), 'a', encoding='utf-8') as f:
            f.write(u'{0} {1}\n'.format(stamp, payload.u(line)))
    except Exception:
        pass


def send(action, data, cfg=None):
    """One POST. -> answer dict (ok true/false). Raises SendError."""
    cfg = cfg or config.load()
    if not config.is_configured(cfg):
        raise SendError(u'receiver not configured')
    body = {'v': PROTOCOL, 'key': cfg['key'], 'action': action, 'data': data}
    timeout = cfg['timeout_s']
    if data.get('attachments'):
        # pictures: upload + saving them to Drive takes longer
        timeout = max(timeout, 90)
    return post_json(cfg['url'], body, timeout)


def _deliver(item, cfg):
    """-> 'ok' / 'drop' / 'retry' (no answer) / 'refused' (answered no) (+ reason)."""
    try:
        ans = send(item['action'], item['data'], cfg)
    except SendError as ex:
        return 'retry', payload.u(ex)
    if ans.get('ok'):
        return 'ok', u''
    err = payload.u(ans.get('error'))
    detail = payload.u(ans.get('detail'))
    # a receiver older than this PEER does not know the action yet: keep the
    # item until the head of the group updates the receiver
    if err == 'bad_request' and detail != u'unknown action':
        return 'drop', err + u' ' + detail
    return 'refused', (err + u' ' + detail).strip()


def submit(action, data, cfg=None, base=None):
    """Queue the item, try to send it now. -> SENT / QUEUED / NOT_CONFIGURED."""
    cfg = cfg or config.load()
    item = {'action': action, 'data': data}
    path = outbox.put(item, base)
    if not config.is_configured(cfg):
        return NOT_CONFIGURED
    res, why = _deliver(item, cfg)
    if res == 'ok':
        if path:
            outbox.remove(path)
        return SENT
    if res == 'drop':
        _log(u'dropped {0} {1}: {2}'.format(action, data.get('id'), why))
        if path:
            outbox.remove(path)
        # a broken item is our bug; for the person it is "not delivered"
        return QUEUED
    _log(u'queued {0} {1}: {2}'.format(action, data.get('id'), why))
    return QUEUED


def flush(cfg=None, base=None):
    """Send everything in the outbox, oldest first. -> (sent, left).

    Stops at the first network failure: the rest would fail the same way.
    An item the receiver refused stays queued, the rest still go out.
    """
    cfg = cfg or config.load()
    if not config.is_configured(cfg):
        return 0, outbox.count(base)
    if not _flush_lock.acquire(False):
        return 0, outbox.count(base)
    sent = 0
    try:
        for path, item in outbox.items(base):
            if not isinstance(item, dict) or 'data' not in item:
                continue
            res, why = _deliver(item, cfg)
            if res == 'ok':
                outbox.remove(path)
                sent += 1
            elif res == 'drop':
                _log(u'dropped {0}: {1}'.format(os.path.basename(path), why))
                outbox.remove(path)
            elif res == 'refused':
                _log(u'kept {0}: {1}'.format(os.path.basename(path), why))
            else:
                _log(u'flush stopped: {0}'.format(why))
                break
    finally:
        _flush_lock.release()
    if sent:
        _log(u'flushed {0}'.format(sent))
    return sent, outbox.count(base)


def flush_async():
    """flush() in a background thread: Revit start is not slowed down."""
    if outbox.count() == 0:
        return None

    def run():
        try:
            flush()
        except Exception as ex:
            _log(u'flush failed: {0}'.format(ex))

    t = threading.Thread(target=run, name='peer_feedback_flush')
    t.daemon = True
    t.start()
    return t


def statuses(ids, cfg=None, batch=100):
    """{id: {'status', 'comment', 'changed'}} for these request ids.

    Raises SendError (no connection / receiver not configured / refused).
    The receiver answers only for the ids asked - never other rows.
    """
    cfg = cfg or config.load()
    out = {}
    ids = [i for i in ids if i]
    for k in range(0, len(ids), batch):
        ans = send('status', {'ids': ids[k:k + batch]}, cfg)
        if not ans.get('ok'):
            raise SendError(u'receiver refused: {0}'.format(ans.get('error')))
        for rid, st in (ans.get('statuses') or {}).items():
            if isinstance(st, dict):
                out[rid] = st
    return out


def ping(cfg=None):
    """-> (ok, text) for the Shift+Click connection check."""
    cfg = cfg or config.load()
    if not config.is_configured(cfg):
        return False, u'Receiver address or key is not set.'
    start = datetime.datetime.now()
    try:
        ans = send('ping', {'peer_version': config.peer_version()}, cfg)
    except SendError as ex:
        return False, u'No answer: {0}'.format(ex)
    ms = int((datetime.datetime.now() - start).total_seconds() * 1000)
    if ans.get('ok'):
        return True, u'Receiver answered in {0} ms.'.format(ms)
    return False, u'Receiver refused: {0}'.format(ans.get('error'))
