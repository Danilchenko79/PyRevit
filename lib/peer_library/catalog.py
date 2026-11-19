# -*- coding: utf-8 -*-
"""Revit type catalog (.txt next to the .rfa): first column = type name.

Header line starts with ',' and lists parameters (Width##LENGTH##MILLIMETERS).
Files come in UTF-16 (Revit default), UTF-8 or the system code page.
"""

import codecs
import io


def _decode(raw):
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return raw.decode('utf-16')
    if raw[:3] == codecs.BOM_UTF8:
        return raw[3:].decode('utf-8')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('cp1252', 'replace')


def _first_cell(line):
    line = line.strip()
    if not line:
        return u''
    if line.startswith(u'"'):
        end = line.find(u'"', 1)
        while end > 0 and line[end + 1:end + 2] == u'"':      # "" inside quotes
            end = line.find(u'"', end + 2)
        return line[1:end].replace(u'""', u'"') if end > 0 else line[1:]
    return line.split(u',', 1)[0].strip()


def type_names(path):
    with io.open(path, 'rb') as f:
        text = _decode(f.read())
    names = []
    for i, line in enumerate(text.splitlines()):
        if i == 0 and line.lstrip().startswith(u','):
            continue
        name = _first_cell(line)
        if name and name not in names:
            names.append(name)
    return names
