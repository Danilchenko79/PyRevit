# -*- coding: utf-8 -*-
"""Backup of the library from the service (CPython 3, admin key).

    py -3 backup.py https://peer-library.<you>.workers.dev <folder>

The key is read from the PEER key store of this Windows user (sign in with
the Library button first) or from the PEER_LIBRARY_KEY environment variable.
Writes <folder>/<date>/PEER-Library/... (index.json, changelog.json and every
file of every card) - the same layout as in R2. Keys and proposals live in
D1: npx wrangler d1 export peer-library --remote --output=<folder>/d1.sql
"""
from __future__ import print_function

import datetime
import json
import os
import sys

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(LIB_DIR))

from peer_library import config, jsonio, keystore, rfa_info  # noqa: E402
from peer_library.backend_http import HttpBackend  # noqa: E402

HASH = {'.rfa': 'sha1', '.png': 'png_sha1', '.txt': 'catalog_sha1'}


def main(url, folder):
    key = os.environ.get('PEER_LIBRARY_KEY') or keystore.load()
    if not key:
        sys.exit('No key: sign in with PEER -> Library or set PEER_LIBRARY_KEY')
    cfg = dict(config.load(), url=url)
    b = HttpBackend(cfg, key=key)
    who = b.auth()
    root = os.path.join(folder, datetime.date.today().isoformat(), 'PEER-Library')
    idx = b.get_index()
    jsonio.write(os.path.join(root, 'index.json'), idx)
    jsonio.write(os.path.join(root, 'changelog.json'), b.get_changelog())
    n, bad = 0, 0
    for card in idx.get('families', []):
        for ext, path in (card.get('files') or {}).items():
            target = os.path.join(root, *path.split('/'))
            b.download(path, target)
            n += 1
            if card.get(HASH.get(ext, ''), '') and rfa_info.sha1(target) != card[HASH[ext]]:
                bad += 1
                print('HASH MISMATCH', path)
    print('{0}: {1} families, {2} files, {3} mismatches -> {4}'.format(
        who.get('name'), len(idx.get('families', [])), n, bad, root))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1].rstrip('/'), sys.argv[2])
