# -*- coding: utf-8 -*-
"""Local queue of unsent items: one JSON file per item in %APPDATA%/PEER/outbox.

An item is {'action': ..., 'data': {...}} with data['id'] unique. It is put
here BEFORE the first send attempt and removed only after the receiver
answered ok, so nothing is lost when Revit closes or the network drops.
Pure python: IronPython 2.7 and CPython 3.
"""

import io
import json
import os

from peer_feedback import config

# a broken network for months must not fill the disk with usage rows;
# a person's own request ('request') is always kept
MAX_ITEMS = 1000
ALWAYS_KEEP = ('request',)


def folder(base=None):
    return os.path.join(base or config.local_dir(), 'outbox')


def rejected_folder(base=None):
    """Items the receiver refused as broken: kept for the head of the group."""
    return os.path.join(base or config.local_dir(), 'rejected')


def _safe(item_id):
    return u''.join(c for c in item_id if c.isalnum() or c in '-_')[:64]


def put(item, base=None):
    """Write the item (atomic: temp file + rename). -> file path or None."""
    item_id = _safe(item['data']['id'])
    if not item_id:
        raise ValueError('item without id')
    d = folder(base)
    if not os.path.isdir(d):
        os.makedirs(d)
    path = os.path.join(d, item_id + '.json')
    if (item.get('action') not in ALWAYS_KEEP and not os.path.exists(path)
            and len(_names(d)) >= MAX_ITEMS):
        return None
    tmp = path + '.tmp'
    text = json.dumps(item, ensure_ascii=False, sort_keys=True)
    if not isinstance(text, type(u'')):
        text = text.decode('utf-8')
    with io.open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)
    return path


def _names(d):
    try:
        return sorted(n for n in os.listdir(d) if n.endswith('.json'))
    except OSError:
        return []


def items(base=None):
    """[(path, item)] oldest first. Unreadable files are skipped, not deleted."""
    d = folder(base)
    out = []
    for n in _names(d):
        path = os.path.join(d, n)
        try:
            with io.open(path, 'r', encoding='utf-8') as f:
                item = json.load(f)
            out.append((os.path.getmtime(path), path, item))
        except (IOError, OSError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return [(p, it) for _, p, it in out]


def remove(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def reject(path, base=None):
    """Move a refused item out of the queue into rejected/. -> new path or None."""
    d = rejected_folder(base)
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
        dst = os.path.join(d, os.path.basename(path))
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(path, dst)
        return dst
    except OSError:
        remove(path)
        return None


def count(base=None):
    return len(_names(folder(base)))


def ids(base=None):
    """data ids of the queued items (file name = id)."""
    return set(n[:-5] for n in _names(folder(base)))


def rejected_ids(base=None):
    return set(n[:-5] for n in _names(rejected_folder(base)))
