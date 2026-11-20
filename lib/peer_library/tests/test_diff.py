# -*- coding: utf-8 -*-
"""family_diff without Revit:  py -3 -m unittest discover -s lib/peer_library/tests"""

import codecs
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from peer_library import family_diff as D  # noqa: E402

LEN = u'autodesk.spec.aec:length-2.0.0'
INT = u'autodesk.spec:int-2.0.0'
TXT = u'autodesk.spec:string-2.0.0'


def par(name, shared=False, guid=u'', instance=True, spec=LEN, formula=u''):
    return {'name': name, 'shared': shared, 'guid': guid, 'instance': instance,
            'spec': spec, 'formula': formula, 'reporting': False}


def sig(params, category=u'Detail Items', types=(u'T1',), nested=()):
    return {'name': u'F', 'category': category, 'params': list(params),
            'types': list(types), 'nested': list(nested)}


def codes(findings):
    return [f[1] for f in findings]


class TestCompare(unittest.TestCase):

    def test_same_family_is_clean(self):
        s = sig([par(u'A'), par(u'Rebar_Number', True, u'g1', spec=INT)])
        self.assertEqual(D.compare(s, s), [])
        self.assertIsNone(D.worst(D.compare(s, s)))

    def test_missing_parameter_is_an_error(self):
        p = sig([par(u'A'), par(u'B')])
        l = sig([par(u'A'), par(u'C')])
        f = D.compare(p, l)
        self.assertEqual(D.worst(f), D.ERROR)
        self.assertIn('param_missing', codes(f))
        self.assertIn('param_new', codes(f))
        self.assertIn(u"'B'", [x for x in f if x[1] == 'param_missing'][0][2])

    def test_other_guid_same_name(self):
        p = sig([par(u'Rebar_Number', True, u'g1', spec=INT)])
        l = sig([par(u'Rebar_Number', True, u'g2', spec=INT)])
        self.assertEqual(codes(D.compare(p, l)), ['guid'])

    def test_renamed_shared_parameter_keeps_values(self):
        p = sig([par(u'Old', True, u'g1')])
        l = sig([par(u'New', True, u'g1')])
        f = D.compare(p, l)
        self.assertEqual(codes(f), ['renamed'])
        self.assertEqual(D.worst(f), D.INFO)

    def test_shared_switch_spec_and_spelling(self):
        p = sig([par(u'S', True, u'g1'), par(u'L'), par(u'Bar  Mark')])
        l = sig([par(u'S'), par(u'L', spec=TXT), par(u'bar mark')])
        c = codes(D.compare(p, l))
        self.assertIn('shared_switch', c)
        self.assertIn('spec', c)
        self.assertIn('spelling', c)

    def test_instance_type_and_formula_are_warnings(self):
        p = sig([par(u'A', instance=True), par(u'B', instance=False)])
        l = sig([par(u'A', instance=False), par(u'B', instance=False, formula=u'A * 2')])
        f = D.compare(p, l)
        self.assertEqual(sorted(codes(f)), ['formula', 'inst_type'])
        self.assertEqual(D.worst(f), D.WARNING)

    def test_category_and_types(self):
        p = sig([], category=u'Detail Items', types=(u'T1', u'Mine'))
        l = sig([], category=u'Generic Models', types=(u'T1', u'T2'))
        c = codes(D.compare(p, l))
        self.assertEqual(c[0], 'category')
        self.assertIn('types_extra', c)
        self.assertIn('types_new', c)

    def test_peer_version_is_ignored(self):
        p = sig([par(u'A')])
        l = sig([par(u'A'), par(u'PEER_Version', instance=False, spec=INT, formula=u'1')])
        self.assertEqual(D.compare(p, l), [])

    def test_project_shared_conflict(self):
        l = sig([par(u'Rebar_Number', True, u'g2', spec=INT), par(u'X', True, u'g3')])
        f = D.compare(sig([]), l, project_shared={u'g1': u'Rebar_Number', u'g3': u'X old'})
        c = codes(f)
        self.assertIn('guid_project', c)
        self.assertIn('guid_name', c)

    def test_nested_shared_family_in_project(self):
        l = sig([], nested=[{'name': u'TN_Label', 'category': u'Generic Annotations',
                             'shared': True}, {'name': u'Inner', 'shared': False}])
        f = D.compare(sig([]), l, project_names={u'tn_label', u'inner'})
        self.assertEqual(codes(f), ['nested'])


class TestTrial(unittest.TestCase):

    def test_trial_findings(self):
        t = {'failed': [], 'warnings': [u'w1', u'w1', u'w2'],
             'deleted': {'dimensions': 12, 'tags': 0, 'instances': 0, 'other': 2},
             'other_categories': [u'Detail Items'],
             'lost': {u'Rebar_Number': [340, 0]}, 'changed': {u'A': [20, 1]},
             'instances': 340, 'types': 3}
        f = D.trial_findings(t)
        c = codes(f)
        self.assertEqual(D.worst(f), D.ERROR)
        self.assertIn('deleted_dimensions', c)
        self.assertNotIn('deleted_tags', c)
        self.assertIn('deleted_other', c)
        self.assertIn('values_lost', c)
        self.assertIn('values_changed', c)
        text = [x[2] for x in f if x[1] == 'values_lost'][0]
        self.assertIn(u"'Rebar_Number' in 340 elements", text)
        self.assertIn(u'(Detail Items)', [x[2] for x in f if x[1] == 'deleted_other'][0])
        warn = [x[2] for x in f if x[1] == 'revit_warnings'][0]
        self.assertEqual(warn.count(u'w1'), 1)
        self.assertIn('values_reset', codes(D.trial_findings(t, overwrite=True)))
        self.assertIn(u'340 placed elements, 3 types', D.trial_summary(t))

    def test_needs_delete(self):
        t = {'resolved': [u'One or more dimension references are or have become invalid.'] * 2,
             'deleted': {'dimensions': 1}}
        f = D.trial_findings(t)
        self.assertEqual(codes(f)[:2], ['needs_delete', 'deleted_dimensions'])
        self.assertEqual(f[0][2].count(u'invalid'), 1)

    def test_clean_trial(self):
        t = {'failed': [], 'warnings': [], 'deleted': {}, 'lost': {}, 'changed': {},
             'instances': 2, 'types': 1}
        self.assertEqual(D.trial_findings(t), [])
        self.assertEqual(D.trial_findings({'failed': [u'x']})[0][1], 'failed')


class TestOneFamily(unittest.TestCase):

    def test_hygiene(self):
        a = par(u'Bar Mark')
        b = par(u'bar  mark')
        u = par(u'Width')
        u['unused'] = True
        s = sig([a, b, u, par(u'PEER_Version', spec=INT)],
                nested=[{'name': u'PEER_Rebar TAG', 'shared': True}, {'name': u'Inner', 'shared': True}])
        c = codes(D.hygiene_findings(s, [u'peer_rebar tag', u'Other']))
        self.assertIn('twins', c)
        self.assertIn('spaces', c)
        self.assertIn('unused', c)
        self.assertEqual(c.count('nested_library'), 1)
        self.assertNotIn('no_version', c)
        self.assertIn('no_version', codes(D.hygiene_findings(sig([par(u'A')]))))

    def test_one_letter_case_is_a_convention(self):
        s = sig([par(u'b'), par(u'B'), par(u'r1'), par(u'R1'), par(u'Washer d'), par(u'Washer D'),
                 par(u'PEER_Version')])
        self.assertNotIn('twins', codes(D.hygiene_findings(s)))
        s = sig([par(u'Cover Top'), par(u'cover top'), par(u'PEER_Version')])
        self.assertIn('twins', codes(D.hygiene_findings(s)))

    def test_shared_file_self(self):
        shared = {'by_guid': {}, 'by_name': {u'PR_?_Angle': {u'g1', u'g2'}, u'PR_A': {u'g3'}}}
        c = codes(D.shared_file_self(shared, u'PR_FOPv4.txt'))
        self.assertEqual(sorted(c), ['file_lost_chars', 'file_twins'])

    def test_types(self):
        f = D.types_findings([(u'600x600', u'Constraints are not satisfied')])
        self.assertEqual(codes(f), ['type_broken'])
        self.assertIn(u"'600x600'", f[0][2])


class TestSharedFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='peerdiff_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, encoding):
        path = os.path.join(self.tmp, 'fop.txt')
        with open(path, 'wb') as f:
            if encoding == 'utf-16':
                f.write(codecs.BOM_UTF16_LE + text.encode('utf-16-le'))
            else:
                f.write(text.encode(encoding))
        return path

    FOP = (u'# This is a Revit shared parameter file.\r\n*META\tVERSION\tMINVERSION\r\nMETA\t2\t1\r\n'
           u'*GROUP\tID\tNAME\r\nGROUP\t11\tRebar\r\n'
           u'*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\r\n'
           u'PARAM\t3DAAA3A8-42d9-4e71-86e3-9541a415b23b\tRebar_Number\tINTEGER\t\t11\t1\t\t1\t0\r\n'
           u'PARAM\tc714ca8d-a6ab-4e35-b7ee-58433b31e364\tPR_Rebar_ID\tINTEGER\t\t11\t1\t\t1\t0\r\n'
           u'PARAM\t11111111-0000-0000-0000-000000000000\tКомментарий\tTEXT\t\t11\t1\t\t1\t0\r\n')

    def test_read_utf16_and_utf8(self):
        for enc in ('utf-16', 'utf-8'):
            s = D.read_shared_file(self.write(self.FOP, enc))
            self.assertEqual(len(s['by_guid']), 3)
            self.assertEqual(s['by_guid']['3daaa3a8-42d9-4e71-86e3-9541a415b23b'][0], u'Rebar_Number')
            self.assertIn(u'Комментарий', s['by_name'])

    def test_findings(self):
        s = D.read_shared_file(self.write(self.FOP, 'utf-16'))
        fam = sig([par(u'Rebar_Number', True, u'99999999-0000-0000-0000-000000000000', spec=INT),
                   par(u'PR_Rebar_ID', True, u'c714ca8d-a6ab-4e35-b7ee-58433b31e364', spec=INT),
                   par(u'Old name', True, u'11111111-0000-0000-0000-000000000000', spec=TXT),
                   par(u'pr_rebar_id '), par(u'My own', True, u'22222222-0000-0000-0000-000000000000'),
                   par(u'Free')])
        f = D.shared_file_findings(fam, s, u'PR_FOPv4.txt')
        c = codes(f)
        self.assertEqual(c[0], 'file_guid')
        self.assertIn('file_name', c)
        self.assertIn('should_share', c)
        self.assertIn('file_missing', c)
        self.assertNotIn(u"'Free'", u' '.join(x[2] for x in f))


if __name__ == '__main__':
    unittest.main()
