# -*- coding: utf-8 -*-
"""What goes into the PEER package (pure rules + the zip builder).

The package is what a colleague's computer needs to run PEER - not the
service code, tests, release tools, old script copies or caches.
build(source_zip, out_zip, version, channel) repacks a `git archive` zip and
adds files.json / version.json (see ext_update.py).
"""

import datetime
import hashlib
import io
import json
import zipfile

SKIP_PREFIXES = (
    u'service/',                 # the Cloudflare worker
    u'feedback/',                # receiver script and setup notes
    u'docs/',
    u'installer/',               # downloaded from the site, not part of PEER
    u'lib/.idea/',
    u'lib/peer_library/tests/',
    u'lib/peer_feedback/tests/',
    u'lib/peer_library/tools/',
    u'lib/Samples/',
)
SKIP_PARTS = (u'OLD', u'__pycache__', u'.idea', u'.git')
SKIP_NAMES = (u'PEER_install.zip', u'install.bat', u'README.md', u'.gitignore', u'.gitattributes',
              u'files.json', u'version.json')
SKIP_SUFFIXES = (u'.pyc', u'.bak', u'.orig', u'.rej')


def wanted(rel):
    """True when the repo file rel ('a/b/c.py') belongs in the package."""
    rel = rel.replace(u'\\', u'/')
    if not rel or rel.endswith(u'/'):
        return False
    parts = rel.split(u'/')
    if any(p in SKIP_PARTS for p in parts):
        return False
    if len(parts) == 1 and parts[0] in SKIP_NAMES:
        return False
    if any(rel.startswith(p) for p in SKIP_PREFIXES):
        return False
    low = parts[-1].lower()
    if low.endswith(SKIP_SUFFIXES) or u'.bak_' in low:
        return False
    try:
        rel.encode('ascii')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False                     # notes folders with non-ASCII names are not PEER code
    return True


# The loader: what anybody may install without a key - signing in, the library
# client, help (Feedback) and the updater. No PEER tools.
LOADER_FILES = (u'startup.py', u'extensions.json', u'lib/__init__.py', u'lib/peer_update.py',
                u'lib/peer_access.py', u'lib/peer_log.py', u'PEER.tab/bundle.yaml')
LOADER_PREFIXES = (u'lib/peer_library/', u'lib/peer_feedback/', u'PEER.tab/Account.panel/',
                   u'PEER.tab/Library.panel/', u'PEER.tab/Feedback.panel/', u'hooks/')


def in_loader(rel):
    rel = rel.replace(u'\\', u'/')
    return wanted(rel) and (rel in LOADER_FILES or any(rel.startswith(p) for p in LOADER_PREFIXES))


def build(source_zip, out_zip, version, channel=u'stable', built=None, flavor=u'full'):
    """Returns (file count, sha1 of out_zip, size). flavor 'boot' = the loader only."""
    built = built or datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    keep = in_loader if flavor == 'boot' else wanted
    files = {}
    with zipfile.ZipFile(source_zip) as src, zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as out:
        for info in sorted(src.infolist(), key=lambda i: i.filename):
            rel = info.filename
            if not keep(rel):
                continue
            data = src.read(info)
            files[rel] = hashlib.sha1(data).hexdigest()
            out.writestr(zipfile.ZipInfo(rel, (1980, 1, 1, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
        for must in (u'startup.py', u'lib/peer_update.py', u'lib/peer_library/ext_update.py'):
            if must not in files:
                raise Exception(u'The package would miss {0} - wrong source?'.format(must))
        meta = json.dumps({'version': version, 'files': files}, sort_keys=True, indent=0)
        out.writestr(zipfile.ZipInfo(u'files.json', (1980, 1, 1, 0, 0, 0)), meta, zipfile.ZIP_DEFLATED)
        meta_ver = {'version': version, 'channel': channel, 'built': built}
        if flavor == 'boot':
            meta_ver['flavor'] = 'boot'
        ver = json.dumps(meta_ver, sort_keys=True)
        out.writestr(zipfile.ZipInfo(u'version.json', (1980, 1, 1, 0, 0, 0)), ver, zipfile.ZIP_DEFLATED)
    h = hashlib.sha1()
    with io.open(out_zip, 'rb') as f:
        data = f.read()
    h.update(data)
    return len(files), h.hexdigest(), len(data)
