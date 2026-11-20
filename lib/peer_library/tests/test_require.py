# -*- coding: utf-8 -*-
"""require.plan without Revit:  py -3 -m unittest discover -s lib/peer_library/tests"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from peer_library import require as R  # noqa: E402


def card(fid, version=1, catalog=False):
    return {'id': fid, 'version': version, 'type_catalog': catalog}


CARDS = {'pr_edge': card(u'PR_Edge', 3), 'he': card(u'HE', 2, catalog=True)}


class TestPlan(unittest.TestCase):

    def test_present_is_never_reloaded(self):
        steps = R.plan([u'PR_Edge'], {'pr_edge': 1}, CARDS)
        self.assertEqual(steps, [(u'PR_Edge', R.PRESENT, 1)])
        self.assertEqual(R.outdated(steps, CARDS), [(u'PR_Edge', 1, 3)])

    def test_present_without_version_is_not_outdated(self):
        steps = R.plan([u'pr_edge'], {'pr_edge': None}, CARDS)
        self.assertEqual(R.outdated(steps, CARDS), [])

    def test_missing_comes_from_library_first(self):
        steps = R.plan([u'PR_EDGE'], {}, CARDS, {'pr_edge': u'x.rfa'})
        self.assertEqual(steps[0][1], R.LIBRARY)
        self.assertEqual(steps[0][2]['id'], u'PR_Edge')

    def test_folder_when_not_in_library(self):
        steps = R.plan([u'Own'], {}, CARDS, {'own': u'c:/f/Own.rfa'})
        self.assertEqual(steps, [(u'Own', R.FOLDER, u'c:/f/Own.rfa')])

    def test_missing_reasons(self):
        self.assertEqual(R.plan([u'Own'], {}, CARDS)[0], (u'Own', R.MISSING, R.WHY_NOT_IN_LIBRARY))
        self.assertEqual(R.plan([u'Own'], {}, None, library_error=u'offline')[0][2], u'offline')
        self.assertEqual(R.plan([u'Own'], {}, None)[0][2], R.WHY_NO_LIBRARY)

    def test_catalog_needs_types(self):
        self.assertEqual(R.plan([u'HE'], {}, CARDS)[0][1:], (R.MISSING, R.WHY_NEEDS_TYPES))
        self.assertEqual(R.plan([u'HE'], {}, CARDS, types={u'he': [u'HE200A']})[0][1], R.LIBRARY)
        self.assertEqual(R.plan([u'HE'], {}, CARDS, {'he': u'he.rfa'})[0][1], R.FOLDER)

    def test_duplicates_and_blanks_dropped(self):
        steps = R.plan([u'PR_Edge', u'', u'pr_edge ', None], {}, CARDS)
        self.assertEqual(len(steps), 1)

    def test_folder_files(self):
        d = tempfile.mkdtemp()
        try:
            open(os.path.join(d, u'Own.rfa'), 'w').close()
            self.assertEqual(list(R.folder_files(d, [u'Own', u'Other']).keys()), ['own'])
            self.assertEqual(R.folder_files(None, [u'Own']), {})
        finally:
            shutil.rmtree(d)

    def test_result_message(self):
        r = R.Result()
        self.assertTrue(r.ok)
        r.missing.append((u'Own', R.WHY_NOT_IN_LIBRARY))
        r.outdated.append((u'PR_Edge', 1, 3))
        self.assertFalse(r.ok)
        self.assertIn(u'Own - not in the library', r.message())
        self.assertIn(u'PR_Edge v1 -> v3', r.message())


if __name__ == '__main__':
    unittest.main()
