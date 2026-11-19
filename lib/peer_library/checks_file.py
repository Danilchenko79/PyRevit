# -*- coding: utf-8 -*-
"""Checks of a family file before it is opened. Limits live here only.

A check result is a list of (level, code, text):
    level 'error'   - blocks publishing
    level 'warning' - admin may accept it with a tick
"""

import os
import re

from peer_library import rfa_info

LIBRARY_REVIT = 2024          # library format; publish only from this Revit
MAX_SIZE_MB = 25              # hard limit
WARN_SIZE_MB = 8              # "heavy family" warning
MAX_NAME = 80
OLD_REVIT = 2018              # older -> warning (will be upgraded on save)

# ID = file name = family name in Revit. Latin letters, digits and a few signs.
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _\-.()+,&]*$')
FORBIDDEN = u'\\/:*?"<>|'
PREFERRED_PREFIX = ('PEER', 'PR_', 'EU_', 'UK_', 'US_', 'M_')


def check_name(family_id):
    """Blocking problems of an ID (empty list = OK)."""
    p = []
    if not family_id:
        return [u'empty name']
    if family_id != family_id.strip():
        p.append(u'spaces at the start or end')
    if family_id.endswith(u'.'):
        p.append(u'ends with a dot')
    if len(family_id) > MAX_NAME:
        p.append(u'longer than {0} characters'.format(MAX_NAME))
    bad = [c for c in family_id if c in FORBIDDEN]
    if bad:
        p.append(u'forbidden characters: ' + u' '.join(sorted(set(bad))))
    elif not NAME_RE.match(family_id.strip()):
        p.append(u'only Latin letters, digits, space and _ - . ( ) + , &')
    if u'  ' in family_id:
        p.append(u'double space')
    return p


def check_file(path, family_id=None):
    """Checks without opening the family. Returns (results, revit_year)."""
    res = []
    if family_id is None:
        family_id = os.path.splitext(os.path.basename(path))[0]
    if not os.path.isfile(path):
        return [('error', 'missing', u'File not found: ' + path)], None
    if not path.lower().endswith('.rfa'):
        res.append(('error', 'not_rfa', u'Not a family file (.rfa)'))
    for p in check_name(family_id):
        res.append(('error', 'name', u'Name "{0}": {1}'.format(family_id, p)))
    if family_id and not family_id.upper().startswith(tuple(x.upper() for x in PREFERRED_PREFIX)):
        res.append(('warning', 'prefix', u'Name does not start with PEER / PR_ '
                                         u'(company families are easier to find)'))
    size_mb = os.path.getsize(path) / 1048576.0
    if size_mb > MAX_SIZE_MB:
        res.append(('error', 'size', u'File is {0:.1f} MB, limit {1} MB'.format(size_mb, MAX_SIZE_MB)))
    elif size_mb > WARN_SIZE_MB:
        res.append(('warning', 'size', u'Heavy file: {0:.1f} MB'.format(size_mb)))
    year = rfa_info.revit_year(path)
    if year is None:
        res.append(('warning', 'revit_unknown', u'Revit version of the file is not readable'))
    elif year > LIBRARY_REVIT:
        res.append(('error', 'revit_new', u'Saved in Revit {0}; the library is Revit {1} - '
                                          u'rebuild it in Revit {1}'.format(year, LIBRARY_REVIT)))
    elif year < OLD_REVIT:
        res.append(('warning', 'revit_old', u'Saved in Revit {0}; publishing upgrades it to {1}'
                                            .format(year, LIBRARY_REVIT)))
    return res, year


def errors(results):
    return [r for r in results if r[0] == 'error']


def warnings(results):
    return [r for r in results if r[0] == 'warning']
