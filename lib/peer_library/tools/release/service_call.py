# -*- coding: utf-8 -*-
"""Release calls to the PEER service with the admin key saved on this computer
(IronPython of pyRevit - .NET HTTPS and DPAPI; started by release.ps1).

ARGS (set by release.ps1):
    ['manifest', product]
    ['publish', product, version, file, channel, note]
    ['promote', product, version, channel]
The key is read from the encrypted file and never printed.
"""
from __future__ import print_function
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))        # noqa: F821
LIB = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from peer_library import config, releases, rfa_info  # noqa: E402

args = list(ARGS)                                        # noqa: F821
cfg = config.load()
backend = config.make_backend(cfg)
if cfg['backend'] != 'http' or not backend.has_key():
    raise SystemExit('The PEER service is not set up or no key is saved on this computer.')
who = backend.auth()
if who.get('role') != 'admin':
    raise SystemExit('Only a PEER admin can release.')
print('SERVICE', backend.url)
print('ADMIN', who.get('name'))

cmd, product = args[0], args[1]
if cmd == 'manifest':
    m, _ = backend.release_manifest(product)
    print('CHANNELS', m.get('channels'))
    for v in m.get('versions') or []:
        print('VERSION', v['version'], v.get('time'), v.get('size'), (v.get('note') or u'').split(u'\n')[0][:80])
    import datetime
    print('NEXT', releases.next_version(m, datetime.datetime.now().strftime('%Y.%m.%d')))
elif cmd == 'publish':
    version, path, channel, note = args[2], args[3], args[4], args[5]
    sha = rfa_info.sha1(path)
    up = backend.release_upload(product, version, path, sha)
    print('UPLOADED', up.get('size'), up.get('sha1'))
    r = backend.release_publish(product, version, channel, note, sha, os.path.basename(path))
    print('PUBLISHED', r.get('version'), 'to', r.get('channel'), r.get('channels'))
elif cmd == 'promote':
    r = backend.release_promote(product, args[2], args[3])
    print('PROMOTED', r.get('version'), 'to', r.get('channel'), r.get('channels'))
else:
    raise SystemExit('Unknown command: ' + cmd)
