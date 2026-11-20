# -*- coding: utf-8 -*-
"""Release calls to the PEER service with the admin key saved on this computer
(IronPython of pyRevit - .NET HTTPS and DPAPI; started by release.ps1).

ARGS (set by release.ps1):
    ['manifest', product]
    ['publish', product, version, file, channel, note]
    ['promote', product, version, channel]
    ['installer', '-', file]
env PEER_RELEASE_TARGET=production -> the office service (see below), else the service of this computer.
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
TARGET = os.environ.get('PEER_RELEASE_TARGET') or 'this'
if TARGET == 'production':
    # the office service: its address and its admin key live beside the everyday ones
    #   %APPDATA%/PEER/production.json            {"url": "https://..."}
    #   %APPDATA%/PEER/library_key_production.bin  (DPAPI, as library_key.bin)
    from peer_library import jsonio, keystore
    from peer_library.backend_http import HttpBackend
    prod = jsonio.read(os.path.join(config.appdata_dir(), 'production.json')) or {}
    if not config.service_url_ok(prod.get('url')) or not prod.get('url').startswith('https://'):
        raise SystemExit('No production address: %APPDATA%/PEER/production.json {"url": "https://..."}')
    try:
        with open(os.path.join(config.appdata_dir(), 'library_key_production.bin'), 'rb') as f:
            key = keystore._dpapi(f.read(), decrypt=True).decode('utf-8')
    except Exception:
        raise SystemExit('No production admin key on this computer (library_key_production.bin).')
    cfg = dict(cfg, backend='http', url=prod['url'])
    backend = HttpBackend(cfg, key=key)
    backend.auth = lambda quick=False: __import__('json').loads(backend._call('GET', '/auth'))   # do not touch local settings
else:
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
    ints = [releases.vkey(v['version'])[0] for v in m.get('versions') or [] if len(releases.vkey(v['version'])) == 1]
    print('NEXTINT', (max(ints) if ints else 0) + 1)
elif cmd == 'publish':
    version, path, channel, note = args[2], args[3], args[4], args[5]
    sha = rfa_info.sha1(path)
    up = backend.release_upload(product, version, path, sha)
    print('UPLOADED', up.get('size'), up.get('sha1'))
    r = backend.release_publish(product, version, channel, note, sha, os.path.basename(path))
    print('PUBLISHED', r.get('version'), 'to', r.get('channel'), r.get('channels'))
elif cmd == 'installer':
    r = __import__('json').loads(backend._call('PUT', '/install', raw=args[2]))
    print('INSTALLER', r.get('size'), 'bytes ->', backend.url + '/install')
elif cmd == 'promote':
    if product in ('ext', 'boot'):
        # stable = PEER, beta = PEER_dev: different packages (other tab name) - only a roll back
        # inside the same channel makes sense
        m, _ = backend.release_manifest(product)
        e = releases.entry(m, args[2]) or {}
        is_dev = (e.get('name') or u'').startswith('PEER_dev')
        if e and is_dev != (args[3] == 'beta'):
            raise SystemExit('Version {0} is a {1} package - it cannot go to the {2} channel. '
                             'Release it from the other branch instead.'.format(
                                 args[2], 'PEER_dev' if is_dev else 'PEER', args[3]))
    r = backend.release_promote(product, args[2], args[3])
    print('PROMOTED', r.get('version'), 'to', r.get('channel'), r.get('channels'))
else:
    raise SystemExit('Unknown command: ' + cmd)
