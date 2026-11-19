# -*- coding: utf-8 -*-
"""Per-user library lists on this computer: favourites and recently loaded.
%APPDATA%/PEER/library_user.json"""

import os

from peer_library import config, jsonio

RECENT_KEEP = 30


def _path():
    return os.path.join(config.appdata_dir(), 'library_user.json')


def load():
    data = jsonio.read(_path(), {}) or {}
    return {'favorites': list(data.get('favorites') or []),
            'recent': list(data.get('recent') or [])}


def _save(data):
    try:
        jsonio.write(_path(), data, indent=1)
    except Exception:
        pass


def toggle_favorite(family_id):
    data = load()
    fav = data['favorites']
    if family_id in fav:
        fav.remove(family_id)
        on = False
    else:
        fav.append(family_id)
        on = True
    _save(data)
    return on


def add_recent(family_id):
    data = load()
    rec = [x for x in data['recent'] if x != family_id]
    data['recent'] = [family_id] + rec[:RECENT_KEEP - 1]
    _save(data)
