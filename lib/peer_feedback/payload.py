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

# pictures: at most this many, each this many base64 chars (~1.5 MB of JPEG)
MAX_IMAGES = 5
MAX_IMAGE_B64 = 2000000
_B64 = re.compile(r'^[A-Za-z0-9+/]+={0,2}$')

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
    # a bug with the error text attached may go without words
    if not u(fields.get('text')).strip() and not u(fields.get('error_text')).strip():
        errors.append('err_text')
    if fields.get('topic') in texts.TOPICS_WITH_BUTTON and not u(fields.get('button')).strip():
        errors.append('err_button')
    return errors


def attachments(images):
    """[base64 JPEG text] -> request attachments. Raises ValueError on junk."""
    out = []
    for i, data in enumerate(images or []):
        data = u(data)
        if not data or len(data) > MAX_IMAGE_B64 or not _B64.match(data):
            raise ValueError('bad image %d' % (i + 1))
        out.append({'name': u'image-%d.jpg' % (i + 1), 'type': u'image/jpeg', 'data': data})
    if len(out) > MAX_IMAGES:
        raise ValueError('too many images: %d' % len(out))
    return out


def make_request(fields, context, request_id=None, created_at=None, images=None):
    """fields: what the person typed; context: what the script collected.

    An empty text with an attached error becomes u'(error report)'.

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
        'text': clip(fields.get('text'), MAX_TEXT) or (
            u'(error report)' if u(context.get('error_text')).strip() else u''),
        'frequency': text_type(freq),
        'duration': text_type(dur),
        'button': clip(fields.get('button'), MAX_FIELD),
    }
    for k in CONTEXT_FIELDS:
        limit = MAX_TEXT if k == 'error_text' else MAX_FIELD
        req[k] = clip(context.get(k), limit)
    if images:
        req['attachments'] = attachments(images)
    return req


# ---------------------------------------------------------------- buttons --
_SUFFIX = re.compile(r'\.(tab|panel|stack|pulldown|splitbutton|splitpushbutton|pushbutton|smartbutton)$')
_ORDER = re.compile(r'^\d+_')


def _clean(name):
    return _ORDER.sub(u'', _SUFFIX.sub(u'', u(name)))


def button_name(rel_path):
    """'Walls.panel/WallRebar2D.pushbutton' -> u'Walls / WallRebar2D'.

    rel_path is relative to PEER.tab, any slashes. A .stack only groups
    buttons on the ribbon - not a level people see - so it is dropped.
    """
    raw = [p for p in u(rel_path).replace(u'\\', u'/').split(u'/') if p]
    return u' / '.join(_clean(p) for p in raw if not p.endswith(u'.stack'))


def button_from_script(scriptpath):
    """Full path of a PEER script -> 'Panel / Button', or u'' if not a PEER.tab button."""
    parts = [p for p in u(scriptpath).replace(u'\\', u'/').split(u'/') if p]
    tab = [i for i, p in enumerate(parts) if p.endswith(u'.tab')]
    btn = [i for i, p in enumerate(parts) if _SUFFIX.search(p) and not p.endswith((u'.tab', u'.panel', u'.stack', u'.pulldown'))]
    if not tab or not btn or btn[-1] <= tab[-1]:
        return u''
    return button_name(u'/'.join(parts[tab[-1] + 1:btn[-1] + 1]))


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
        out.append(button_name(os.path.relpath(root, tab_dir)))
    return sorted(set(out), key=lambda x: x.lower())
