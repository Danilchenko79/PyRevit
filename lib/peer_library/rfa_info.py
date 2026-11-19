# -*- coding: utf-8 -*-
"""Facts about a .rfa without opening it in Revit.

revit_year: in Revit - BasicFileInfo.Extract (exact); outside Revit - the
UTF-16 text of the BasicFileInfo stream ("Format: 2024" since Revit 2019,
"Autodesk Revit Architecture 2013 ..." before). None = not readable.
"""

import hashlib
import re

_FORMAT = re.compile(u'Format: (20\\d\\d)')
_PRODUCT = re.compile(u'Autodesk Revit[^0-9\\x00]{0,30}(20\\d\\d)')


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _year_from_bytes(data):
    found = []
    for shift in (0, 1):
        text = data[shift:].decode('utf-16-le', 'ignore')
        for rx in (_FORMAT, _PRODUCT):
            m = rx.search(text)
            if m:
                found.append((rx is _PRODUCT, int(m.group(1))))
    if not found:
        return None
    found.sort()          # "Format:" wins over the product string
    return found[0][1]


def _year_revit_api(path):
    from Autodesk.Revit.DB import BasicFileInfo  # noqa: import only inside Revit
    info = BasicFileInfo.Extract(path)
    fmt = getattr(info, 'Format', None)          # Revit 2020+
    if fmt and fmt.isdigit():
        return int(fmt)
    m = re.search(u'(20\\d\\d)', info.SavedInVersion or u'')
    return int(m.group(1)) if m else None


def revit_year(path):
    try:
        return _year_revit_api(path)
    except Exception:
        pass
    try:
        with open(path, 'rb') as f:
            return _year_from_bytes(f.read())
    except (IOError, OSError):
        return None
