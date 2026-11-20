# -*- coding: utf-8 -*-
"""Release the checked-out commit through the PEER service (CPython; GitHub Actions or by hand).

    python lib/peer_library/tools/release/ci_release.py stable|beta
    env  PEER_URL, PEER_RELEASE_KEY   the service and an admin key (never printed)
         PEER_BEFORE                  commit before the push: nothing of PEER changed since -> no release

stable = PEER (branch main), beta = PEER_dev (branch dev). Publishes the full
package, the loader and the installer of one version; the note is the commit subject.
"""
from __future__ import print_function

import datetime
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
EXT = os.path.dirname(LIB)
sys.path.insert(0, LIB)

from peer_library import config, pack, releases, rfa_info  # noqa: E402
from peer_library.backend_http import HttpBackend  # noqa: E402


def git(*args):
    return subprocess.check_output(('git', '-C', EXT) + args).decode('utf-8', 'replace').strip()


def changed_since(before):
    """Package files changed since the commit before the push (None = unknown: release)."""
    if not before or set(before) == set('0'):
        return None
    try:
        names = git('diff', '--name-only', before, 'HEAD').splitlines()
    except Exception:
        return None
    return [n for n in names if pack.wanted(n) or n.startswith('installer/')]


def main():
    channel = sys.argv[1] if len(sys.argv) > 1 else ''
    if channel not in ('stable', 'beta'):
        sys.exit('usage: ci_release.py stable|beta')
    url, key = (os.environ.get('PEER_URL') or '').strip().rstrip('/'), (os.environ.get('PEER_RELEASE_KEY') or '').strip()
    if not url or not key:
        print('PEER_URL / PEER_RELEASE_KEY are not set - nothing released.')
        return
    changed = changed_since(os.environ.get('PEER_BEFORE'))
    if changed is not None and not changed:
        print('No file of PEER changed in this push - nothing released.')
        return
    backend = HttpBackend(dict(config.DEFAULTS, backend='http', url=url), key=key)
    who = json.loads(backend._call('GET', '/auth'))
    if who.get('role') != 'admin':
        sys.exit('The release key is not an admin key.')
    note = git('log', '-1', '--pretty=%s')[:300] or 'update'
    manifest, _ = backend.release_manifest(releases.EXT)
    ver = releases.next_version(manifest, datetime.datetime.now().strftime('%Y.%m.%d'))
    out = tempfile.mkdtemp(prefix='peer_release_')
    raw = os.path.join(out, 'source.zip')
    subprocess.check_call(['git', '-C', EXT, 'archive', '--format=zip', '-o', raw, 'HEAD'])
    name = 'PEER_dev' if channel == 'beta' else 'PEER'
    full = os.path.join(out, '{0}-{1}.zip'.format(name, ver))
    boot = os.path.join(out, '{0}-loader-{1}.zip'.format(name, ver))
    n_full = pack.build(raw, full, ver, channel)[0]
    n_boot = pack.build(raw, boot, ver, channel, flavor='boot')[0]
    for product, path in ((releases.EXT, full), (releases.BOOT, boot)):
        sha = rfa_info.sha1(path)
        backend.release_upload(product, ver, path, sha)
        backend.release_publish(product, ver, channel, note, sha, os.path.basename(path))
    import zipfile
    with zipfile.ZipFile(raw) as z:
        ps1 = z.read('installer/install.ps1').decode('utf-8')
    inst = os.path.join(out, 'PEER_install.bat')
    with open(inst, 'wb') as f:
        f.write(pack.installer_bat(ps1).encode('ascii'))
    backend._call('PUT', '/install', raw=inst)
    print('Released {0} {1} to {2}: {3} files, loader {4} files. Note: {5}'.format(name, ver, channel, n_full, n_boot, note))


if __name__ == '__main__':
    main()
