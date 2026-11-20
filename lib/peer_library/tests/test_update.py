# -*- coding: utf-8 -*-
"""PEER package update without Revit:
    py -3 -m unittest discover -s lib/peer_library/tests

The service is a fake backend over a folder; the installation is a temp folder."""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from peer_library import ext_update as U  # noqa: E402
from peer_library import releases as R  # noqa: E402
from peer_library import rfa_info, version  # noqa: E402
from peer_library.backend_base import AccessError, OfflineError  # noqa: E402


def sha(data):
    return hashlib.sha1(data).hexdigest()


def make_zip(path, ver, files, channel=u'stable', listed=None, extra=None):
    """A package: files {rel: bytes} + files.json + version.json."""
    listed = dict((k, sha(v)) for k, v in files.items()) if listed is None else listed
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel, data in files.items():
            z.writestr(rel, data)
        for rel, data in (extra or {}).items():
            z.writestr(rel, data)
        z.writestr('files.json', json.dumps({'version': ver, 'files': listed}))
        z.writestr('version.json', json.dumps({'version': ver, 'channel': channel, 'built': u'now'}))
    return path


class FakeService(object):
    """backend with the release calls of HttpBackend."""

    def __init__(self, folder):
        self.folder = folder
        self.manifest = {'channels': {'stable': u'', 'beta': u''}, 'versions': []}
        self.key = True
        self.offline = False
        self.revoked = False
        self.downloads = []
        self.damage = False

    def has_key(self):
        return self.key

    def add(self, ver, files, channel='stable', **kw):
        p = make_zip(os.path.join(self.folder, ver + '.zip'), ver, files, **kw)
        self.manifest['versions'].append({'version': ver, 'sha1': rfa_info.sha1(p),
                                          'size': os.path.getsize(p), 'note': u'note ' + ver})
        self.manifest['channels'][channel] = ver

    def release_manifest(self, product, etag=None, quick=False):
        if self.revoked:
            raise AccessError(u'This library key is not valid any more - ask an admin.')
        if self.offline:
            raise OfflineError(u'No connection to the library service (test).')
        tag = sha(json.dumps(self.manifest, sort_keys=True).encode('utf-8'))
        if etag == tag:
            return None, tag
        return json.loads(json.dumps(self.manifest)), tag

    def release_download(self, product, ver, target):
        if self.offline:
            raise OfflineError(u'No connection to the library service (test).')
        self.downloads.append(ver)
        shutil.copyfile(os.path.join(self.folder, ver + '.zip'), target)
        if self.damage:
            with open(target, 'ab') as f:
                f.write(b'x')
        return target


class TestReleases(unittest.TestCase):

    def test_version_order(self):
        self.assertTrue(R.vkey('2026.11.20.10') > R.vkey('2026.11.20.9'))
        self.assertTrue(R.vkey('14') > R.vkey('9'))
        self.assertEqual(R.vkey('git 0123456'), ())

    def test_target_by_channel(self):
        m = {'channels': {'stable': '2', 'beta': '3'},
             'versions': [{'version': '1'}, {'version': '2'}, {'version': '3'}]}
        self.assertEqual(R.target(m, 'stable')['version'], '2')
        self.assertEqual(R.target(m, 'beta')['version'], '3')
        m['channels'] = {'stable': '3', 'beta': '2'}          # stable overtook beta
        self.assertEqual(R.target(m, 'beta')['version'], '3')
        m['channels'] = {'stable': '2', 'beta': ''}
        self.assertEqual(R.target(m, 'beta')['version'], '2')
        self.assertIsNone(R.target({'channels': {'stable': '', 'beta': '3'}, 'versions': [{'version': '3'}]}))
        self.assertIsNone(R.target({}, 'stable'))
        self.assertIsNone(R.target({'channels': {'stable': '9'}, 'versions': []}))   # file already removed

    def test_news(self):
        m = {'channels': {'stable': '3', 'beta': '4'},
             'versions': [{'version': str(i), 'note': 'n%d' % i} for i in (1, 2, 3, 4)]}
        self.assertEqual(R.news(m, '1'), [('3', 'n3'), ('2', 'n2')])
        self.assertEqual(R.news(m, '3'), [])
        self.assertEqual(R.news(m, 'git abc', 'beta')[0], ('4', 'n4'))

    def test_next_version(self):
        m = {'versions': [{'version': '2026.11.20.1'}, {'version': '2026.11.20.2'}, {'version': '2026.11.19.7'}]}
        self.assertEqual(R.next_version(m, '2026.11.20'), '2026.11.20.3')
        self.assertEqual(R.next_version(m, '2026.11.21'), '2026.11.21.1')
        self.assertEqual(R.next_version({}, '2026.01.05'), '2026.01.05.1')


class TestPack(unittest.TestCase):

    def test_what_goes_into_the_package(self):
        from peer_library import pack
        yes = [u'startup.py', u'extensions.json', u'lib/peer_update.py', u'lib/peer_library/loader.py',
               u'PEER.tab/Walls.panel/WallRebar2D.pushbutton/PR_Wall2D_Edge.rfa', u'hooks/doc-opened.py',
               u'PEER.tab/Account.panel/Account.pushbutton/icon.png', u'lib/peer_library/settings.json']
        no = [u'service/src/worker.js', u'feedback/receiver/Code.gs', u'docs/LIBRARY.md', u'README.md',
              u'lib/peer_library/tests/test_core.py', u'lib/peer_library/tools/release/release.ps1',
              u'PEER.tab/Columns.panel/CreateColumn.pushbutton/OLD/1.py', u'install.bat', u'PEER_install.zip',
              u'lib/PEER_Sheets/__pycache__/ui.cpython-313.pyc', u'lib/kz_dims.py.bak_2026-09-24',
              u'lib/.idea/misc.xml', u'\u0418\u0434\u0435\u0438/plan.md', u'files.json', u'version.json', u'',
              u'lib/Samples/x.py', u'PEER.tab/', u'installer/install.ps1']
        for rel in yes:
            self.assertTrue(pack.wanted(rel), rel)
        for rel in no:
            self.assertFalse(pack.wanted(rel), rel)

    def test_build_is_repeatable_and_complete(self):
        from peer_library import pack
        tmp = tempfile.mkdtemp(prefix='peerpack_')
        try:
            src = os.path.join(tmp, 'src.zip')
            with zipfile.ZipFile(src, 'w') as z:
                for rel in (u'startup.py', u'lib/peer_update.py', u'lib/peer_library/ext_update.py', u'service/x.js'):
                    z.writestr(rel, rel.encode('ascii'))
            a = pack.build(src, os.path.join(tmp, 'a.zip'), '1', 'beta', built='t')
            b = pack.build(src, os.path.join(tmp, 'b.zip'), '1', 'beta', built='t')
            self.assertEqual(a, b)                                  # same input -> same bytes
            self.assertEqual(a[0], 3)
            files = U.stage(os.path.join(tmp, 'a.zip'), os.path.join(tmp, 'stage'))
            self.assertEqual(sorted(files), [u'lib/peer_library/ext_update.py', u'lib/peer_update.py', u'startup.py'])
            with zipfile.ZipFile(src, 'w') as z:
                z.writestr(u'startup.py', b'only this')
            with self.assertRaises(Exception):
                pack.build(src, os.path.join(tmp, 'c.zip'), '1')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestUpdate(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='peerupd_')
        self.ext = os.path.join(self.tmp, 'PEER.extension')
        self.work = os.path.join(self.tmp, 'work')
        os.makedirs(self.ext)
        os.makedirs(os.path.join(self.tmp, 'svc'))
        self.svc = FakeService(os.path.join(self.tmp, 'svc'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, channel='stable', old=None):
        return U.sync(self.ext, self.svc, channel, self.work, old)

    def read(self, rel):
        with open(os.path.join(self.ext, *rel.split('/')), 'rb') as f:
            return f.read()

    def write(self, rel, data):
        p = os.path.join(self.ext, *rel.split('/'))
        if not os.path.isdir(os.path.dirname(p)):
            os.makedirs(os.path.dirname(p))
        with open(p, 'wb') as f:
            f.write(data)

    V1 = {'startup.py': b'one', 'lib/a.py': b'a1', 'PEER.tab/X.panel/B.pushbutton/script.py': b'b1'}

    # ---------------------------------------------------------------------
    def test_first_install_then_clean(self):
        self.svc.add('1', self.V1)
        status, det = self.sync()
        self.assertEqual(status, 'updated', det)
        self.assertEqual(self.read('lib/a.py'), b'a1')
        self.assertEqual(version.get(self.ext)['version'], u'1')
        self.assertEqual(self.sync(), ('clean', u'1'))
        self.assertEqual(self.svc.downloads, ['1'])                 # downloaded once

    def test_update_writes_changed_removes_deleted_keeps_foreign(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.write('lib/__pycache__/a.pyc', b'cache')               # not PEER's
        self.write('my notes.txt', b'mine')
        v2 = {'startup.py': b'one', 'lib/a.py': b'a2', 'lib/new.py': b'n'}
        self.svc.add('2', v2)
        status, det = self.sync()
        self.assertEqual(status, 'updated', det)
        self.assertIn(u'2 file(s) written, 1 removed', det)
        self.assertEqual(self.read('lib/a.py'), b'a2')
        self.assertEqual(self.read('lib/new.py'), b'n')
        self.assertFalse(os.path.exists(os.path.join(self.ext, 'PEER.tab')))    # empty folders go too
        self.assertEqual(self.read('my notes.txt'), b'mine')
        self.assertEqual(self.read('lib/__pycache__/a.pyc'), b'cache')
        self.assertEqual(version.get(self.ext)['version'], u'2')

    def test_local_edit_and_deleted_file_are_repaired(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.write('lib/a.py', b'edited by a person')
        os.remove(os.path.join(self.ext, 'startup.py'))
        status, det = self.sync()
        self.assertEqual(status, 'updated', det)
        self.assertEqual(self.read('lib/a.py'), b'a1')
        self.assertEqual(self.read('startup.py'), b'one')
        self.assertEqual(self.svc.downloads, ['1'])                 # repaired from the kept zip

    def test_roll_back_follows_the_channel(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.svc.add('2', {'startup.py': b'two'})
        self.sync()
        self.assertFalse(os.path.exists(os.path.join(self.ext, 'lib', 'a.py')))
        self.svc.manifest['channels']['stable'] = '1'               # admin points stable back
        status, det = self.sync()
        self.assertEqual(status, 'updated', det)
        self.assertEqual(self.read('startup.py'), b'one')
        self.assertEqual(self.read('lib/a.py'), b'a1')
        self.assertEqual(version.get(self.ext)['version'], u'1')

    def test_beta_channel(self):
        self.svc.add('1', self.V1)
        self.svc.add('2', {'startup.py': b'beta'}, channel='beta')
        self.sync('stable')
        self.assertEqual(self.read('startup.py'), b'one')
        self.sync('beta')
        self.assertEqual(self.read('startup.py'), b'beta')
        self.assertEqual(version.text(self.ext, 'beta'), u'2 (beta)')

    def test_no_key_offline_revoked_nothing_published(self):
        self.assertEqual(self.sync()[0], 'none')
        self.svc.add('1', self.V1)
        self.svc.key = False
        self.assertEqual(self.sync()[0], 'nokey')
        self.svc.key, self.svc.offline = True, True
        self.assertEqual(self.sync()[0], 'offline')
        self.svc.offline, self.svc.revoked = False, True
        self.assertEqual(self.sync()[0], 'nokey')
        self.assertEqual(os.listdir(self.ext), [])                  # nothing was touched

    def test_installed_copy_keeps_working_offline(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.svc.offline = True
        self.assertEqual(self.sync()[0], 'offline')
        self.assertEqual(self.read('lib/a.py'), b'a1')

    def test_damaged_download_changes_nothing(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.svc.add('2', {'startup.py': b'two'})
        self.svc.damage = True
        status, det = self.sync()
        self.assertEqual(status, 'error')
        self.assertIn(u'damaged', det)
        self.assertEqual(self.read('startup.py'), b'one')
        self.assertEqual(version.get(self.ext)['version'], u'1')
        self.svc.damage = False                                     # next start: fine
        self.assertEqual(self.sync()[0], 'updated')
        self.assertEqual(self.read('startup.py'), b'two')

    def test_package_with_a_wrong_file_list_is_refused(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.svc.add('2', {'startup.py': b'two'}, listed={'startup.py': sha(b'something else')})
        status, det = self.sync()
        self.assertEqual(status, 'error')
        self.assertEqual(self.read('startup.py'), b'one')

    def test_package_cannot_write_outside_the_extension(self):
        for bad in (u'../evil.py', u'/abs.py', u'C:/x.py', u'lib/../../evil.py', u'lib//x.py'):
            with self.assertRaises(U.UpdateError):
                U._safe(bad)
        self.svc.add('1', {'startup.py': b'one'}, listed={'startup.py': sha(b'one'), '../evil.py': sha(b'e')})
        self.assertEqual(self.sync()[0], 'error')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'evil.py')))

    def test_interrupted_update_finishes_next_time(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.svc.add('2', {'startup.py': b'two', 'lib/a.py': b'a2'})
        real = U._copy
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if dst.endswith('startup.py'):
                raise IOError('in use')
            real(src, dst)
        U._copy = flaky
        try:
            status, det = self.sync()
        finally:
            U._copy = real
        self.assertEqual(status, 'partial', det)
        self.assertEqual(version.get(self.ext)['version'], u'1')    # version.json is the commit point
        self.assertEqual(self.read('lib/a.py'), b'a2')
        status, det = self.sync()
        self.assertEqual(status, 'updated', det)
        self.assertEqual(self.read('startup.py'), b'two')
        self.assertEqual(version.get(self.ext)['version'], u'2')

    def test_git_clone_becomes_a_package(self):
        self.write('startup.py', b'old from git')
        self.write('lib/gone.py', b'deleted from PEER later')
        self.write('lib/untracked.log', b'log')
        self.write('.git/HEAD', b'ref: refs/heads/main\n')
        self.svc.add('1', self.V1)
        tracked = {'startup.py': u'', 'lib/gone.py': u''}
        status, det = self.sync(old=tracked)
        self.assertEqual(status, 'updated', det)
        self.assertEqual(self.read('startup.py'), b'one')
        self.assertFalse(os.path.exists(os.path.join(self.ext, 'lib', 'gone.py')))
        self.assertEqual(self.read('lib/untracked.log'), b'log')
        self.assertEqual(version.get(self.ext)['kind'], 'package')

    def test_old_zips_are_tidied(self):
        for v in ('1', '2', '3', '4'):
            self.svc.add(v, {'startup.py': v.encode('ascii')})
            self.sync()
        zips = sorted(f for f in os.listdir(self.work) if f.endswith('.zip'))
        self.assertEqual(zips, ['ext-3.zip', 'ext-4.zip'])

    def test_manifest_not_downloaded_again_when_unchanged(self):
        self.svc.add('1', self.V1)
        self.sync()
        seen = []
        real = self.svc.release_manifest

        def spy(product, etag=None, quick=False):
            data, tag = real(product, etag, quick)
            seen.append((etag is not None, data is None, quick))
            return data, tag
        self.svc.release_manifest = spy
        self.assertEqual(self.sync()[0], 'clean')
        self.assertEqual(seen, [(True, True, True)])                # tag sent, 304, short timeout


if __name__ == '__main__':
    unittest.main()
