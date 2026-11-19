# -*- coding: utf-8 -*-
"""Card info for families imported in bulk: readable name and tags.

Name:  PEER-Concrete-Column-Rectangular -> "Concrete Column Rectangular"
       EU_HE - Wide-Flange HEA-HEB-HEM  -> "HE - Wide-Flange HEA-HEB-HEM" + tag "EU"
Tags:  the folders the family came from (_sort_log.csv of tools/sort_source.py):
       02 Model Families/Structural Connections/Mounting Parts/Anchor Bolts
       -> ["Structural Connections", "Mounting Parts", "Anchor Bolts"]
The admin corrects them later in the library (Edit info) or in bulk (CSV).
"""

import csv
import io
import os
import re

PREFIXES = ('PEER_', 'PEER-', 'PEER ', 'PR_', 'PR-', 'PR - ', 'M_')
STANDARDS = {'EU_': u'EU', 'UK_': u'UK', 'US_': u'US'}
SKIP_FOLDERS = re.compile(r'^(\d+\s|OLD$|_?Архив|Новые формы$)', re.I)
TOP_FOLDERS = ('01 Annotation', '02 Model Families', '03 Sheets', '04 Rebar',
               '05 Templates & Views', 'STEEL')


def display_name(family_id):
    name = family_id
    for p in PREFIXES:
        if name.upper().startswith(p.upper()) and len(name) > len(p) + 1:
            name = name[len(p):]
            break
    for p in STANDARDS:
        if name.startswith(p):
            name = name[len(p):]
            break
    if ' - ' not in name:
        name = name.replace(u'_', u' ').replace(u'-', u' ')
    else:
        name = name.replace(u'_', u' ')
    return re.sub(r'\s+', u' ', name).strip() or family_id


def standard_tag(family_id):
    for p, tag in STANDARDS.items():
        if family_id.startswith(p):
            return tag
    return None


def folder_tags(source_rel):
    parts = re.split(r'[\\/]', source_rel or u'')[:-1]       # without the file name
    tags = []
    for p in parts:
        if p in TOP_FOLDERS or SKIP_FOLDERS.match(p):
            continue
        t = p.replace(u'_', u' ').strip()
        if t.isupper():
            t = t.title()
        if t and t not in tags:
            tags.append(t)
    return tags


def read_sort_log(folder):
    """id -> source relative path, from <folder>/_sort_log.csv (copied rows only)."""
    path = os.path.join(folder, '_sort_log.csv')
    out = {}
    if not os.path.isfile(path):
        return out
    with io.open(path, 'r', encoding='utf-8-sig') as f:
        text = f.read()
    for row in csv.DictReader(text.splitlines()):
        if row.get('action') == 'copy' and row.get('id'):
            out[row['id']] = row.get('source') or u''
    return out


def info_for(family_id, source_rel=u''):
    tags = folder_tags(source_rel)
    st = standard_tag(family_id)
    if st and st not in tags:
        tags.insert(0, st)
    name = display_name(family_id)
    if re.search(r'3D Rebar[\\/]Shapes', source_rel or u''):
        name = u'Rebar shape ' + family_id          # BS 8666 codes: 21E, 11, 98-H2 ...
    return {'name': name, 'tags': tags}
