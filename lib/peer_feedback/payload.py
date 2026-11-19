# -*- coding: utf-8 -*-
"""Build and check the request dict. Pure python: IronPython 2.7 and CPython 3.

One request = one row on the "Requests" sheet. Field names here are the
column keys of the receiver (feedback/receiver/Code.gs, REQUEST_COLUMNS).
"""

import datetime
import os
import re
import uuid

from peer_feedback import texts

try:
    text_type = unicode  # noqa: F821  (IronPython 2.7)
except NameError:
    text_type = str

# Google Sheets holds 50 000 chars per cell; keep rows readable.
MAX_TEXT = 5000
MAX_FIELD = 500

# what the person fills in
USER_FIELDS = ('topic', 'text', 'frequency', 'duration', 'button')
# what the script adds
CONTEXT_FIELDS = ('user', 'machine', 'project', 'revit_version',
                  'pyrevit_version', 'peer_version', 'view', 'selection',
                  'error_script', 'error_text')


def u(x):
    if x is None:
        return u''
    if isinstance(x, text_type):
        return x
    if isinstance(x, bytes):
        try:
            return x.decode('utf-8')
        except UnicodeDecodeError:
            return x.decode('latin-1')
    return text_type(x)


def clip(x, limit):
    x = u(x).strip()
    return x if len(x) <= limit else x[:limit - 1] + u'…'


def new_id():
    return text_type(uuid.uuid4().hex)


def utc_now():
    return text_type(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))


def validate(fields):
    """-> list of error keys of texts.STRINGS (empty = ok)."""
    errors = []
    if not u(fields.get('text')).strip():
        errors.append('err_text')
    if fields.get('topic') in texts.TOPICS_WITH_BUTTON and not u(fields.get('button')).strip():
        errors.append('err_button')
    return errors


def make_request(fields, context, request_id=None, created_at=None):
    """fields: what the person typed; context: what the script collected.

    Unknown topic / frequency / duration codes raise ValueError: they come
    from the window's lists, so a bad one is a bug in the caller.
    """
    topic = fields.get('topic')
    if topic not in texts.TOPIC_CODES:
        raise ValueError('unknown topic: %r' % (topic,))
    freq = fields.get('frequency') or ''
    dur = fields.get('duration') or ''
    if freq not in texts.FREQUENCY_CODES:
        raise ValueError('unknown frequency: %r' % (freq,))
    if dur not in texts.DURATION_CODES:
        raise ValueError('unknown duration: %r' % (dur,))

    req = {
        'id': request_id or new_id(),
        'created_at': created_at or utc_now(),
        'topic': text_type(topic),
        'text': clip(fields.get('text'), MAX_TEXT),
        'frequency': text_type(freq),
        'duration': text_type(dur),
        'button': clip(fields.get('button'), MAX_FIELD),
    }
    for k in CONTEXT_FIELDS:
        limit = MAX_TEXT if k == 'error_text' else MAX_FIELD
        req[k] = clip(context.get(k), limit)
    return req


# ---------------------------------------------------------------- buttons --
_SUFFIX = re.compile(r'\.(tab|panel|stack|pulldown|splitbutton|splitpushbutton|pushbutton|smartbutton)$')
_ORDER = re.compile(r'^\d+_')


def _clean(name):
    return _ORDER.sub(u'', _SUFFIX.sub(u'', u(name)))


def list_buttons(tab_dir):
    """Buttons of the PEER tab as 'Panel / Button' (folder names), sorted.

    Pulldown members are 'Panel / Pulldown / Button'. Folders without a
    script (icon-only placeholders) are skipped.
    """
    out = []
    if not os.path.isdir(tab_dir):
        return out
    for root, dirs, files in os.walk(tab_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('OLD', '__pycache__')]
        if not root.endswith('.pushbutton'):
            continue
        if not any(f.endswith(('.py', '.yaml')) for f in files):
            continue
        rel = os.path.relpath(root, tab_dir)
        parts = [_clean(p) for p in rel.replace('\\', '/').split('/')]
        # a .stack only groups buttons on the ribbon - not a level people see
        parts = [p for p, raw in zip(parts, rel.replace('\\', '/').split('/'))
                 if not raw.endswith('.stack')]
        out.append(u' / '.join(parts))
    return sorted(set(out), key=lambda x: x.lower())
