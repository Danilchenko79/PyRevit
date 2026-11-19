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


def _cells(line):
    """Split one CSV line ("" escapes a quote inside quotes)."""
    out, cur, quoted, i = [], u'', False, 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == u'"':
                if line[i + 1:i + 2] == u'"':
                    cur += u'"'
                    i += 1
                else:
                    quoted = False
            else:
                cur += ch
        elif ch == u'"':
            quoted = True
        elif ch == u',':
            out.append(cur.strip())
            cur = u''
        else:
            cur += ch
        i += 1
    out.append(cur.strip())
    return out


def read(path):
    """(parameter names, [(type name, [values])])."""
    with io.open(path, 'rb') as f:
        text = _decode(f.read())
    params, rows, seen = [], [], set()
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        cells = _cells(line)
        if i == 0 and line.lstrip().startswith(u','):
            params = [c.split(u'##')[0] for c in cells[1:]]
            continue
        name = cells[0]
        if name and name not in seen:
            seen.add(name)
            rows.append((name, cells[1:]))
    return params, rows


def type_names(path):
    return [r[0] for r in read(path)[1]]


def short_values(params, values, n=3):
    """'h=100, b=100, tw=5' from the first n non-empty values."""
    parts = []
    for p, v in zip(params, values):
        if v:
            parts.append(u'{0}={1}'.format(p, v))
        if len(parts) >= n:
            break
    return u', '.join(parts)
