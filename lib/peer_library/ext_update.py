# -*- coding: utf-8 -*-
"""Keep an installed PEER identical to the package on the service.

The package is a zip of the extension with two files at its root:
    files.json    {"version": "...", "files": {"rel/path": sha1, ...}}
    version.json  {"version", "channel", "built"}   (peer_library/version.py)

sync(ext_dir, backend, channel, work_dir):
    1. manifest of the 'ext' product -> the version this computer should run;
    2. already that version and every file matches files.json -> 'clean';
    3. otherwise the zip (downloaded once, SHA-1 checked) is unpacked next to
       the installation and the folder is brought to it: changed files copied,
       files of the old list that the new one does not have removed, files
       PEER does not own (logs, caches, a person's own files) left alone.
       version.json is written last - a start that was interrupted finishes
       on the next one.
A person's edits in PEER files are overwritten on purpose (as git reset did).
Pure Python + zip; runs under IronPython (Revit) and CPython (tests).
"""

import io
import os
import shutil

from peer_library import jsonio, releases, rfa_info, version
from peer_library.backend_base import AccessError, LibraryError, OfflineError

FILES = 'files.json'
OWN = (FILES, version.FILE)          # written by the updater itself, last
KEEP_ZIPS = 2
# what updates PEER: written after everything else, and only if the new code
# compiles here (a broken updater could never bring the next fix)
CORE = (u'startup.py', u'lib/peer_update.py', u'lib/peer_library/ext_update.py',
        u'lib/peer_library/releases.py', u'lib/peer_library/version.py', u'lib/peer_library/jsonio.py',
        u'lib/peer_library/rfa_info.py', u'lib/peer_library/config.py', u'lib/peer_library/keystore.py',
        u'lib/peer_library/backend_base.py', u'lib/peer_library/backend_http.py', u'lib/peer_library/log.py')


class UpdateError(Exception):
    pass


def _safe(rel):
    rel = (rel or u'').replace(u'\\', u'/')
    parts = rel.split(u'/')
    if not rel or rel.startswith(u'/') or u':' in rel or any(p in (u'', u'.', u'..') for p in parts):
        raise UpdateError(u'Bad path in the package: {0}'.format(rel))
    return os.path.join(*parts)


def _unzip(zip_path, folder):
    try:
        import clr
    except ImportError:
        import zipfile
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if not name.endswith('/'):
                    _safe(name)
            z.extractall(folder)
        return
    clr.AddReference('System.IO.Compression.FileSystem')
    from System.IO.Compression import ZipFile
    ZipFile.ExtractToDirectory(zip_path, folder)     # refuses entries outside the folder


def _rmtree(folder):
    def on_error(fn, path, exc):
        try:
            os.chmod(path, 0o666)
            fn(path)
        except Exception:
            pass
    if os.path.isdir(folder):
        shutil.rmtree(folder, onerror=on_error)
    return not os.path.exists(folder)


def _copy(src, dst):
    """Copy next to dst, then swap: an interrupted copy never leaves half a file."""
    folder = os.path.dirname(dst)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    tmp = dst + u'.peer_new'
    shutil.copyfile(src, tmp)
    try:
        if os.path.exists(dst):
            os.chmod(dst, 0o666)
        jsonio.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def check_core(staged, files):
    """The updater files of the package must compile with this Python (IronPython
    in Revit). Raises UpdateError."""
    for rel in CORE:
        if rel not in files:
            continue
        p = os.path.join(staged, _safe(rel))
        try:
            with io.open(p, 'r', encoding='utf-8-sig') as f:
                compile(f.read(), p, 'exec')
        except (SyntaxError, ValueError, TypeError) as ex:
            raise UpdateError(u'The package does not run here ({0}: {1}) - not installed.'.format(rel, ex))


def installed_files(ext_dir):
    data = jsonio.read(os.path.join(ext_dir, FILES))
    files = data.get('files') if isinstance(data, dict) else None
    return files if isinstance(files, dict) else {}


def changed(ext_dir, files):
    """Tracked files that are missing or differ from the list."""
    out = []
    for rel, sha in files.items():
        p = os.path.join(ext_dir, _safe(rel))
        if not os.path.isfile(p) or rfa_info.sha1(p) != sha:
            out.append(rel)
    return sorted(out)


def stage(zip_path, folder, flavor=None, edition=None):
    """Unpack and verify the package. Returns its file list {rel: sha1}."""
    _rmtree(folder)
    os.makedirs(folder)
    _unzip(zip_path, folder)
    data = jsonio.read(os.path.join(folder, FILES))
    files = data.get('files') if isinstance(data, dict) else None
    if not isinstance(files, dict) or not files:
        raise UpdateError(u'The package has no file list.')
    if not version.get(folder).get('version') or version.get(folder)['kind'] != 'package':
        raise UpdateError(u'The package has no version.')
    if flavor is not None and version.get(folder)['flavor'] != flavor:
        raise UpdateError(u'This is not the package that was asked for ({0}).'.format(version.get(folder)['flavor']))
    if edition is not None and version.get(folder)['edition'] != edition:
        raise UpdateError(u'This package is the {0} edition of PEER - not for this channel.'.format(
            version.get(folder)['edition']))
    check_core(folder, files)
    for rel, sha in files.items():
        p = os.path.join(folder, _safe(rel))
        if not os.path.isfile(p) or rfa_info.sha1(p) != sha:
            raise UpdateError(u'The package is damaged: {0}'.format(rel))
    return files


def apply(staged, ext_dir, files, old_files):
    """Bring ext_dir to the staged package. Returns (copied, removed, failed)."""
    copied, removed, failed = [], [], []
    core = [r for r in CORE if r in files]
    order = [r for r in sorted(files) if r not in core] + core      # the updater last
    for rel in order:
        src = os.path.join(staged, _safe(rel))
        dst = os.path.join(ext_dir, _safe(rel))
        if os.path.isfile(dst) and rfa_info.sha1(dst) == files[rel]:
            continue
        try:
            _copy(src, dst)
            copied.append(rel)
        except (IOError, OSError) as ex:
            failed.append(u'{0}: {1}'.format(rel, ex))
            if rel in core:
                break                    # the rest of the updater stays as it was, consistent
    have = set(k.lower() for k in files)
    for rel in sorted(old_files or {}):
        if rel.lower() in have or rel in OWN:
            continue
        try:
            p = os.path.join(ext_dir, _safe(rel))
        except UpdateError:
            continue
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o666)
                os.remove(p)
                removed.append(rel)
                d = os.path.dirname(p)
                while d and os.path.normcase(d) != os.path.normcase(ext_dir) and not os.listdir(d):
                    os.rmdir(d)
                    d = os.path.dirname(d)
            except (IOError, OSError) as ex:
                failed.append(u'{0}: {1}'.format(rel, ex))
    if not failed:
        for name in OWN:                        # version.json last: the commit point
            _copy(os.path.join(staged, name), os.path.join(ext_dir, name))
    return copied, removed, failed


def _zip_name(v, product=releases.EXT):
    return u'{0}-{1}.zip'.format(product, v)


def _tidy(work_dir, keep, product=releases.EXT):
    head = product + '-'
    try:
        zips = sorted((f for f in os.listdir(work_dir) if f.startswith(head) and f.endswith('.zip')),
                      key=lambda f: releases.vkey(f[len(head):-4]))
    except OSError:
        return
    keep = set(keep)
    for f in zips[:-KEEP_ZIPS]:
        if f not in keep:
            try:
                os.remove(os.path.join(work_dir, f))
            except OSError:
                pass


def read_manifest(backend, work_dir, quick=True, product=releases.EXT):
    """Manifest from the service (ETag copy in work_dir). Raises OfflineError."""
    copy = os.path.join(work_dir, '{0}_manifest.json'.format(product))
    tag_file = copy + '.etag'
    old = None
    if os.path.isfile(copy) and os.path.isfile(tag_file):
        try:
            with io.open(tag_file, 'r', encoding='utf-8') as f:
                old = f.read().strip() or None
        except (IOError, OSError):
            old = None
    data, tag = backend.release_manifest(product, old, quick)
    if data is None:
        data = jsonio.read(copy)
        if data is None:
            data, tag = backend.release_manifest(product, None, quick)
    if not os.path.isdir(work_dir):
        os.makedirs(work_dir)
    jsonio.write(copy, data)
    try:
        with io.open(tag_file, 'w', encoding='utf-8') as f:
            f.write(u'{0}'.format(tag or u''))
    except (IOError, OSError):
        pass
    return data


def _prepare(ext_dir, backend, channel, work_dir, product):
    """Everything up to touching the installation. Returns (status, details) when
    there is nothing to install, else ('needed', (zip_path, goal, have, mine, want_edition)):
    the package is downloaded and its SHA-1 checked."""
    boot = product == releases.BOOT
    if not boot and not backend.has_key():
        return 'nokey', u'no PEER key on this computer - sign in (PEER -> Account)'
    if boot and not version.is_loader(ext_dir) and installed_files(ext_dir):
        return 'clean', u'the full PEER is installed - the loader is not needed'
    try:
        manifest = read_manifest(backend, work_dir, product=product)
    except OfflineError as ex:
        return 'offline', u'{0}'.format(ex)
    except AccessError as ex:
        return 'nokey', u'{0}'.format(ex)
    except LibraryError as ex:
        return 'error', u'{0}'.format(ex)
    goal = releases.target(manifest, channel, follow=False)
    if goal is None:
        return 'none', u'no PEER package is published yet'
    want_edition = u'dev' if channel == releases.BETA else u'stable'
    want = goal['version']
    have = version.get(ext_dir)
    mine = installed_files(ext_dir)
    same_flavor = (have['flavor'] == 'boot') == boot       # a loader always takes the full PEER
    if have['kind'] == 'package' and have['edition'] != want_edition:
        return 'error', u'this installation is the {0} edition, the channel {1} is the other one'.format(
            have['edition'], channel)
    if have['kind'] == 'package' and have['version'] == want and same_flavor and mine and \
            not changed(ext_dir, mine):
        return 'clean', want
    zip_path = os.path.join(work_dir, _zip_name(want, product))
    try:
        if not os.path.isfile(zip_path) or rfa_info.sha1(zip_path) != goal.get('sha1'):
            backend.release_download(product, want, zip_path)
            if rfa_info.sha1(zip_path) != goal.get('sha1'):
                os.remove(zip_path)
                return 'error', u'the downloaded package {0} is damaged - will try again'.format(want)
    except OfflineError as ex:
        return 'offline', u'{0}'.format(ex)
    except (LibraryError, IOError, OSError) as ex:
        return 'error', u'{0}'.format(ex)
    return 'needed', (zip_path, goal, have, mine, want_edition)


def check(ext_dir, backend, channel, work_dir, product=releases.EXT):
    """Is there something to install? Nothing in the installation is touched.
    -> (status, details): 'needed' = the package is downloaded and verified,
    sync() will apply it; else as sync() (clean / none / nokey / offline / error)."""
    status, det = _prepare(ext_dir, backend, channel, work_dir, product)
    if status == 'needed':
        return 'needed', u'{0} -> {1}'.format(det[2]['version'], det[1]['version'])
    return status, det


def sync(ext_dir, backend, channel, work_dir, old_files=None, product=releases.EXT):
    """-> (status, details). status: clean / updated / partial / none / nokey /
    offline / error. old_files: tracked files of an installation that has no
    files.json yet (a git clone being converted).
    product 'ext' = the full PEER (needs a key); 'boot' = the public loader,
    only for an installation that is a loader itself (never replaces a full one)."""
    boot = product == releases.BOOT
    status, det = _prepare(ext_dir, backend, channel, work_dir, product)
    if status != 'needed':
        return status, det
    zip_path, goal, have, mine, want_edition = det
    want = goal['version']
    try:
        staged = os.path.join(work_dir, 'stage')
        files = stage(zip_path, staged, u'boot' if boot else u'full', want_edition)
        copied, removed, failed = apply(staged, ext_dir, files, mine or old_files or {})
        _rmtree(staged)
    except (LibraryError, UpdateError, IOError, OSError) as ex:
        return 'error', u'{0}'.format(ex)
    _tidy(work_dir, [_zip_name(want, product), _zip_name(have['version'], product)], product)
    det = u'{0} -> {1}: {2} file(s) written, {3} removed'.format(have['version'], want, len(copied), len(removed))
    if failed:
        return 'partial', det + u'; could not write (next start tries again): ' + u'; '.join(failed[:10])
    return 'updated', det
