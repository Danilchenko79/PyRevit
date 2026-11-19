# -*- coding: utf-8 -*-
"""Receiver address, key and timeout.

Two files, the second wins key by key:
    1. lib/peer_feedback/settings.json  - in the repo, reaches everyone with
       the PEER update (bat file / auto-sync).
    2. %APPDATA%/PEER/feedback.json     - on this computer only. Written by
       Shift+Click on Contact -> "Receiver address and key".

settings.json in the repo carries the group's receiver address and key, so
Contact works on every computer without setup. The repo is public: anyone can
read the key. With it the receiver only appends rows / pictures and returns
the status of a request id one already knows - it never returns the table.
Spam -> run rotateKey in Apps Script, put the new key here, push.
"""

import io
import json
import os

DEFAULTS = {
    'url': u'',          # https://script.google.com/macros/s/<id>/exec
    'key': u'',          # same value as Script Property PEER_KEY
    'timeout_s': 10,     # one HTTP request, seconds
}

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_FILE = os.path.join(HERE, 'settings.json')


def ext_dir():
    """PEER.extension folder (parent of lib/)."""
    return os.path.dirname(os.path.dirname(HERE))


def local_dir():
    """%APPDATA%/PEER - per-user data that survives PEER updates."""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'PEER')


def local_file():
    return os.path.join(local_dir(), 'feedback.json')


def _read(path):
    try:
        with io.open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def load():
    cfg = dict(DEFAULTS)
    for path in (REPO_FILE, local_file()):
        for k, v in _read(path).items():
            if k in DEFAULTS and v not in (None, u''):
                cfg[k] = v
    cfg['url'] = (cfg['url'] or u'').strip()
    cfg['key'] = (cfg['key'] or u'').strip()
    try:
        cfg['timeout_s'] = max(2, min(60, int(cfg['timeout_s'])))
    except (TypeError, ValueError):
        cfg['timeout_s'] = DEFAULTS['timeout_s']
    return cfg


def save_local(**values):
    """Merge values into %APPDATA%/PEER/feedback.json."""
    data = _read(local_file())
    for k, v in values.items():
        if k in DEFAULTS:
            data[k] = v
    folder = local_dir()
    if not os.path.isdir(folder):
        os.makedirs(folder)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    if not isinstance(text, type(u'')):
        text = text.decode('utf-8')
    with io.open(local_file(), 'w', encoding='utf-8') as f:
        f.write(text)
    return load()


def is_configured(cfg=None):
    cfg = cfg or load()
    return cfg['url'].startswith('https://') and bool(cfg['key'])


def peer_version(root=None):
    """Short git sha of the installed PEER (no git needed), or u'unknown'."""
    git = os.path.join(root or ext_dir(), '.git')
    try:
        with io.open(os.path.join(git, 'HEAD'), 'r', encoding='utf-8') as f:
            head = f.read().strip()
        if not head.startswith('ref:'):
            return head[:7]
        ref = head[4:].strip()
        path = os.path.join(git, *ref.split('/'))
        if os.path.isfile(path):
            with io.open(path, 'r', encoding='utf-8') as f:
                return f.read().strip()[:7]
        with io.open(os.path.join(git, 'packed-refs'), 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(' ')
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0][:7]
    except (IOError, OSError):
        pass
    return u'unknown'
