# -*- coding: utf-8 -*-
"""JSON files: UTF-8, non-ASCII kept as is, write through a temp file."""

import io
import json
import os

try:
    text_type = unicode  # noqa: F821  (IronPython / py2)
except NameError:
    text_type = str


def read(path, default=None):
    try:
        with io.open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return default


def dumps(data, indent=1):
    text = json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=True)
    if not isinstance(text, text_type):
        text = text.decode('utf-8')
    return text


def makedirs(folder):
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)


def replace(src, dst):
    """Move src over dst (dst may exist)."""
    rep = getattr(os, 'replace', None)
    if rep is not None:
        rep(src, dst)
        return
    if os.path.exists(dst):
        os.remove(dst)
    os.rename(src, dst)


def write(path, data, indent=1):
    makedirs(os.path.dirname(path))
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        f.write(dumps(data, indent))
    replace(tmp, path)
