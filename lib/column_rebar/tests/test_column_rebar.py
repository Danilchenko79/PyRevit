# -*- coding: utf-8 -*-
"""Column reinforcement without Revit:  py -3 -m unittest discover -s lib/column_rebar/tests

The numbers fix the logic of the old Create Column script. A rule changed
to match the standard must show up here as a changed number."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from column_rebar import grouping, layout, rules  # noqa: E402
from column_rebar.rules import RECT, ROUND1, ROUND2  # noqa: E402


class Totals(unittest.TestCase):

    def test_rect_adds_four_corners(self):
        self.assertEqual(rules.total_bars(RECT, 2, 3), 14)      # the legend sketch
        self.assertEqual(rules.total_bars(RECT, 0, 1), 6)

    def test_rounded_has_no_extra_corners(self):
        self.assertEqual(rules.total_bars(ROUND2, 2, 3), 10)
        self.assertEqual(rules.total_bars(ROUND1, 2, 4), 12)

    def test_nothing_entered_is_zero(self):
        for shape in rules.SHAPES:
            self.assertEqual(rules.total_bars(shape, 0, 0), 0)


class Ties(unittest.TestCase):

    def test_wide_spacing_ties_every_bar(self):
        for q in range(1, 8):
            self.assertEqual(rules.tie_count(q, 151, RECT), q)
        self.assertEqual(rules.tie_count(3, None, RECT), 3)     # spacing unknown

    def test_close_spacing_ties_every_second_bar(self):
        got = [rules.tie_count(q, 150, RECT) for q in range(0, 8)]
        self.assertEqual(got, [0, 0, 0, 1, 1, 2, 2, 3])

    def test_rounded_takes_two_bars_off(self):
        self.assertEqual(rules.tie_count(2, 200, ROUND2), 0)
        self.assertEqual(rules.tie_count(4, 200, ROUND1), 2)
        self.assertEqual(rules.tie_count(5, 100, ROUND2), 1)    # 3 left -> 1

    def test_sizes(self):
        self.assertEqual(rules.stirrup_size(300, 600, 25), (250, 550))
        self.assertEqual(rules.tie_length(600, 25), 550)
        self.assertEqual(rules.stirrup_size(40, 40, 25), (0, 0))

    def test_estimate_spacing(self):
        # 600 - 2*(25+8) - 16 = 518 between the corner bars, 3 bars -> 4 gaps
        self.assertAlmostEqual(rules.estimate_spacing(600, 3, 25, 8, 16), 129.5)
        self.assertIsNone(rules.estimate_spacing(60, 1, 25, 8, 16))


class Transverse(unittest.TestCase):

    def kinds(self, items):
        return [(t['kind'], t['direction'], t['family_shape'], t['qty']) for t in items]

    def test_rect(self):
        items = rules.transverse(RECT, 300, 600, 1, 3, spacing_b=100, spacing_h=130)
        self.assertEqual(self.kinds(items), [
            ('stirrup', None, 52, 1),
            ('tie', 'horizontal', 62, 1)])       # qb=1 close -> no vertical tie
        self.assertEqual((items[0]['a'], items[0]['b']), (250, 550))
        self.assertEqual(items[1]['b'], 250)     # horizontal tie spans B
        self.assertEqual(items[0]['dia'], 8)
        self.assertEqual(items[1]['dia'], 10)
        self.assertEqual(items[1]['spacing'], 200)

    def test_vertical_tie_spans_h(self):
        items = rules.transverse(RECT, 600, 600, 3, 3, spacing_b=160, spacing_h=160)
        v = [t for t in items if t['direction'] == 'vertical'][0]
        self.assertEqual((v['b'], v['qty']), (550, 3))

    def test_round1_uses_shape_60(self):
        items = rules.transverse(ROUND1, 300, 600, 2, 4)
        self.assertEqual(self.kinds(items), [
            ('stirrup', None, 60, 1), ('tie', 'horizontal', 62, 2)])

    def test_round2_has_no_stirrup_yet(self):
        items = rules.transverse(ROUND2, 300, 800, 2, 5)
        self.assertEqual(self.kinds(items), [('tie', 'horizontal', 62, 3)])

    def test_family_can_switch_ties_off(self):
        items = rules.transverse(RECT, 600, 600, 3, 3,
                                 vertical_ties=False, horizontal_ties=False)
        self.assertEqual(self.kinds(items), [('stirrup', None, 52, 1)])

    def test_missing(self):
        self.assertEqual(rules.missing(0, 0, 0), [u'Rebar_Quantity', u'Rebar_Diameter'])
        self.assertEqual(rules.missing(0, 2, 16), [])


def col(i, mark, b=300, h=600, qb=1, qh=3, dia=16, shape=RECT):
    return {'id': i, 'mark': mark, 'shape': shape, 'b': b, 'h': h,
            'qb': qb, 'qh': qh, 'dia': dia}


class Grouping(unittest.TestCase):

    def test_marks_and_ranges(self):
        got = grouping.marks_and_ranges(['5', '1', '2', '3', '9', 'A1', '10'])
        self.assertEqual([(m['num'], m['num2']) for m in got],
                         [('1', '3'), ('5', None), ('9', None), ('10', None), ('A1', None)])
        self.assertEqual(got[0]['width'], 500)
        self.assertTrue(got[0]['num_plus'])

    def test_two_in_a_row_is_not_a_range(self):
        got = grouping.marks_and_ranges(['1', '2'])
        self.assertEqual([m['num_plus'] for m in got], [False, False])

    def test_mark_rows(self):
        rows = grouping.mark_rows(grouping.marks_and_ranges(
            ['1', '3', '5', '7', '9', '11', '13']))
        self.assertEqual([len(r) for r in rows], [5, 2])
        rows = grouping.mark_rows(grouping.marks_and_ranges(
            ['1', '3', '10', '11', '12']))
        self.assertEqual([len(r) for r in rows], [2, 1])        # the range wraps

    def test_sorted_marks_mixed(self):
        self.assertEqual(grouping.sorted_marks(['10', 'B', '2', 'A']),
                         ['2', '10', 'A', 'B'])

    def test_same_values_one_group_other_value_new_group(self):
        cols = [col(1, '1'), col(2, '2'), col(3, '3', qh=4), col(4, None), col(5, 'N/A')]
        groups, no_mark = grouping.make_groups(cols)
        self.assertEqual(no_mark, [4, 5])
        self.assertEqual([(g['marks'], g['qh']) for g in groups],
                         [(['3'], 4), (['1', '2'], 3)])

    def test_float_noise_does_not_split(self):
        cols = [col(1, '1', b=300.0), col(2, '2', b=300.00004), col(3, '3', dia=16.00001)]
        groups, _ = grouping.make_groups(cols)
        self.assertEqual(len(groups), 1)

    def test_order_shape_then_size(self):
        cols = [col(1, '1', shape=ROUND1), col(2, '2', b=300, h=400),
                col(3, '3', b=500, h=500), col(4, '4', shape=ROUND2)]
        groups, _ = grouping.make_groups(cols)
        self.assertEqual([g['marks'][0] for g in groups], ['3', '2', '4', '1'])

    def test_split_then_merge_back(self):
        groups, _ = grouping.make_groups([col(1, '2'), col(2, '1'), col(3, '7', h=900)])
        split = grouping.split_group(groups, 1)
        self.assertEqual([g['marks'] for g in split], [['7'], ['1'], ['2']])
        split[1]['qh'] = 5                       # edited after the split
        merged = grouping.merge_groups(split)
        self.assertEqual(len(merged), 3)
        split[1]['qh'] = 3
        merged = grouping.merge_groups(split)
        self.assertEqual(sorted(merged[1]['marks']), ['1', '2'])
        self.assertEqual(sorted(merged[1]['ids']), [1, 2])

    def test_duplicate_marks(self):
        cols = [col(1, '1'), col(2, '1'), col(3, '2'), col(4, None)]
        self.assertEqual(grouping.duplicate_marks(cols), {'1': [1, 2]})


class Layout(unittest.TestCase):

    def extent(self, b, h, qb, qh, marks):
        return layout.section_extent(
            b, h, rules.transverse(RECT, b, h, qb, qh, spacing_b=200, spacing_h=200), marks)

    def test_extent_covers_stirrup_and_ties(self):
        e = self.extent(300, 600, 3, 3, ['1'])
        # vertical tie: 1.5*300 + 550 + 250/2 = 1125, + tag 200 + 900
        self.assertEqual(e['right'], 2225)
        self.assertEqual(e['up'], 600 + 220 + 220 + 150)
        self.assertEqual(e['left'], 210 + 210)

    def test_wide_section_reaches_further(self):
        narrow = self.extent(300, 600, 3, 3, ['1'])
        wide = self.extent(1500, 600, 3, 3, ['1'])
        self.assertGreater(wide['right'], narrow['right'] + 1200)

    def test_many_marks_reach_left_and_down(self):
        one = self.extent(300, 600, 1, 1, ['1'])
        many = self.extent(300, 600, 1, 1, [str(n) for n in range(1, 30, 2)])
        self.assertEqual(many['left'], 210 + 5 * 210)
        self.assertEqual(many['down'] - one['down'], 2 * 210)

    def test_pack_no_overlap(self):
        exts = [self.extent(b, h, 3, 3, ['1'])
                for b, h in ((1500, 600), (300, 900), (300, 300), (600, 600), (400, 1200))]
        pts = layout.pack(exts, max_width=6000)
        boxes = [(x - e['left'], y - e['down'], x + e['right'], y + e['up'])
                 for (x, y), e in zip(pts, exts)]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                apart = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
                self.assertTrue(apart, (i, j))
        self.assertGreater(len(set(y for _, y in pts)), 1)      # it did wrap
        for box in boxes:
            self.assertLessEqual(box[2], 6000)

    def test_pack_too_wide_gets_own_row(self):
        exts = [self.extent(3000, 600, 3, 3, ['1']), self.extent(300, 300, 1, 1, ['2'])]
        pts = layout.pack(exts, max_width=1000)
        self.assertNotEqual(pts[0][1], pts[1][1])


if __name__ == '__main__':
    unittest.main()
