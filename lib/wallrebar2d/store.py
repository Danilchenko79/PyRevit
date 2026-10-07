# -*- coding: utf-8 -*-
"""Хранение пользовательских настроек WallRebar2D.

Файл: %AppData%/WallRebar2D/settings.json
В файле лежат только те ключи, что пользователь менял; остальное берётся
из settings.py. Так дефолты можно править в коде, не ломая сохранённое.
Совместимо с IronPython 2.7 и CPython.
"""

import os
import json
import codecs
import copy

from wallrebar2d.settings import SETTINGS as DEFAULTS


def settings_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'WallRebar2D')


def settings_path():
    return os.path.join(settings_dir(), 'settings.json')


def defaults():
    return copy.deepcopy(DEFAULTS)


def load():
    """Дефолты, поверх которых наложен пользовательский json."""
    S = defaults()
    path = settings_path()
    if not os.path.isfile(path):
        return S
    try:
        with codecs.open(path, 'r', 'utf-8') as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return S
    for k, v in data.items():
        if k in ('wall_filter', 'families', 'tags') and isinstance(v, dict):
            S[k].update(v)
        elif k in S:
            S[k] = v
    # кортежи после json приходят списками — вернём кортежи там, где это важно
    for k in ('corner_block_bars', 'thickness_step_add'):
        if isinstance(S.get(k), list):
            S[k] = tuple(S[k])
    return S


def save(S):
    """Пишет только отличия от дефолтов. Возвращает путь файла."""
    base = defaults()
    diff = {}
    for k, v in S.items():
        if k in ('wall_filter', 'families', 'tags'):
            sub = dict((kk, vv) for kk, vv in v.items() if base.get(k, {}).get(kk) != vv)
            if sub:
                diff[k] = sub
        elif base.get(k) != v:
            diff[k] = v
    folder = settings_dir()
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except OSError:
            pass
    path = settings_path()
    with codecs.open(path, 'w', 'utf-8') as f:
        f.write(json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True))
    return path


def reset():
    """Удаляет пользовательский файл — возврат к дефолтам."""
    path = settings_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return True
