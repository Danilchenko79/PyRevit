# -*- coding: utf-8 -*-
"""Project template on the computer + template passport, without Revit:
    py -3 -m unittest discover -s lib/peer_library/tests"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from peer_library import passport as P  # noqa: E402
from peer_library import template_sync as T  # noqa: E402
from peer_library.backend_base import AccessError, OfflineError  # noqa: E402


class FakeService(object):

    def __init__(self):
        self.files = {}
        self.manifest = {'channels': {'stable': u'', 'beta': u''}, 'versions': []}
        self.key, self.offline, self.revoked, self.damage = True, False, False, False
        self.downloads = []

    def has_key(self):
        return self.key

    def add(self, ver, data, channel='stable', note=None):
        self.files[ver] = data
        self.manifest['versions'].append({'version': ver, 'sha1': hashlib.sha1(data).hexdigest(),
                                          'note': note or u'what changed in ' + ver, 'time': u't' + ver})
        self.manifest['channels'][channel] = ver

    def release_manifest(self, product, etag=None, quick=False):
        assert product == 'template'
        if self.revoked:
            raise AccessError(u'key not valid')
        if self.offline:
            raise OfflineError(u'no connection')
        return self.manifest, 'tag'

    def release_download(self, product, ver, target):
        if self.offline:
            raise OfflineError(u'no connection')
        self.downloads.append(ver)
        with open(target, 'wb') as f:
            f.write(self.files[ver] + (b'x' if self.damage else b''))
        return target


class TestTemplateSync(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='peertpl_')
        self.folder = os.path.join(self.tmp, 'Templates')
        self.svc = FakeService()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def data(self):
        with open(T.path(self.folder), 'rb') as f:
            return f.read()

    def test_name_is_fixed(self):
        self.assertEqual(os.path.basename(T.path(self.folder)), u'PR_Template Concrete.rte')

    def test_first_download_then_clean(self):
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'none')
        self.svc.add('1', b'rte-1')
        status, det, notes = T.sync(self.svc, 'stable', self.folder)
        self.assertEqual((status, det), ('updated', u'- -> 1'))
        self.assertEqual(notes, [('1', u'what changed in 1')])
        self.assertEqual(self.data(), b'rte-1')
        self.assertEqual(T.installed(self.folder)['version'], '1')
        self.assertEqual(T.sync(self.svc, 'stable', self.folder), ('clean', '1', []))
        self.assertEqual(self.svc.downloads, ['1'])

    def test_update_tells_what_is_new(self):
        self.svc.add('1', b'rte-1')
        T.sync(self.svc, 'stable', self.folder)
        self.svc.add('2', b'rte-2')
        self.svc.add('3', b'rte-3')
        status, det, notes = T.sync(self.svc, 'stable', self.folder)
        self.assertEqual((status, det), ('updated', u'1 -> 3'))
        self.assertEqual([n[0] for n in notes], ['3', '2'])
        self.assertEqual(self.data(), b'rte-3')

    def test_beta_and_roll_back(self):
        self.svc.add('1', b'rte-1')
        self.svc.add('2', b'rte-2', channel='beta')
        T.sync(self.svc, 'stable', self.folder)
        self.assertEqual(self.data(), b'rte-1')
        T.sync(self.svc, 'beta', self.folder)
        self.assertEqual(self.data(), b'rte-2')
        self.svc.manifest['channels']['beta'] = ''                # beta withdrawn
        self.assertEqual(T.sync(self.svc, 'beta', self.folder)[0], 'updated')
        self.assertEqual(self.data(), b'rte-1')

    def test_edited_or_deleted_file_comes_back(self):
        self.svc.add('1', b'rte-1')
        T.sync(self.svc, 'stable', self.folder)
        with open(T.path(self.folder), 'wb') as f:
            f.write(b'saved over by a person')
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'updated')
        self.assertEqual(self.data(), b'rte-1')
        os.remove(T.path(self.folder))
        self.assertEqual(T.installed(self.folder), {})
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'updated')

    def test_file_in_use_waits_for_the_next_start(self):
        self.svc.add('1', b'rte-1')
        T.sync(self.svc, 'stable', self.folder)
        self.svc.add('2', b'rte-2')
        real = T._replace
        T._replace = lambda new, target: False                    # Revit holds the file
        try:
            status, det, notes = T.sync(self.svc, 'stable', self.folder)
        finally:
            T._replace = real
        self.assertEqual(status, 'waiting')
        self.assertEqual(self.data(), b'rte-1')
        self.assertEqual(T.installed(self.folder)['version'], '1')
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'updated')
        self.assertEqual(self.data(), b'rte-2')
        self.assertEqual(self.svc.downloads, ['1', '2'])           # the waiting file is reused
        self.assertFalse(os.path.exists(T.path(self.folder) + u'.new'))

    def test_damaged_offline_nokey_change_nothing(self):
        self.svc.add('1', b'rte-1')
        T.sync(self.svc, 'stable', self.folder)
        self.svc.add('2', b'rte-2')
        self.svc.damage = True
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'error')
        self.svc.damage, self.svc.offline = False, True
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'offline')
        self.svc.offline, self.svc.revoked = False, True
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'nokey')
        self.svc.revoked, self.svc.key = False, False
        self.assertEqual(T.sync(self.svc, 'stable', self.folder)[0], 'nokey')
        self.assertEqual(self.data(), b'rte-1')                    # the template still works


class TestPassport(unittest.TestCase):
    OLD = {
        'view_templates': {'PEER GR': {'scale': 50, 'detail': 'Fine', 'filters': ['Bx', 'By']},
                           'PEER RE': {'scale': 50}},
        'filters': {'Bx': {'rules': 'PR_Set_HE != B', 'categories': ['Rebar']}},
        'families': {'PR_Tag Rebar': {'category': 'Tags', 'version': 2}, 'Own Tag': {'version': None}},
    }

    def test_no_difference(self):
        self.assertEqual(P.diff(self.OLD, self.OLD), [])
        self.assertEqual(P.text([]), u'No differences.')
        self.assertEqual(P.summary([]), u'no differences')

    def test_added_removed_changed(self):
        new = {
            'view_templates': {'PEER GR': {'scale': 75, 'detail': 'Fine', 'filters': ['By', 'Bx', 'Tx']},
                               'PEER Formwork': {'scale': 50}},
            'filters': {'Bx': {'rules': 'PR_Set_HE != Bx', 'categories': ['Rebar']}},
            'families': {'PR_Tag Rebar': {'category': 'Tags', 'version': 3}, 'Own Tag': {'version': None}},
            'my_section': {'x': {'a': True}},
        }
        ch = P.diff(self.OLD, new)
        self.assertEqual([(c[0], c[1], c[2]) for c in ch], [
            ('view_templates', 'added', 'PEER Formwork'),
            ('view_templates', 'changed', 'PEER GR'),
            ('view_templates', 'removed', 'PEER RE'),
            ('filters', 'changed', 'Bx'),
            ('families', 'changed', 'PR_Tag Rebar'),
            ('my_section', 'added', 'x')])
        gr = [c for c in ch if c[2] == 'PEER GR'][0][3]
        self.assertEqual(gr, [u'filters: added Tx', u'scale: 50 -> 75'])     # order of a list is not a change
        self.assertEqual(P.summary(ch), u'2 added, 1 removed, 3 changed')
        t = P.text(ch)
        self.assertIn(u'**View templates**', t)
        self.assertIn(u'~ PEER GR: filters: added Tx; scale: 50 -> 75', t)
        self.assertIn(u'- PEER RE', t)
        self.assertIn(u'**My section**', t)
        self.assertIn(u'... and 4 more', P.text(ch, limit=2))

    def test_empty_and_odd_input(self):
        self.assertEqual(P.diff(None, None), [])
        self.assertEqual(P.diff({}, {'filters': {'A': {}}})[0][:3], ('filters', 'added', 'A'))
        self.assertEqual(P.diff({'filters': {'A': 1}}, {'filters': {'A': 2}})[0][3], [u'1 -> 2'])
        self.assertEqual(P.diff({'filters': 'broken'}, {'filters': {}}), [])

    def test_template_families_against_the_library(self):
        cards = {'pr_tag rebar': {'id': 'PR_Tag Rebar', 'version': 3}, 'own tag': {'id': 'Own Tag', 'version': 1}}
        self.assertEqual(P.outdated_families(self.OLD, cards),
                         [('Own Tag', None, 1), ('PR_Tag Rebar', 2, 3)])
        cards['pr_tag rebar']['version'] = 2
        cards.pop('own tag')
        self.assertEqual(P.outdated_families(self.OLD, cards), [])


if __name__ == '__main__':
    unittest.main()
