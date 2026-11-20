# -*- coding: utf-8 -*-
"""Which PEER is installed on this computer.

    <extension>/version.json   {"version": "2026.11.20.1", "channel": "stable", "built": "..."}
is written by the release script into every package. A git clone (the old
installer, or the author's working copy) has no such file - then the version
is 'git <short sha>' or 'dev'.
"""

import io
import os

from peer_library import jsonio

FILE = 'version.json'


def ext_dir():
    """The extension folder (parent of lib/)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git_sha(folder):
    try:
        with io.open(os.path.join(folder, '.git', 'HEAD'), 'r', encoding='utf-8') as f:
            head = f.read().strip()
        if not head.startswith('ref:'):
            return head[:7]
        ref = os.path.join(folder, '.git', *head[4:].strip().split('/'))
        with io.open(ref, 'r', encoding='utf-8') as f:
            return f.read().strip()[:7]
    except (IOError, OSError):
        return u''


def get(folder=None):
    """{'version', 'channel', 'built', 'kind': 'package' | 'git' | 'dev'}"""
    folder = folder or ext_dir()
    data = jsonio.read(os.path.join(folder, FILE))
    if isinstance(data, dict) and data.get('version'):
        return {'version': u'{0}'.format(data['version']), 'channel': data.get('channel') or u'stable',
                'built': data.get('built') or u'', 'kind': 'package'}
    sha = _git_sha(folder)
    if sha:
        return {'version': u'git {0}'.format(sha), 'channel': u'', 'built': u'', 'kind': 'git'}
    return {'version': u'dev', 'channel': u'', 'built': u'', 'kind': 'dev'}


def text(folder=None, channel=None):
    """'2026.11.20.1' or '2026.11.20.1 (beta)'. The channel is the one this
    computer follows (settings), not the one the package was first published to:
    a beta package promoted to stable is the same file."""
    v = get(folder)
    if channel is None:
        try:
            from peer_library import config
            channel = config.load().get('channel')
        except Exception:
            channel = u''
    if v['kind'] == 'package' and channel == 'beta':
        return u'{0} (beta)'.format(v['version'])
    return v['version']
