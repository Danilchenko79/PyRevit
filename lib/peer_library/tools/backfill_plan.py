# -*- coding: utf-8 -*-
"""Card info for families already in the library (CPython, no network).

    py -3 backfill_plan.py <index.json> <sorted source folder> <plan.json>

For every card whose name is still its ID (never edited by hand): readable
name and folder tags (importmeta) + type names from its type catalog in the
source folder. Writes [{id, fields}] for tools/apply_plan.ps1, which sends
them to POST /card (no new versions, files untouched).
"""
from __future__ import print_function

import io
import json
import os
import sys

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(LIB_DIR))

from peer_library import catalog, importmeta  # noqa: E402


def main(index_path, src, out_path):
    with io.open(index_path, 'r', encoding='utf-8-sig') as f:
        idx = json.load(f)
    sources = importmeta.read_sort_log(src)
    plan = []
    for c in idx.get('families', []):
        fields = {}
        if (c.get('name') or c['id']) == c['id']:
            info = importmeta.info_for(c['id'], sources.get(c['id'], u''))
            fields['name'] = info['name']
            if not c.get('tags'):
                fields['tags'] = info['tags']
        if not c.get('types'):
            txt = os.path.join(src, c.get('group', u''), c['id'] + '.txt')
            if c.get('type_catalog') and os.path.isfile(txt):
                fields['types'] = catalog.type_names(txt)[:2000]
        if fields:
            plan.append({'id': c['id'], 'fields': fields})
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(plan, ensure_ascii=False, indent=1))
    print(len(plan), 'cards to update of', len(idx.get('families', [])))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main(*sys.argv[1:4])
