# -*- coding: utf-8 -*-
"""One-off: sort a raw family folder into library groups (CPython 3, outside Revit).

    py -3 sort_source.py <raw folder> <target folder> [--dry]

Copies (never moves) every usable .rfa with its type catalog .txt into
<target>/<group>/, skipping backups (*.0001.rfa), OLD / delete folders,
families saved in a Revit newer than the library format and exact duplicates.
Writes <target>/_sort_log.csv (UTF-8 with BOM, opens in Excel) with
source -> target, Revit version and the reason for every skipped file.
"""
from __future__ import print_function

import csv
import hashlib
import io
import os
import re
import shutil
import sys

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(LIB_DIR))

from peer_library import checks_file, rfa_info  # noqa: E402
from peer_library.groups import GROUPS  # noqa: E402

# First matching prefix of the source path (relative, '\\'-separated) wins.
FOLDER_RULES = [
    (r'02 Model Families\_Structural Framing', '01_Framing'),
    (r'02 Model Families\_Structural Columns', '01_Framing'),
    (r'02 Model Families\Structural Connections\Precast', '01_Framing'),
    (r'02 Model Families\Profile', '01_Framing'),
    (r'02 Model Families\_Structural Foundations', '02_Foundations'),
    (r'02 Model Families\Anchors', '02_Foundations'),
    (r'04 Rebar\2D Rebar', '03_Rebar_2D'),
    (r'01 Annotation\DETAIL ITEMS\Reinforcement Details', '03_Rebar_2D'),
    (r'04 Rebar\3D Rebar', '04_Rebar_3D_Embeds'),
    (r'02 Model Families\Structural Connections\Mounting Parts', '04_Rebar_3D_Embeds'),
    (r'01 Annotation\DETAIL ITEMS\Grid_Head', '06_Tags'),
    (r'01 Annotation\DETAIL ITEMS', '05_Details'),
    (r'02 Model Families\Stairs', '05_Details'),
    (r'01 Annotation', '06_Tags'),
    (r'03 Sheets', '07_Sheets'),
    (r'STEEL', '08_Steel'),
    (r'02 Model Families\Structural Connections\Steel', '08_Steel'),
    (r'02 Model Families\Structural Stiffeners', '08_Steel'),
    (r'02 Model Families\Structural Trusses', '08_Steel'),
    (r'02 Model Families\Steel Decks', '08_Steel'),
    (r'02 Model Families\Openings', '09_Openings'),
]

SKIP_DIRS = re.compile(r'(^|\\)(OLD|_?Архив[^\\]*|' + u'למחוק' + r')(\\|$)', re.I)
BACKUP = re.compile(r'\.\d{4}$')

# Hebrew / bad names -> English IDs (the family name in Revit becomes the ID).
RENAME = {
    u'איטום': 'PEER_Detail_Waterproofing',
    u'ארגזי פוליביד עם קרקע': 'PEER_Detail_Polybid boxes with soil',
    u'ארגזי פוליביד': 'PEER_Detail_Polybid boxes',
    u'החסרה בקיר': 'PEER_Detail_Wall recess',
    u'מילוי בלוק - תקרת צלעות': 'PEER_Detail_Ribbed slab block fill',
    u'נישה בקיר': 'PEER_Detail_Wall niche',
    u'עומסים': 'PEER_Detail_Loads',
    u'קו קרקע': 'PEER_Detail_Ground line',
    u'עפ מידות-  תג קורות - מספר וגודל': 'PEER_Tag_Beam_Number and size by dims',
    u'תג קורה - מספר חתך וגובה': 'PEER_Tag_Beam_Number section and height',
    u'תג קורות - גודל V2': 'PEER_Tag_Beam_Size V2',
    u'תג קורות - מספר וגודל': 'PEER_Tag_Beam_Number and size',
    u'תג קורות - מספר וגודל 12 ממ': 'PEER_Tag_Beam_Number and size 12mm',
    u'תג קורות - מספר וגודל V2': 'PEER_Tag_Beam_Number and size V2',
    u'תג קורות - מספר וגודל-מסגרת רחבה': 'PEER_Tag_Beam_Number and size wide frame',
    u'תג קורות - מספר': 'PEER_Tag_Beam_Number',
    u'תג קורות -ראה זיון קורה': 'PEER_Tag_Beam_See beam reinforcement',
    u'קצה רצפה טרפזי': 'PEER_Profile_Slab edge trapezoid',
    u'כלונס': 'PEER_Pile_Round',
    u'PEER-Annotation-Elevation o.k.': 'PEER-Annotation-Elevation ok',
    u'US_HSS-R - Hollow Struct. Section rect.': 'US_HSS-R - Hollow Struct. Section rect',
}

# Known wrong files: same bytes as another family under a different name.
KNOWN_BAD = {
    'PEER_Rebar_Shape 63': 'same file as PEER_Rebar_Shape 60 - real Shape 63 (angle) is missing',
    'Round hole in walls': 'same file as Rectangular hole in floor',
}


def _norm(name):
    return re.sub(u'[‎‏]', u'', name).strip()


def group_for(rel):
    for prefix, group in FOLDER_RULES:
        if rel == prefix or rel.startswith(prefix + '\\'):
            return group
    return None


def plan(src):
    rows, seen_sha, seen_id = [], {}, {}
    for dp, dn, fn in os.walk(src):
        dn.sort()
        for f in sorted(fn):
            if not f.lower().endswith('.rfa'):
                continue
            path = os.path.join(dp, f)
            rel = os.path.relpath(path, src)
            rel_dir = os.path.dirname(rel)
            base = _norm(os.path.splitext(f)[0])
            new_id = RENAME.get(base, base)
            row = {'source': rel, 'group': group_for(rel_dir) or '', 'id': new_id,
                   'revit': '', 'catalog': '', 'action': 'copy', 'reason': ''}
            rows.append(row)
            if SKIP_DIRS.search(rel_dir):
                row.update(action='skip', reason='old / to-delete folder')
                continue
            if BACKUP.search(base):
                row.update(action='skip', reason='Revit backup copy')
                continue
            year = rfa_info.revit_year(path)
            row['revit'] = year or ''
            if year and year > checks_file.LIBRARY_REVIT:
                row.update(action='skip', reason='saved in Revit %d - rebuild in %d'
                           % (year, checks_file.LIBRARY_REVIT))
                continue
            if base in KNOWN_BAD:
                row.update(action='skip', reason=KNOWN_BAD[base])
                continue
            sha = rfa_info.sha1(path)
            if sha in seen_sha:
                row.update(action='skip', reason='same content as ' + seen_sha[sha])
                continue
            seen_sha[sha] = rel
            if not row['group']:
                row.update(action='skip', reason='no group rule for this folder')
                continue
            if new_id.lower() in seen_id:
                row.update(action='skip', reason='ID already used by ' + seen_id[new_id.lower()])
                continue
            seen_id[new_id.lower()] = rel
            problems = checks_file.check_name(new_id)
            if problems:
                row.update(action='skip', reason='bad name: ' + '; '.join(problems))
                continue
            if new_id != base:
                row['reason'] = 'renamed'
            cat = os.path.join(dp, os.path.splitext(f)[0] + '.txt')
            if os.path.exists(cat):
                row['catalog'] = 'yes'
            if year is None:
                row['reason'] = (row['reason'] + '; ' if row['reason'] else '') + \
                    'Revit version not readable - check at publish'
    return rows


def run(src, dst, dry=False):
    rows = plan(src)
    if not dry:
        for g in GROUPS:
            d = os.path.join(dst, g[0])
            if not os.path.isdir(d):
                os.makedirs(d)
        for r in rows:
            if r['action'] != 'copy':
                continue
            sp = os.path.join(src, r['source'])
            tp = os.path.join(dst, r['group'], r['id'] + '.rfa')
            shutil.copy2(sp, tp)
            if r['catalog']:
                shutil.copy2(os.path.splitext(sp)[0] + '.txt',
                             os.path.join(dst, r['group'], r['id'] + '.txt'))
        with io.open(os.path.join(dst, '_sort_log.csv'), 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.DictWriter(fh, ['action', 'group', 'id', 'revit', 'catalog', 'reason', 'source'])
            w.writeheader()
            w.writerows(rows)
    return rows


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    res = run(a[0], a[1], dry='--dry' in sys.argv)
    from collections import Counter
    print('copy', sum(1 for r in res if r['action'] == 'copy'),
          'skip', sum(1 for r in res if r['action'] == 'skip'))
    print(Counter(r['group'] for r in res if r['action'] == 'copy').most_common())
    print(Counter(r['reason'].split(' - ')[0].split(':')[0] for r in res if r['action'] == 'skip').most_common())
    for r in res:
        if r['action'] == 'skip' and not r['reason'].startswith(('Revit backup', 'old /')):
            print('  SKIP', r['source'], '->', r['reason'])
