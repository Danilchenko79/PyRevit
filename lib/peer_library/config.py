# -*- coding: utf-8 -*-
"""User settings of the library.

Two files, the second wins key by key:
    1. lib/peer_library/settings.json   - in the repo (office default), optional
    2. %APPDATA%/PEER/library.json      - this computer (Shift+Click on Library)

Keys:
    backend  'local' (a plain folder) | 'http' (the access service)
    root     folder that holds PEER-Library and PEER-Inbox (local backend)
    url      service address (http backend)
    cache    local copy, default %LOCALAPPDATA%/PEER/Library
    role     'user' | 'admin' - local backend only; the service decides itself
    user     name shown on proposals, default = Windows user name
"""

import os

from peer_library import jsonio

DEFAULTS = {
    'backend': u'local',
    'root': u'',
    'url': u'',
    'cache': u'',
    'role': u'user',
    'user': u'',
    'overwrite_params': False,
}

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_FILE = os.path.join(HERE, 'settings.json')


def appdata_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'PEER')


def local_file():
    return os.path.join(appdata_dir(), 'library.json')


def default_cache():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'PEER', 'Library')


def work_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'PEER', 'Work')


def _expand(path):
    return os.path.expandvars(os.path.expanduser(path)) if path else path


def load():
    cfg = dict(DEFAULTS)
    for path in (REPO_FILE, local_file()):
        data = jsonio.read(path, {})
        if not isinstance(data, dict):
            continue
        for k, v in data.items():
            if k in DEFAULTS and v not in (None, u''):
                cfg[k] = v
    cfg['root'] = _expand(cfg['root'])
    cfg['cache'] = _expand(cfg['cache']) or default_cache()
    if cfg['backend'] not in ('local', 'http'):
        cfg['backend'] = 'local'
    if cfg['role'] not in ('user', 'admin'):
        cfg['role'] = 'user'
    cfg['user'] = cfg['user'] or os.environ.get('USERNAME') or u'user'
    return cfg


def save_local(**values):
    data = jsonio.read(local_file(), {})
    if not isinstance(data, dict):
        data = {}
    for k, v in values.items():
        if k in DEFAULTS:
            data[k] = v
    jsonio.write(local_file(), data, indent=2)
    return load()


def is_configured(cfg=None):
    cfg = cfg or load()
    if cfg['backend'] == 'http':
        return cfg['url'].startswith('https://')
    return bool(cfg['root']) and os.path.isdir(cfg['root'])


def make_backend(cfg=None):
    cfg = cfg or load()
    if cfg['backend'] == 'http':
        from peer_library.backend_http import HttpBackend
        return HttpBackend(cfg)
    from peer_library.backend_local import LocalBackend
    return LocalBackend(cfg['root'], role=cfg['role'], user=cfg['user'])
