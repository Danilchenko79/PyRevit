# -*- coding: utf-8 -*-
"""One key for the whole PEER tab, without Revit:
    py -3 -m unittest discover -s lib/peer_library/tests"""

import datetime
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from peer_library import access as A  # noqa: E402
from peer_library import strings, version  # noqa: E402

NOW = datetime.datetime(2026, 11, 20, 12, 0, 0)


def cfg(lock=True, last=u'2026-11-19T12:00:00', url=u'https://peer.example.workers.dev', backend=u'http'):
    return {'backend': backend, 'url': url, 'access_lock': lock, 'last_ok': last,
            'user': u'Anna', 'role': u'user'}


class TestEvaluate(unittest.TestCase):

    def test_no_service_never_locks(self):
        for c in (cfg(url=u''), cfg(backend=u'local'), cfg(url=u'http://plain.example')):
            st = A.evaluate(c, False, now=NOW)
            self.assertEqual(st.code, A.OFF)
            self.assertFalse(st.locked)

    def test_fresh_key(self):
        st = A.evaluate(cfg(), True, now=NOW)
        self.assertEqual((st.code, st.locked, st.signed_in, st.name), (A.OK, False, True, u'Anna'))
        self.assertEqual(st.days_left, 13)

    def test_offline_window_is_14_days(self):
        ok = A.evaluate(cfg(last=u'2026-11-06T12:00:01'), True, now=NOW)
        self.assertEqual((ok.code, ok.locked), (A.OK, False))
        old = A.evaluate(cfg(last=u'2026-11-06T12:00:00'), True, now=NOW)
        self.assertEqual((old.code, old.locked, old.days_left), (A.STALE, True, 0))

    def test_key_never_checked_is_stale(self):
        st = A.evaluate(cfg(last=u''), True, now=NOW)
        self.assertEqual((st.code, st.locked), (A.STALE, True))

    def test_no_key(self):
        self.assertEqual(A.evaluate(cfg(), False, now=NOW).code, A.NONE)
        self.assertEqual(A.evaluate(cfg(), False, True, now=NOW).code, A.REQUESTED)
        self.assertTrue(A.evaluate(cfg(), False, now=NOW).locked)

    def test_future_check_is_not_trusted(self):
        st = A.evaluate(cfg(last=u'2027-01-01T00:00:00'), True, now=NOW)
        self.assertEqual((st.code, st.locked), (A.STALE, True))

    def test_lock_off_never_locks(self):
        for has_key, last in ((False, u''), (True, u''), (True, u'2020-01-01T00:00:00')):
            self.assertFalse(A.evaluate(cfg(lock=False, last=last), has_key, now=NOW).locked)


class TestSettingsFiles(unittest.TestCase):

    def setUp(self):
        from peer_library import config
        self.config = config
        self.tmp = tempfile.mkdtemp(prefix='peercfg_')
        self.old = (config.REPO_FILE, os.environ.get('APPDATA'))
        config.REPO_FILE = os.path.join(self.tmp, 'settings.json')
        os.environ['APPDATA'] = os.path.join(self.tmp, 'appdata')

    def tearDown(self):
        self.config.REPO_FILE = self.old[0]
        if self.old[1] is None:
            os.environ.pop('APPDATA', None)
        else:
            os.environ['APPDATA'] = self.old[1]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, path, text):
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    def test_only_the_office_file_sets_the_lock(self):
        self.write(self.config.REPO_FILE, u'{"access_lock": true}')
        self.write(self.config.local_file(), u'{"access_lock": false, "url": "https://x.example"}')
        cfg = self.config.load()
        self.assertTrue(cfg['access_lock'])
        self.assertEqual(cfg['url'], u'https://x.example')

    def test_unreadable_file_is_not_overwritten(self):
        self.write(self.config.local_file(), u'{"url": "https://x.example", broken')
        with self.assertRaises(IOError):
            self.config.save_local(last_ok=u'2026-11-20T10:00:00')
        with io.open(self.config.local_file(), encoding='utf-8') as f:
            self.assertIn(u'broken', f.read())

    def test_parallel_writers_keep_every_key(self):
        import threading
        self.config.save_local(url=u'https://x.example')
        errors = []

        def work(i):
            try:
                for _ in range(15):
                    self.config.save_local(**{('last_ok' if i % 2 else 'notify_checked'): u'2026-11-20T10:00:0%d' % (i % 10)})
            except Exception as ex:
                errors.append(ex)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        cfg = self.config.load()
        self.assertEqual(cfg['url'], u'https://x.example')
        self.assertTrue(cfg['last_ok'] and cfg['notify_checked'])
        self.assertEqual([f for f in os.listdir(os.path.dirname(self.config.local_file())) if f.endswith('.tmp')], [])


class TestWorkingCopyIsNeverLocked(unittest.TestCase):

    def test_lock_only_for_an_installed_package(self):
        from peer_library import config, keystore
        real = (config.load, keystore.load, keystore.load_request, version.get)
        config.load = lambda: cfg(lock=True, last=u'')
        keystore.load = lambda: None
        keystore.load_request = lambda: None
        try:
            version.get = lambda folder=None: {'kind': 'git', 'version': u'git abc', 'flavor': u'full', 'edition': u'stable', 'channel': u''}
            st = A.status()
            self.assertEqual((st.code, st.locked), (A.NONE, False))      # the author's clone: tools stay
            version.get = lambda folder=None: {'kind': 'package', 'version': u'1', 'flavor': u'full', 'edition': u'stable', 'channel': u'stable'}
            st = A.status()
            self.assertEqual((st.code, st.locked), (A.NONE, True))       # installed from the service: locked
        finally:
            config.load, keystore.load, keystore.load_request, version.get = real


class TestRibbonPlan(unittest.TestCase):
    NAMES = ['Sheets', 'Reinforcement', 'Library', 'Feedback', 'Account']

    def test_unlocked(self):
        plan = A.panel_plan(self.NAMES, False, True)
        self.assertEqual(plan, {'Sheets': True, 'Reinforcement': True, 'Library': True, 'Account': True})

    def test_locked_keeps_account_and_feedback(self):
        plan = A.panel_plan(self.NAMES, True, True)
        self.assertEqual(plan, {'Sheets': False, 'Reinforcement': False, 'Library': False, 'Account': True})
        self.assertNotIn('Feedback', plan)          # never touched

    def test_library_waits_for_families(self):
        plan = A.panel_plan(self.NAMES, False, True, False)
        self.assertEqual(plan, {'Sheets': True, 'Reinforcement': True, 'Library': False, 'Account': True})

    def test_no_service_hides_library_and_account_only(self):
        plan = A.panel_plan(self.NAMES, False, False)
        self.assertEqual(plan, {'Sheets': True, 'Reinforcement': True, 'Library': False, 'Account': False})


class TestLibraryReady(unittest.TestCase):

    def test_admin_always_users_when_there_are_families(self):
        tmp = tempfile.mkdtemp(prefix='peerready_')
        try:
            c = {'backend': 'http', 'role': 'user', 'cache': tmp}
            self.assertFalse(A.library_ready(c))
            self.assertTrue(A.library_ready(dict(c, role='admin')))
            with io.open(os.path.join(tmp, 'index.json'), 'w', encoding='utf-8') as f:
                f.write(u'{"families": []}')
            self.assertFalse(A.library_ready(c))
            with io.open(os.path.join(tmp, 'index.json'), 'w', encoding='utf-8') as f:
                f.write(u'{"families": [{"id": "X"}]}')
            self.assertTrue(A.library_ready(c))
            self.assertTrue(A.library_ready({'backend': 'local', 'role': 'user', 'cache': tmp}))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDescribe(unittest.TestCase):

    def test_texts(self):
        S = A.Status
        self.assertEqual(A.describe(S(A.OK, True, 9), 'ok'), strings.ACC_OK)
        self.assertIn(u'9 more day', A.describe(S(A.OK, True, 9), 'offline'))
        self.assertEqual(A.describe(S(A.NONE, True)), strings.ACC_NONE_LOCKED)
        self.assertEqual(A.describe(S(A.NONE, False)), strings.ACC_NONE)
        self.assertEqual(A.describe(S(A.NONE, True), 'revoked'), strings.ACC_REVOKED)
        self.assertEqual(A.describe(S(A.STALE, True)), strings.ACC_STALE_LOCKED)
        self.assertEqual(A.describe(S(A.REQUESTED, True)), strings.ACC_REQUESTED)
        self.assertEqual(A.describe(S(A.OFF, False)), strings.ACC_OFF)


class TestVersion(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='peerver_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_package(self):
        with io.open(os.path.join(self.tmp, 'version.json'), 'w', encoding='utf-8') as f:
            f.write(u'{"version": "2026.11.20.1", "channel": "beta", "built": "2026-11-20T10:00:00"}')
        v = version.get(self.tmp)
        self.assertEqual((v['version'], v['channel'], v['kind']), (u'2026.11.20.1', u'beta', 'package'))
        self.assertEqual(version.text(self.tmp, 'beta'), u'2026.11.20.1 (beta)')
        self.assertEqual(version.text(self.tmp, 'stable'), u'2026.11.20.1')

    def test_git_clone(self):
        os.makedirs(os.path.join(self.tmp, '.git', 'refs', 'heads'))
        with io.open(os.path.join(self.tmp, '.git', 'HEAD'), 'w', encoding='utf-8') as f:
            f.write(u'ref: refs/heads/main\n')
        with io.open(os.path.join(self.tmp, '.git', 'refs', 'heads', 'main'), 'w', encoding='utf-8') as f:
            f.write(u'0123456789abcdef0123456789abcdef01234567\n')
        self.assertEqual(version.text(self.tmp, 'beta'), u'git 0123456')
        self.assertEqual(version.get(self.tmp)['kind'], 'git')

    def test_nothing(self):
        self.assertEqual(version.get(self.tmp)['version'], u'dev')

    def test_button_folder_is_found_wherever_it_sits(self):
        tab = os.path.join(self.tmp, 'PEER.tab')
        os.makedirs(os.path.join(tab, 'Library.panel', 'LibraryMain.stack', 'Library.smartbutton'))
        os.makedirs(os.path.join(tab, 'Walls.panel', 'WallRebar2D.pushbutton'))
        self.assertTrue(version.bundle_dir('Library.smartbutton', self.tmp).endswith(
            os.path.join('LibraryMain.stack', 'Library.smartbutton')))
        self.assertTrue(version.bundle_dir('WallRebar2D.pushbutton', self.tmp).endswith(
            os.path.join('Walls.panel', 'WallRebar2D.pushbutton')))
        self.assertEqual(version.bundle_dir('Nope.pushbutton', self.tmp), os.path.join(tab, 'Nope.pushbutton'))

    def test_real_windows_are_where_the_code_looks(self):
        for name, xaml in (('Library.smartbutton', 'LoginWindow.xaml'), ('Library.smartbutton', 'LibraryWindow.xaml'),
                           ('Library.smartbutton', 'EditInfoWindow.xaml'), ('Account.pushbutton', 'AccountWindow.xaml'),
                           ('Publish.smartbutton', 'PublishWindow.xaml'), ('Propose.smartbutton', 'ProposeWindow.xaml'),
                           ('Keys.smartbutton', 'KeysWindow.xaml'), ('Contact.pushbutton', 'ContactForm.xaml'),
                           ('Contact.pushbutton', 'MyRequestsForm.xaml'), ('About.pushbutton', 'AboutWindow.xaml')):
            self.assertTrue(os.path.isfile(os.path.join(version.bundle_dir(name), xaml)), name + '/' + xaml)

    def test_ribbon_layout_lists_what_exists(self):
        """Every name in the bundle.yaml layouts of the two left panels is a real folder;
        stacks hold 2-3 buttons; the rarely used things sit in the slide-out."""
        tab = version.tab_dir()

        def layout(path):
            with io.open(path, encoding='utf-8') as f:
                # '- "Account[beforeall:]"' -> 'Account' (the part in brackets tells pyRevit where to
                # move a panel that already exists in the running Revit)
                return [l.strip()[2:].strip('"').split('[')[0] for l in f if l.strip().startswith('- ')]

        order = layout(os.path.join(tab, 'bundle.yaml'))
        self.assertEqual(order[:2], ['Account', 'Library'])
        for panel in order:
            self.assertTrue(os.path.isdir(os.path.join(tab, panel + '.panel')), panel)
        for panel, first, hidden in (('Account', 'AccountTools', 'About'), ('Library', 'LibraryMain', 'LibraryAdmin')):
            base = os.path.join(tab, panel + '.panel')
            items = layout(os.path.join(base, 'bundle.yaml'))
            self.assertEqual(items[0], first)
            self.assertEqual(items[1], '>>>>>')                      # the slide-out starts here
            self.assertIn(hidden, items[2:])
            on_disk = sorted(d.split('.')[0] for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
            self.assertEqual(sorted(i for i in items if i != '>>>>>'), on_disk, panel)
            for st in [d for d in os.listdir(base) if d.endswith('.stack')]:
                sdir = os.path.join(base, st)
                inside = layout(os.path.join(sdir, 'bundle.yaml'))
                self.assertTrue(2 <= len(inside) <= 3, st)           # Revit stacks hold 2 or 3 buttons
                have = sorted(d.split('.')[0] for d in os.listdir(sdir) if os.path.isdir(os.path.join(sdir, d)))
                # Info: the Wiki button under its previous folder name, kept for one release and left
                # out of the layout (pyRevit does not create what a layout does not list)
                self.assertEqual(sorted(inside), [h for h in have if h != 'Info'], st)

    def test_version_is_a_safe_header(self):
        import re
        self.assertTrue(re.match(r'^[A-Za-z0-9 ._()-]{1,40}$', version.text()))


if __name__ == '__main__':
    unittest.main()
