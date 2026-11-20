# -*- coding: utf-8 -*-
"""Build the PEER package from a git ref (CPython, nothing is sent anywhere).

    py -3 lib/peer_library/tools/release/build_ext.py <version> [--ref HEAD] [--channel beta] [--out folder]

Only committed files go in (git archive), filtered by peer_library/pack.py.
Prints the path, the SHA-1 and the size.
"""
from __future__ import print_function

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
EXT = os.path.dirname(LIB)
sys.path.insert(0, LIB)

from peer_library import pack, releases  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('version')
    ap.add_argument('--ref', default='HEAD')
    ap.add_argument('--channel', default='beta')
    ap.add_argument('--out', default=os.path.join(tempfile.gettempdir(), 'peer_release'))
    a = ap.parse_args()
    if not releases.vkey(a.version):
        sys.exit('Bad version: ' + a.version)
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    raw = os.path.join(a.out, 'source.zip')
    subprocess.check_call(['git', '-C', EXT, 'archive', '--format=zip', '-o', raw, a.ref])
    sha = subprocess.check_output(['git', '-C', EXT, 'rev-parse', '--short', a.ref]).decode('ascii').strip()
    out = os.path.join(a.out, 'PEER-{0}.zip'.format(a.version))
    count, digest, size = pack.build(raw, out, a.version, a.channel)
    boot = os.path.join(a.out, 'PEER-loader-{0}.zip'.format(a.version))
    bcount, bdigest, bsize = pack.build(raw, boot, a.version, a.channel, flavor='boot')
    os.remove(raw)
    print('PACKAGE', out)
    print('SHA1', digest)
    print('SIZE', size)
    print('FILES', count)
    print('LOADER', boot)
    print('LOADERFILES', bcount, bsize)
    print('COMMIT', sha)


if __name__ == '__main__':
    main()
