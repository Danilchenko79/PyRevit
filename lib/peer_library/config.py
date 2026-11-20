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
    shared_params  company shared parameter file for the family checks;
             empty = the file set in Revit (Manage > Shared Parameters)
    access_lock    True = every PEER button needs a signed-in key (set in the repo file
             once everybody has a key)
    channel  'stable' | 'beta' - which PEER package / template this computer follows
"""

import os
import threading

from peer_library import jsonio

_WRITE = threading.Lock()      # background checks at Revit start write the same file

DEFAULTS = {
    'backend': u'local',
    'root': u'',
    'url': u'',
    'cache': u'',
    'role': u'user',
    'user': u'',
    'overwrite_params': False,
    'shared_params': u'',
    'last_ok': u'',      # http: last successful key check (ISO), 14 days offline grace
    'seen_until': u'',   # changelog time the user has seen (library window opened)
    'notify_checked': u'',  # last startup notification check (ISO, local)
    'access_lock': False,   # True: PEER buttons need a signed-in key (peer_library/access.py)
    'channel': u'stable',   # update channel of the PEER package and the template: stable | beta
}

OFFLINE_DAYS = 14

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


REPO_ONLY = ('access_lock',)     # office decisions: a computer's own file cannot change them


def load():
    cfg = dict(DEFAULTS)
    for path in (REPO_FILE, local_file()):
        data = jsonio.read(path, {})
        if not isinstance(data, dict):
            continue
        for k, v in data.items():
            if path != REPO_FILE and k in REPO_ONLY:
                continue
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
    """Change keys of this computer's settings. A file that exists but cannot be
    read is never overwritten (that would lose the service address)."""
    with _WRITE:
        path = local_file()
        data = jsonio.read(path, None)
        if data is None:
            if os.path.exists(path):
                raise IOError(u'{0} cannot be read - not overwritten'.format(path))
            data = {}
        if not isinstance(data, dict):
            data = {}
        for k, v in values.items():
            if k in DEFAULTS:
                data[k] = v
        jsonio.write(path, data, indent=2)
    return load()


def service_url_ok(url):
    """https, or this computer itself (a local copy of the service for tests)."""
    url = url or u''
    return url.startswith('https://') or url.startswith('http://127.0.0.1:') or url == 'http://127.0.0.1'


def is_configured(cfg=None):
    cfg = cfg or load()
    if cfg['backend'] == 'http':
        return service_url_ok(cfg['url'])
    return bool(cfg['root']) and os.path.isdir(cfg['root'])


def panel_visible(cfg=None):
    """Library buttons show only where the library is set up (service address
    in settings.json / on this computer, or a reachable folder) - colleagues
    without it see no buttons that cannot work."""
    try:
        return is_configured(cfg)
    except Exception:
        return False


def make_backend(cfg=None):
    cfg = cfg or load()
    if cfg['backend'] == 'http':
        from peer_library.backend_http import HttpBackend
        return HttpBackend(cfg)
    from peer_library.backend_local import LocalBackend
    return LocalBackend(cfg['root'], role=cfg['role'], user=cfg['user'])
