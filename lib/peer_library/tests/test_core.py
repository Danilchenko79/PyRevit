# -*- coding: utf-8 -*-
"""Library core without Revit:  py -3 -m unittest discover -s lib/peer_library/tests"""

import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from peer_library import cache, checks_file, index, jsonio, rfa_info  # noqa: E402
from peer_library.backend_base import AccessError, ConflictError, OfflineError  # noqa: E402
from peer_library.backend_local import LocalBackend  # noqa: E402


def fake_rfa(path, year=2024, payload=b'x'):
    """Bytes the version reader understands: UTF-16 'Format: <year>'."""
    data = b'\xd0\xcf\x11\xe0' + (u'Format: {0}'.format(year)).encode('utf-16-le') + payload
    with open(path, 'wb') as f:
        f.write(data)
    return path


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='peerlib_')
        self.root = os.path.join(self.tmp, 'share')
        os.makedirs(self.root)
        self.src = os.path.join(self.tmp, 'src')
        os.makedirs(self.src)
        self.admin = LocalBackend(self.root, role='admin', user=u'dima')
        self.user = LocalBackend(self.root, role='user', user=u'anna')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rfa(self, name='PEER_Beam_Rect', payload=b'x', year=2024):
        return fake_rfa(os.path.join(self.src, name + '.rfa'), year, payload)

    def publish(self, fid='PEER_Beam_Rect', payload=b'x', note=u'', **extra):
        rfa = self.rfa(fid, payload)
        png = os.path.join(self.src, fid + '.png')
        with open(png, 'wb') as f:
            f.write(b'png' + payload)
        card = index.new_card(id=fid, name=u'Балка прямоугольная', group='01_Framing',
                              tags=[u'балка'], version=self.admin.next_version(fid))
        card.update(extra)
        return self.admin.publish(card, rfa, png, note=note)


class TestPublish(Base):

    def test_publish_into_empty_folder(self):
        card = self.publish()
        self.assertEqual(card['version'], 1)
        lib = os.path.join(self.root, 'PEER-Library')
        for ext in ('.rfa', '.json', '.png'):
            self.assertTrue(os.path.isfile(os.path.join(lib, '01_Framing', 'PEER_Beam_Rect' + ext)))
        idx = jsonio.read(os.path.join(lib, 'index.json'))
        self.assertEqual(idx['count'], 1)
        self.assertEqual(idx['families'][0]['name'], u'Балка прямоугольная')
        self.assertEqual(idx['families'][0]['sha1'],
                         rfa_info.sha1(os.path.join(lib, '01_Framing', 'PEER_Beam_Rect.rfa')))
        log = jsonio.read(os.path.join(lib, 'changelog.json'))
        self.assertEqual(log['entries'][-1]['action'], 'added')

    def test_republish_bumps_version_and_history(self):
        self.publish()
        card = self.publish(payload=b'y', note=u'Добавлен вут')
        self.assertEqual(card['version'], 2)
        self.assertEqual([h['v'] for h in card['history']], [1, 2])
        self.assertEqual(card['history'][-1]['note'], u'Добавлен вут')
        self.assertEqual(self.admin.next_version('PEER_Beam_Rect'), 3)
        self.assertEqual(jsonio.read(os.path.join(self.root, 'PEER-Library', 'changelog.json'))
                         ['entries'][-1]['action'], 'updated')

    def test_stale_version_is_rejected(self):
        self.publish()
        rfa = self.rfa()
        card = index.new_card(id='PEER_Beam_Rect', group='01_Framing', version=1)
        with self.assertRaises(ConflictError):
            self.admin.publish(card, rfa)

    def test_user_cannot_publish(self):
        rfa = self.rfa()
        card = index.new_card(id='PEER_Beam_Rect', group='01_Framing', version=1)
        with self.assertRaises(AccessError):
            self.user.publish(card, rfa)

    def test_group_change_moves_files(self):
        self.publish()
        self.publish(payload=b'z', group='05_Details')
        lib = os.path.join(self.root, 'PEER-Library')
        self.assertFalse(os.path.exists(os.path.join(lib, '01_Framing', 'PEER_Beam_Rect.rfa')))
        self.assertTrue(os.path.exists(os.path.join(lib, '05_Details', 'PEER_Beam_Rect.rfa')))
        self.assertEqual(self.admin.get_index()['count'], 1)

    def test_failure_keeps_old_state(self):
        self.publish()
        lib = os.path.join(self.root, 'PEER-Library')
        before = rfa_info.sha1(os.path.join(lib, '01_Framing', 'PEER_Beam_Rect.rfa'))
        real = index.build_index
        calls = []

        def broken(root):
            calls.append(1)
            if len(calls) == 1:
                raise IOError('disk full')
            return real(root)
        index.build_index = broken
        try:
            with self.assertRaises(IOError):
                self.publish(payload=b'new')
        finally:
            index.build_index = real
        card = jsonio.read(os.path.join(lib, '01_Framing', 'PEER_Beam_Rect.json'))
        self.assertEqual(card['version'], 1)
        self.assertEqual(rfa_info.sha1(os.path.join(lib, '01_Framing', 'PEER_Beam_Rect.rfa')), before)
        self.assertFalse(os.path.exists(os.path.join(lib, '.lock')))

    def test_index_rebuilt_after_delete(self):
        self.publish()
        self.publish('PEER_Pile_Round', group='02_Foundations')
        os.remove(os.path.join(self.root, 'PEER-Library', 'index.json'))
        idx = self.user.get_index()
        self.assertEqual(sorted(c['id'] for c in idx['families']),
                         ['PEER_Beam_Rect', 'PEER_Pile_Round'])

    def test_deprecate_moves_to_archive(self):
        self.publish()
        self.admin.deprecate('PEER_Beam_Rect', u'replaced')
        lib = os.path.join(self.root, 'PEER-Library')
        self.assertTrue(os.path.exists(os.path.join(lib, '_Archive', 'PEER_Beam_Rect.rfa')))
        self.assertEqual(self.user.get_index()['families'][0]['status'], 'deprecated')


class TestInfoLocal(Base):

    def test_update_card_moves_group_and_keeps_version(self):
        self.publish()
        c = self.admin.update_card('PEER_Beam_Rect', {'group': '05_Details', 'tags': [u'x']})
        self.assertEqual((c['group'], c['version'], c['tags']), ('05_Details', 1, [u'x']))
        lib = os.path.join(self.root, 'PEER-Library')
        self.assertTrue(os.path.exists(os.path.join(lib, '05_Details', 'PEER_Beam_Rect.rfa')))
        with self.assertRaises(AccessError):
            self.user.update_card('PEER_Beam_Rect', {'name': u'y'})

    def test_collections_and_request(self):
        self.admin.put_collections([{'name': u'Старт', 'families': ['A']}, {'name': u''}])
        self.assertEqual(len(self.user.get_collections()['collections']), 1)
        pid = self.user.send_proposal({'kind': 'issue', 'name': u'x', 'family_id': 'A'})
        self.assertIsNone(self.admin.download_proposal(pid, os.path.join(self.tmp, 'w')))
        self.admin.resolve_proposal(pid, 'accepted', u'fixed')
        self.assertEqual(self.user.my_proposals()[0]['status'], 'accepted')


class TestCache(Base):

    def test_download_and_corrupted_copy(self):
        card = self.publish()
        c = cache.Cache(os.path.join(self.tmp, 'cache'), self.user)
        idx, online = c.index()
        self.assertTrue(online)
        path = c.get(idx['families'][0])
        self.assertEqual(rfa_info.sha1(path), card['sha1'])
        with open(path, 'ab') as f:              # someone edits the cached file
            f.write(b'garbage')
        path2 = c.get(idx['families'][0])
        self.assertEqual(rfa_info.sha1(path2), card['sha1'])

    def test_offline_uses_cache(self):
        card = self.publish()
        c = cache.Cache(os.path.join(self.tmp, 'cache'), self.user)
        idx, _ = c.index()
        c.get(card)
        self.user.root = os.path.join(self.tmp, 'gone')          # share unreachable
        self.user.lib = os.path.join(self.user.root, 'PEER-Library')
        idx2, online = c.index()
        self.assertFalse(online)
        self.assertEqual(idx2['count'], 1)
        self.assertTrue(os.path.isfile(c.get(card)))
        other = dict(card, id='PEER_Never_Downloaded', sha1='0' * 40)
        with self.assertRaises(OfflineError):
            c.get(other)


class TestProposals(Base):

    def test_round_trip(self):
        rfa = self.rfa('My beam')
        pid = self.user.send_proposal({'name': u'Балка с вутом', 'group': '01_Framing',
                                       'kind': 'new', 'reason': u'нужна'}, rfa)
        self.assertEqual(self.user.my_proposals()[0]['status'], 'pending')
        with self.assertRaises(AccessError):
            self.user.list_proposals()
        self.assertEqual([p['id'] for p in self.admin.list_proposals()], [pid])
        work = os.path.join(self.tmp, 'work')
        path = self.admin.download_proposal(pid, work)
        self.assertTrue(os.path.isfile(path))
        with self.assertRaises(Exception):
            self.admin.resolve_proposal(pid, 'rejected', u'')
        card = index.new_card(id='PEER_Beam_Haunch', group='01_Framing', version=1)
        self.admin.publish(card, path, proposal_id=pid)
        mine = self.user.my_proposals()
        self.assertEqual(mine[0]['status'], 'accepted')
        self.assertTrue(mine[0]['done'])
        self.assertEqual(self.admin.list_proposals(), [])

    def test_user_sees_only_own(self):
        rfa = self.rfa('x')
        self.user.send_proposal({'name': u'a'}, rfa)
        other = LocalBackend(self.root, role='user', user=u'boris')
        self.assertEqual(other.my_proposals(), [])


class TestChecks(unittest.TestCase):

    def test_names(self):
        self.assertEqual(checks_file.check_name(u'PEER_Beam-L (v2)'), [])
        self.assertTrue(checks_file.check_name(u'תג קורות'))
        self.assertTrue(checks_file.check_name(u'Beam.'))
        self.assertTrue(checks_file.check_name(u'Beam '))
        self.assertTrue(checks_file.check_name(u'a/b'))

    def test_revit_version(self):
        tmp = tempfile.mkdtemp()
        try:
            new = fake_rfa(os.path.join(tmp, 'PEER_New.rfa'), 2025)
            res, year = checks_file.check_file(new)
            self.assertEqual(year, 2025)
            self.assertIn('revit_new', [r[1] for r in checks_file.errors(res)])
            ok = fake_rfa(os.path.join(tmp, 'PEER_Ok.rfa'), 2023)
            res, year = checks_file.check_file(ok)
            self.assertEqual(checks_file.errors(res), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_type_catalog(self):
        from peer_library import catalog
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, 'c.txt')
            text = u',Width##LENGTH##MILLIMETERS\r\n"HEA 100",100\r\nHEA 120,120\r\n"A ""B""",1\r\n'
            with open(p, 'wb') as f:
                f.write(b'\xff\xfe' + text.encode('utf-16-le'))
            self.assertEqual(catalog.type_names(p), [u'HEA 100', u'HEA 120', u'A "B"'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_is_new(self):
        import datetime
        d = datetime.date(2026, 11, 19)
        self.assertTrue(index.is_new({'updated': '2026-11-10'}, d))
        self.assertFalse(index.is_new({'updated': '2026-10-01'}, d))

    def test_notify_text(self):
        from peer_library import notify
        log = {'entries': [
            {'time': '2026-11-01T10:00:00', 'action': 'added', 'by': 'anna'},
            {'time': '2026-11-20T10:00:00', 'action': 'added', 'by': 'anna'},
            {'time': '2026-11-20T11:00:00', 'action': 'updated', 'by': 'anna'},
            {'time': '2026-11-20T12:00:00', 'action': 'added', 'by': 'dima'}]}
        self.assertEqual(notify.news_text(log, '2026-11-10T00:00:00', 'dima'),
                         u'1 new, 1 updated families')
        self.assertEqual(notify.news_text(log, '2026-11-20T12:00:00'), u'')
        log['entries'][2]['id'] = 'PEER_A'
        self.assertIn(u'that you use: PEER_A',
                      notify.news_text(log, '2026-11-10T00:00:00', 'dima', ['PEER_A']))
        self.assertEqual(notify.latest_time(log), '2026-11-20T12:00:00')

    def test_import_names_and_tags(self):
        from peer_library import importmeta as m
        self.assertEqual(m.display_name('PEER-Concrete-Column-Rectangular'), u'Concrete Column Rectangular')
        self.assertEqual(m.info_for('EU_HE - Wide-Flange', u'STEEL\\01 Framing\\Generic\\x.rfa'),
                         {'name': u'HE - Wide-Flange', 'tags': [u'EU', u'Generic']})
        self.assertEqual(m.info_for('21E', u'04 Rebar\\3D Rebar\\Shapes\\21E.rfa')['name'],
                         u'Rebar shape 21E')
        self.assertEqual(m.folder_tags(u'01 Annotation\\TAGS\\BEAMS\\x.rfa'), [u'Tags', u'Beams'])

    def test_cards_csv_round_trip(self):
        from peer_library import cards_csv
        tmp = tempfile.mkdtemp()
        try:
            cards = [index.new_card(id='PEER_A', name=u'Балка, "T"', group='01_Framing',
                                    tags=[u'балка', u'T'], description=u'line1\nline2', version=2),
                     index.new_card(id='PEER_B', name=u'B', group='05_Details', version=1)]
            p = os.path.join(tmp, 'cards.csv')
            self.assertEqual(cards_csv.export(cards, p), 2)
            ch, probs = cards_csv.changes(cards, p)
            self.assertEqual(ch, [{'id': 'PEER_A', 'fields': {'description': u'line1 / line2'}}])
            with io.open(p, 'r', encoding='utf-8-sig') as f:
                text = f.read()
            text = text.replace(u'05_Details', u'09_Openings').replace(u'balka', u'x')
            text = text.replace(u'PEER_B,B,', u'PEER_B,Беam,') + u'PEER_X,x,01_Framing,,,,,1\r\n'
            with io.open(p, 'w', encoding='utf-8-sig') as f:
                f.write(text)
            ch, probs = cards_csv.changes(cards, p)
            got = dict((c['id'], c['fields']) for c in ch)
            self.assertEqual(got['PEER_B'], {'name': u'Беam', 'group': '09_Openings'})
            self.assertEqual(probs, [u'PEER_X: not in the library'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_attention(self):
        c = index.new_card(id='PEER_A', group='01_Framing', version=1, png_sha1='x',
                           description=u'd', tags=[u't'])
        self.assertEqual(index.attention(c), [])
        c['checks'] = [{'code': 'version', 'text': u'...'}]
        c['tags'] = []
        self.assertEqual(index.attention(c), [u'no tags', u'PEER_Version not written'])

    def test_card_validation(self):
        self.assertEqual(index.validate(index.new_card(id='PEER_A', group='01_Framing',
                                                       version=1)), [])
        self.assertTrue(index.validate(index.new_card(id='PEER_A', group='nope', version=0)))


class TestSearch(unittest.TestCase):

    def setUp(self):
        from peer_library import search
        self.s = search
        cards = [
            {'id': 'EU_HE - Column', 'name': u'Steel column HE', 'tags': [u'steel'],
             'types': [u'HE200A', u'HE300B'], 'revit_category': u'Structural Columns'},
            {'id': 'PEER-Concrete-Column-Rectangular', 'name': u'Concrete column, rectangular',
             'tags': [u'concrete'], 'revit_category': u'Structural Columns'},
            {'id': 'PR_Pile', 'name': u'Bored pile', 'tags': [u'foundation'],
             'description': u'Use for the column foundations'},
            {'id': 'PR_Tag beams', 'name': u'Beam tag', 'tags': []},
        ]
        self.entries = [search.Entry(c) for c in cards]

    def ids(self, q):
        return [i for i, _ in self.s.rank(self.entries, q)]

    def test_separators_and_case(self):
        for q in (u'he200a', u'HE 200 A', u'he-200a', u'He200A'):
            self.assertEqual(self.ids(q), [0], q)

    def test_all_words_must_match(self):
        self.assertEqual(self.ids(u'concrete column'), [1])
        self.assertEqual(self.ids(u'concrete beam'), [])

    def test_order_name_then_tags_then_description(self):
        # 'column' is in names of 0 and 1, only in the description of 2
        self.assertEqual(self.ids(u'column'), [0, 1, 2])
        self.assertEqual(self.ids(u'foundation'), [2])

    def test_name_prefix_first(self):
        self.assertEqual(self.ids(u'concrete col')[0], 1)
        self.assertEqual(self.s.rank(self.entries, u'beam tag')[0], (3, 0))

    def test_russian_and_hebrew(self):
        self.assertEqual(self.ids(u'колонна бетон'), [1])
        self.assertEqual(self.ids(u'כלונס'), [2])
        self.assertEqual(self.ids(u'Ёмкость'), [])          # unknown word: nothing, no error

    def test_invisible_marks(self):
        self.assertEqual(self.ids(u'‏bored'), [2])

    def test_empty_query_keeps_all(self):
        self.assertEqual(self.ids(u'  '), [0, 1, 2, 3])


if __name__ == '__main__':
    unittest.main()
