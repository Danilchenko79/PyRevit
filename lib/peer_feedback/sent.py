# -*- coding: utf-8 -*-
"""This person's requests and their last known status: %APPDATA%/PEER/sent.json.

The table belongs to the head of the group; PEER keeps only what it needs
to show "My requests": id, date, topic, button, the start of the text and
the status / comment last fetched from the receiver.
Pure python: IronPython 2.7 and CPython 3.
"""

import io
import json
import os

from peer_feedback import config, payload

KEEP = 300          # newest requests kept in the file
TEXT = 200          # chars of the request text kept
WAITING = u'Waiting to send'
REJECTED = u'Not delivered'


def path(base=None):
    return os.path.join(base or config.local_dir(), 'sent.json')


def _read(base):
    try:
        with io.open(path(base), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return [x for x in data if isinstance(x, dict) and x.get('id')] if isinstance(data, list) else []
    except (IOError, OSError, ValueError):
        return []


def _write(items, base):
    d = os.path.dirname(path(base))
    if not os.path.isdir(d):
        os.makedirs(d)
    text = json.dumps(items[:KEEP], ensure_ascii=False, indent=1, sort_keys=True)
    if not isinstance(text, type(u'')):
        text = text.decode('utf-8')
    tmp = path(base) + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    if os.path.exists(path(base)):
        os.remove(path(base))
    os.rename(tmp, path(base))


def items(base=None):
    """Newest first."""
    return sorted(_read(base), key=lambda x: x.get('created_at', u''), reverse=True)


def add(req, base=None):
    """Remember a request right after submit (sent or queued)."""
    data = [x for x in _read(base) if x.get('id') != req['id']]
    data.append({
        'id': req['id'],
        'created_at': req.get('created_at', u''),
        'topic': req.get('topic', u''),
        'button': req.get('button', u''),
        'text': payload.clip(req.get('text'), TEXT),
        'status': u'',
        'comment': u'',
        'changed': u'',
    })
    data.sort(key=lambda x: x.get('created_at', u''), reverse=True)
    _write(data, base)


def merge(statuses, base=None):
    """statuses: {id: {'status', 'comment', 'changed'}} from the receiver.

    -> ids whose status or comment changed since the last fetch.
    """
    data = _read(base)
    changed = []
    for x in data:
        st = statuses.get(x['id'])
        if not st:
            continue
        new = (payload.u(st.get('status')), payload.u(st.get('comment')))
        if new != (x.get('status', u''), x.get('comment', u'')):
            changed.append(x['id'])
        x['status'], x['comment'] = new
        x['changed'] = payload.u(st.get('changed'))
    if changed or statuses:
        _write(sorted(data, key=lambda x: x.get('created_at', u''), reverse=True), base)
    return changed


COLUMNS = (u'Date', u'Topic', u'Button', u'Request', u'Status', u'Comment')


def table_rows(entries, queued_ids, topic_labels, to_local_text, rejected_ids=()):
    """Rows for "My requests" in COLUMNS order.

    queued_ids: ids still in the outbox -> status WAITING.
    rejected_ids: ids the receiver refused -> status REJECTED.
    topic_labels: {code: label}. to_local_text: UTC ISO text -> shown date.
    """
    rows = []
    for x in entries:
        if x['id'] in queued_ids:
            status = WAITING
        elif x['id'] in rejected_ids and not x.get('status'):
            status = REJECTED
        else:
            status = x.get('status') or u'New'
        rows.append((
            to_local_text(x.get('created_at', u'')),
            topic_labels.get(x.get('topic'), x.get('topic', u'')),
            x.get('button', u''),
            x.get('text', u''),
            status,
            x.get('comment', u''),
        ))
    return rows
