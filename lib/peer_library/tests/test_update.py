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
    flavor = 'boot' if os.path.basename(path).startswith('boot-') else None
    """A package: files {rel: bytes} + files.json + version.json."""
    listed = dict((k, sha(v)) for k, v in files.items()) if listed is None else listed
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel, data in files.items():
            z.writestr(rel, data)
        for rel, data in (extra or {}).items():
            z.writestr(rel, data)
        z.writestr('files.json', json.dumps({'version': ver, 'files': listed}))
        meta = {'version': ver, 'channel': channel, 'built': u'now'}
        if flavor:
            meta['flavor'] = flavor
        if channel == u'beta':
            meta['edition'] = 'dev'
        z.writestr('version.json', json.dumps(meta))
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
        p = make_zip(os.path.join(self.folder, ver + '.zip'), ver, files, channel=channel, **kw)
        self.manifest['versions'].append({'version': ver, 'sha1': rfa_info.sha1(p),
                                          'size': os.path.getsize(p), 'note': u'note ' + ver})
        self.manifest['channels'][channel] = ver

    boot = None

    def release_manifest(self, product, etag=None, quick=False):
        if product == 'boot':                           # public: no key needed
            m = self.boot or {'channels': {'stable': u'', 'beta': u''}, 'versions': []}
            return json.loads(json.dumps(m)), 'boot-tag'
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
        name = ('boot-' + ver if product == 'boot' and os.path.isfile(os.path.join(self.folder, 'boot-' + ver + '.zip'))
                else ver)
        shutil.copyfile(os.path.join(self.folder, name + '.zip'), target)
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
        # the PEER package: each channel on its own
        self.assertIsNone(R.target(m, 'beta', follow=False))
        m['channels'] = {'stable': '3', 'beta': '2'}
        self.assertEqual(R.target(m, 'beta', follow=False)['version'], '2')
        self.assertEqual(R.target(m, 'stable', follow=False)['version'], '3')
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


class TestGitBranch(unittest.TestCase):

    def test_branch(self):
        import peer_update
        tmp = tempfile.mkdtemp(prefix='peergit_')
        try:
            self.assertEqual(peer_update.git_branch(tmp), u'')
            os.makedirs(os.path.join(tmp, '.git'))
            for head, want in ((u'ref: refs/heads/main\n', u'main'), (u'ref: refs/heads/dev', u'dev'),
                               (u'0123456789abcdef', u'')):
                with io.open(os.path.join(tmp, '.git', 'HEAD'), 'w', encoding='utf-8') as f:
                    f.write(head)
                self.assertEqual(peer_update.git_branch(tmp), want)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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

    def test_loader_holds_no_tools(self):
        from peer_library import pack
        yes = [u'startup.py', u'lib/peer_update.py', u'lib/peer_access.py', u'lib/peer_library/ui_account.py',
               u'PEER.tab/Account.panel/Account.pushbutton/script.py', u'PEER.tab/bundle.yaml',
               u'PEER.tab/Library.panel/Library.smartbutton/LoginWindow.xaml', u'lib/peer_feedback/client.py',
               u'PEER.tab/Account.panel/AccountTools.stack/Contact.pushbutton/script.py',
               u'PEER.tab/Account.panel/AccountTools.stack/Info.pushbutton/script.py', u'hooks/doc-opened.py']
        no = [u'PEER.tab/Walls.panel/WallRebar2D.pushbutton/script.py', u'lib/wallrebar2d/core.py',
              u'lib/kz_dims.py', u'lib/tributary/engine.js', u'PEER.tab/Sheets.panel/Worksets.pushbutton/script.py',
              u'lib/peer_library/tests/test_core.py', u'lib/peer_feedback/tests/test_x.py', u'service/src/worker.js']
        for rel in yes:
            self.assertTrue(pack.in_loader(rel), rel)
        for rel in no:
            self.assertFalse(pack.in_loader(rel), rel)

    def test_installer_is_one_bat_file(self):
        from peer_library import pack
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        with io.open(os.path.join(here, 'installer', 'install.ps1'), encoding='utf-8') as f:
            ps1 = f.read()
        bat = pack.installer_bat(ps1)
        self.assertTrue(bat.startswith(u'@echo off\r\n'))
        self.assertNotIn(u'\n', bat.replace(u'\r\n', u''))            # CRLF only: cmd needs it
        self.assertEqual(bat.count(pack.INSTALLER_MARK), 1)             # the header builds the marker from two halves
        self.assertIn(u'set "PEER_URL=__PEER_SERVICE_URL__"', bat)
        self.assertIn(u'param(', bat.split(pack.INSTALLER_MARK)[1][:40])
        self.assertNotIn(u'Read-Host', bat)                             # no questions
        ready = pack.installer_bat(ps1, u'https://x.example', u'stable')
        self.assertIn(u'set "PEER_URL=https://x.example"', ready)
        self.assertNotIn(u'__PEER_', ready)
        with self.assertRaises(Exception):
            pack.installer_bat(u'Say "\u043f\u0440\u0438\u0432\u0435\u0442"')

    def test_dev_edition_package_has_its_own_tab(self):
        from peer_library import pack
        self.assertEqual(pack.edition_path(u'PEER.tab/Walls.panel/x.py', 'dev'), u'PEER_dev.tab/Walls.panel/x.py')
        self.assertEqual(pack.edition_path(u'PEER.tab/Walls.panel/x.py', 'stable'), u'PEER.tab/Walls.panel/x.py')
        self.assertEqual(pack.edition_path(u'lib/PEER.tab/x.py', 'dev'), u'lib/PEER.tab/x.py')
        tmp = tempfile.mkdtemp(prefix='peered_')
        try:
            src = os.path.join(tmp, 'src.zip')
            with zipfile.ZipFile(src, 'w') as z:
                for rel in (u'startup.py', u'lib/peer_update.py', u'lib/peer_library/ext_update.py',
                            u'PEER.tab/bundle.yaml', u'PEER.tab/Walls.panel/W.pushbutton/script.py',
                            u'PEER.tab/Account.panel/Account.pushbutton/script.py'):
                    z.writestr(rel, b'x = 1\n')
            for flavor, n in (('full', 6), ('boot', 5)):
                out = os.path.join(tmp, flavor + '.zip')
                self.assertEqual(pack.build(src, out, '7', 'beta', flavor=flavor)[0], n)
                files = U.stage(out, os.path.join(tmp, 'st_' + flavor), flavor, 'dev')
                self.assertTrue(all(not k.startswith('PEER.tab/') for k in files))
                self.assertIn(u'PEER_dev.tab/Account.panel/Account.pushbutton/script.py', files)
                with self.assertRaises(U.UpdateError):
                    U.stage(out, os.path.join(tmp, 'st2_' + flavor), flavor, 'stable')
            out = os.path.join(tmp, 'stable.zip')
            pack.build(src, out, '7', 'stable')
            self.assertIn(u'PEER.tab/bundle.yaml', U.stage(out, os.path.join(tmp, 'st3'), 'full', 'stable'))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

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

    def test_two_editions_side_by_side(self):
        """PEER follows stable, PEER_dev follows beta; one never becomes the other."""
        dev = os.path.join(self.tmp, 'PEER_dev.extension')
        os.makedirs(dev)
        work_dev = os.path.join(self.tmp, 'work_dev')
        self.svc.add('1', self.V1)
        self.svc.add('2', {'startup.py': b'dev_two = 2', 'PEER_dev.tab/bundle.yaml': b'x'}, channel='beta')
        self.assertEqual(self.sync('stable')[0], 'updated')
        self.assertEqual(U.sync(dev, self.svc, 'beta', work_dev)[0], 'updated')
        self.assertEqual(self.read('startup.py'), b'one')
        with open(os.path.join(dev, 'startup.py'), 'rb') as f:
            self.assertEqual(f.read(), b'dev_two = 2')
        self.assertEqual((version.edition(self.ext), version.edition(dev)), ('stable', 'dev'))
        self.assertEqual((version.channel_of(self.ext), version.channel_of(dev)), ('stable', 'beta'))
        self.assertEqual((version.tab_name(self.ext), version.tab_name(dev)), ('PEER', 'PEER_dev'))
        self.assertEqual(version.text(dev, 'stable'), u'2 dev')
        self.assertTrue(version.is_secondary(dev))                  # PEER.extension sits beside it
        # stable moves on: PEER_dev stays on its own channel
        self.svc.add('3', {'startup.py': b'three'})
        self.assertEqual(self.sync('stable')[0], 'updated')
        self.assertEqual(U.sync(dev, self.svc, 'beta', work_dev), ('clean', '2'))
        # asking the wrong channel is refused, nothing changes
        self.assertEqual(U.sync(dev, self.svc, 'stable', work_dev)[0], 'error')
        self.assertEqual(self.sync('beta')[0], 'error')
        self.assertEqual(self.read('startup.py'), b'three')
        # a stable package put on the beta channel by mistake is refused
        self.svc.manifest['channels']['beta'] = '3'
        self.assertEqual(U.sync(dev, self.svc, 'beta', work_dev)[0], 'error')
        with open(os.path.join(dev, 'startup.py'), 'rb') as f:
            self.assertEqual(f.read(), b'dev_two = 2')

    def test_dev_edition_beside_the_everyday_one_is_secondary(self):
        root = os.path.join(self.tmp, 'Extensions')
        dev, main = os.path.join(root, 'PEER_dev.extension'), os.path.join(root, 'PEER.extension')
        os.makedirs(dev)
        self.svc.add('2', {'startup.py': b'dev = 1'}, channel='beta')
        U.sync(dev, self.svc, 'beta', self.work)
        self.assertFalse(version.is_secondary(dev))
        os.makedirs(main)
        self.assertTrue(version.is_secondary(dev))
        self.assertFalse(version.is_secondary(main))

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
        # a zip that itself holds an entry outside the folder (not only in files.json)
        self.svc.add('2', {'startup.py': b'two'}, extra={'../evil2.py': b'e'})
        self.assertEqual(self.sync()[0], 'error')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'evil2.py')))
        self.assertFalse(os.path.exists(os.path.join(self.work, 'evil2.py')))

    def test_updater_that_does_not_compile_is_not_installed(self):
        self.svc.add('1', self.V1)
        self.sync()
        broken = dict(self.V1, **{'lib/peer_update.py': b'def run(:\n', 'lib/a.py': b'a2'})
        self.svc.add('2', broken)
        status, det = self.sync()
        self.assertEqual(status, 'error')
        self.assertIn(u'does not run here', det)
        self.assertEqual(self.read('lib/a.py'), b'a1')               # nothing was written
        self.assertEqual(version.get(self.ext)['version'], u'1')

    def test_updater_files_are_written_last(self):
        self.svc.add('1', self.V1)
        self.sync()
        self.svc.add('2', {'startup.py': b'two', 'lib/peer_update.py': b'x = 2\n', 'lib/z.py': b'z',
                           'lib/peer_library/ext_update.py': b'y = 2\n'})
        order = []
        real = U._copy
        U._copy = lambda src, dst: (order.append(os.path.relpath(dst, self.ext).replace(os.sep, '/')), real(src, dst))
        try:
            self.assertEqual(self.sync()[0], 'updated')
        finally:
            U._copy = real
        files = [o for o in order if o not in U.OWN]
        self.assertEqual(files[0], 'lib/z.py')
        self.assertEqual(set(files[1:]), set(['startup.py', 'lib/peer_update.py', 'lib/peer_library/ext_update.py']))

    def test_copy_never_leaves_half_a_file(self):
        self.write('lib/a.py', b'old')
        src = os.path.join(self.tmp, 'new.py')
        with open(src, 'wb') as f:
            f.write(b'new')
        real = U.jsonio.replace

        def boom(a, b):
            raise OSError('power cut')
        U.jsonio.replace = boom
        try:
            with self.assertRaises(OSError):
                U._copy(src, os.path.join(self.ext, 'lib', 'a.py'))
        finally:
            U.jsonio.replace = real
        self.assertEqual(self.read('lib/a.py'), b'old')
        self.assertEqual(os.listdir(os.path.join(self.ext, 'lib')), ['a.py'])

    def test_loader_then_full_peer(self):
        loader = {'startup.py': b'one', 'lib/peer_update.py': b'u = 1\n'}
        full = dict(loader, **{'lib/tools.py': b'tools'})
        self.svc.add('1', full)
        p = make_zip(os.path.join(self.svc.folder, 'boot-1.zip'), '1', loader, extra=None)
        self.svc.boot = {'channels': {'stable': u'1', 'beta': u''},
                         'versions': [{'version': '1', 'sha1': rfa_info.sha1(p)}]}
        # no key: only the loader can be installed / kept current
        self.svc.key = False
        status, det = U.sync(self.ext, self.svc, 'stable', self.work, None, 'boot')
        self.assertEqual(status, 'updated', det)
        self.assertTrue(version.is_loader(self.ext))
        self.assertEqual(version.text(self.ext, 'stable'), u'1 loader')
        self.assertEqual(U.sync(self.ext, self.svc, 'stable', self.work, None, 'boot'), ('clean', '1'))
        self.assertEqual(U.sync(self.ext, self.svc, 'stable', self.work)[0], 'nokey')
        # signed in: the same version number, but the full PEER replaces the loader
        self.svc.key = True
        status, det = U.sync(self.ext, self.svc, 'stable', self.work)
        self.assertEqual(status, 'updated', det)
        self.assertFalse(version.is_loader(self.ext))
        self.assertEqual(self.read('lib/tools.py'), b'tools')
        self.assertEqual(U.sync(self.ext, self.svc, 'stable', self.work), ('clean', '1'))
        # a full installation is never turned back into a loader
        self.assertEqual(U.sync(self.ext, self.svc, 'stable', self.work, None, 'boot')[0], 'clean')
        self.assertEqual(self.read('lib/tools.py'), b'tools')

    def test_a_full_package_offered_as_loader_is_refused(self):
        self.svc.add('1', self.V1)                      # full package
        self.svc.boot = self.svc.manifest               # ... listed as the loader
        self.svc.key = False
        status, det = U.sync(self.ext, self.svc, 'stable', self.work, None, 'boot')
        self.assertEqual(status, 'error')
        self.assertEqual(os.listdir(self.ext), [])

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
