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

    def test_lock_off_never_locks(self):
        for has_key, last in ((False, u''), (True, u''), (True, u'2020-01-01T00:00:00')):
            self.assertFalse(A.evaluate(cfg(lock=False, last=last), has_key, now=NOW).locked)


class TestRibbonPlan(unittest.TestCase):
    NAMES = ['Sheets', 'Reinforcement', 'Library', 'Feedback', 'Account']

    def test_unlocked(self):
        plan = A.panel_plan(self.NAMES, False, True)
        self.assertEqual(plan, {'Sheets': True, 'Reinforcement': True, 'Library': True, 'Account': True})

    def test_locked_keeps_account_and_feedback(self):
        plan = A.panel_plan(self.NAMES, True, True)
        self.assertEqual(plan, {'Sheets': False, 'Reinforcement': False, 'Library': False, 'Account': True})
        self.assertNotIn('Feedback', plan)          # never touched

    def test_no_service_hides_library_and_account_only(self):
        plan = A.panel_plan(self.NAMES, False, False)
        self.assertEqual(plan, {'Sheets': True, 'Reinforcement': True, 'Library': False, 'Account': False})


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
        self.assertEqual(version.text(self.tmp), u'2026.11.20.1 (beta)')

    def test_git_clone(self):
        os.makedirs(os.path.join(self.tmp, '.git', 'refs', 'heads'))
        with io.open(os.path.join(self.tmp, '.git', 'HEAD'), 'w', encoding='utf-8') as f:
            f.write(u'ref: refs/heads/main\n')
        with io.open(os.path.join(self.tmp, '.git', 'refs', 'heads', 'main'), 'w', encoding='utf-8') as f:
            f.write(u'0123456789abcdef0123456789abcdef01234567\n')
        self.assertEqual(version.text(self.tmp), u'git 0123456')
        self.assertEqual(version.get(self.tmp)['kind'], 'git')

    def test_nothing(self):
        self.assertEqual(version.get(self.tmp)['version'], u'dev')

    def test_version_is_a_safe_header(self):
        import re
        self.assertTrue(re.match(r'^[A-Za-z0-9 ._()-]{1,40}$', version.text()))


if __name__ == '__main__':
    unittest.main()
