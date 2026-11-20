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
                'built': data.get('built') or u'', 'kind': 'package',
                'flavor': u'boot' if data.get('flavor') == 'boot' else u'full',
                'edition': u'dev' if data.get('edition') == 'dev' else u'stable'}
    sha = _git_sha(folder)
    if sha:
        return {'version': u'git {0}'.format(sha), 'channel': u'', 'built': u'', 'kind': 'git', 'flavor': u'full',
                'edition': u'stable'}
    return {'version': u'dev', 'channel': u'', 'built': u'', 'kind': 'dev', 'flavor': u'full', 'edition': u'stable'}


# Two editions can sit side by side in one Revit, each with its own ribbon tab:
#   PEER       branch main, what everybody runs     PEER.extension / PEER.tab         channel stable
#   PEER_dev   branch dev, for trying new things    PEER_dev.extension / PEER_dev.tab channel beta
# They share the key, the service and the family library; only the tools differ.
DEV_EXT, DEV_TAB = u'PEER_dev', u'PEER_dev'


def edition(folder=None):
    """'stable' | 'dev' of the installation in folder."""
    return get(folder)['edition']


def channel_of(folder=None):
    """The release channel an installation follows: its edition decides."""
    return u'beta' if edition(folder) == 'dev' else u'stable'


def tab_dir(folder=None):
    """The ribbon tab folder of this extension (PEER.tab, or PEER_dev.tab in the dev edition)."""
    folder = folder or ext_dir()
    for name in (u'PEER.tab', DEV_TAB + u'.tab'):
        p = os.path.join(folder, name)
        if os.path.isdir(p):
            return p
    return os.path.join(folder, u'PEER.tab')


_BUNDLES = {}


def bundle_dir(name, folder=None):
    """Folder of a button of this extension by its name ('Library.smartbutton'),
    wherever it sits in the tab (panel, stack, pulldown). The ribbon layout can
    change without breaking the paths to the windows."""
    tab = tab_dir(folder)
    key = (tab, name)
    if key not in _BUNDLES or not os.path.isdir(_BUNDLES[key]):
        found = os.path.join(tab, name)
        for root, dirs, files in os.walk(tab):
            if name in dirs:
                found = os.path.join(root, name)
                break
        _BUNDLES[key] = found
    return _BUNDLES[key]


def tab_name(folder=None):
    return os.path.basename(tab_dir(folder))[:-len('.tab')]


def is_secondary(folder=None):
    """True in the dev edition when the everyday PEER is installed next to it:
    the things both would do at Revit start (notifications, the template,
    usage upload) are left to the everyday one."""
    folder = folder or ext_dir()
    if edition(folder) != 'dev':
        return False
    return os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(folder)), u'PEER.extension'))


def is_loader(folder=None):
    """True on an installation that holds only the loader (Account + updater):
    the full PEER comes after signing in."""
    return get(folder)['flavor'] == 'boot'


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
    text = v['version'] + (u' dev' if v['edition'] == 'dev' else u'') + (u' loader' if v['flavor'] == 'boot' else u'')
    if v['kind'] == 'package' and channel == 'beta' and v['edition'] != 'dev':
        return u'{0} (beta)'.format(text)
    return text
