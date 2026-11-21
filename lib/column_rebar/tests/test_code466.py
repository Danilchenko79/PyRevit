# -*- coding: utf-8 -*-
"""Section by SI 466 (office guide 2026-11-20):
    py -3 -m unittest discover -s lib/column_rebar/tests"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from column_rebar import code466 as c  # noqa: E402
from column_rebar.code466 import RECT, CIRCLE, RED, YELLOW  # noqa: E402


def codes(r, level=None):
    return sorted(x['code'] for x in r['messages'] if level is None or x['level'] == level)


class Spacing(unittest.TestCase):

    def test_guide_example(self):
        # guide, section 5: 400x600, D20 -> D8@250/100; D12 -> D8@175/100
        self.assertEqual(c.design(RECT, 400, 600, 25, 20, 3, 4)['label'], u'Ø8@200/100')
        self.assertEqual(c.main_spacing(400, 12), 175)
        self.assertEqual(c.dense_spacing(250), 100)
        self.assertEqual(c.dense_spacing(175), 100)
        self.assertEqual(c.dense_spacing(150), 75)        # 0.6 * 150 = 90 -> 75

    def test_short_side_governs(self):
        self.assertEqual(c.main_spacing(200, 25), 200)

    def test_user_spacing_checked(self):
        r = c.design(RECT, 400, 600, 25, 12, 4, 4, spacing=250)
        self.assertIn('spacing', codes(r, RED))
        r = c.design(RECT, 400, 600, 25, 20, 3, 4, dense=150)
        self.assertIn('dense', codes(r, RED))


class StirrupDia(unittest.TestCase):

    def test_series(self):
        self.assertEqual(c.stirrup_dia_min(12), 8)
        self.assertEqual(c.stirrup_dia_min(32), 8)
        self.assertEqual(c.stirrup_dia_min(36), 10)       # 36/4 = 9

    def test_user_too_thin(self):
        r = c.design(RECT, 600, 600, 25, 36, 4, 4, stirrup_dia=8)
        self.assertIn('stirrup_dia', codes(r, RED))

    def test_tie_thicker_than_bar(self):
        r = c.design(RECT, 400, 400, 25, 12, 3, 3, stirrup_dia=14)
        self.assertIn('tie_hook', codes(r, RED))


class Bars(unittest.TestCase):

    def test_ratio_levels(self):
        self.assertIn('rho_min', codes(c.design(RECT, 400, 600, 25, 12, 3, 3), RED))     # 0.38 %
        self.assertIn('rho_reduced', codes(c.design(RECT, 300, 300, 25, 12, 2, 2), YELLOW))
        self.assertIn('rho_max', codes(c.design(RECT, 300, 300, 25, 32, 4, 4), RED))

    def test_min_dia_and_count(self):
        self.assertIn('bar_dia', codes(c.design(RECT, 300, 300, 25, 10, 3, 3), RED))
        self.assertIn('bar_count', codes(c.design(RECT, 300, 300, 25, 16, 1, 2), RED))
        self.assertIn('bar_count', codes(c.design(CIRCLE, 400, None, 25, 16, 5), RED))

    def test_wall_warning(self):
        self.assertIn('wall', codes(c.design(RECT, 200, 1200, 25, 16, 2, 6), YELLOW))
        self.assertNotIn('wall', codes(c.design(RECT, 150, 700, 25, 16, 2, 4)))   # < 800

    def test_clear_gap(self):
        r = c.design(RECT, 300, 300, 25, 25, 5, 5)
        self.assertIn('gap', codes(r, RED))

    def test_corner_in_bend(self):
        # D20 in a D8 stirrup: r = 16, 25 + 8 + 16 - 6 / sqrt2
        self.assertAlmostEqual(c.corner_offset(25, 8, 20), 44.757, places=3)
        # bar thicker than the arc: touches both legs
        self.assertAlmostEqual(c.corner_offset(25, 8, 40), 25 + 8 + 20)

    def test_count_and_symmetry(self):
        r = c.design(RECT, 400, 600, 25, 20, 3, 4)
        self.assertEqual(len(r['bars']), 10)
        xs = sorted(round(x, 6) for x, y in r['bars'])
        self.assertEqual(xs, sorted(round(400 - x, 6) for x in xs))


class Restraint(unittest.TestCase):

    def test_every_second_when_close(self):
        # 5 bars, 128 apart: corners + the middle one
        r = c.design(RECT, 600, 600, 25, 16, 5, 5)
        self.assertEqual([round(t['at']) for t in r['ties']], [300, 300])
        self.assertFalse(c.blocked(r))

    def test_every_bar_when_far(self):
        # 4 bars, 235 apart: both middle bars tied
        r = c.design(RECT, 800, 800, 25, 25, 4, 4, transverse=c.TIES)
        self.assertEqual(len(r['ties']), 4)


class Hoops(unittest.TestCase):

    def test_column_pairs_ties_into_hoops(self):
        # user sketch 2026-11-20: 800x800 4x4 -> one inner hoop per direction
        r = c.design(RECT, 800, 800, 25, 25, 4, 4)
        self.assertEqual(r['ties'], [])
        self.assertEqual([x['bars'] for x in r['hoops']], [(1, 2), (1, 2)])
        self.assertTrue(all(x['kind'] == 'rect' for x in r['hoops']))

    def test_odd_middle_keeps_a_tie(self):
        r = c.design(RECT, 1000, 1000, 25, 20, 7, 7)
        self.assertEqual(len(r['ties']), 2)
        self.assertEqual(len(r['hoops']), 4)

    def test_pairing(self):
        self.assertEqual(c.pair_up([1, 2]), ([(1, 2)], []))
        self.assertEqual(c.pair_up([1, 3, 5]), ([(1, 5)], [3]))
        self.assertEqual(c.pair_up([1, 2, 4, 5]), ([(1, 2), (4, 5)], []))
        self.assertEqual(c.pair_up([1, 2, 3, 4, 5]), ([(1, 2), (4, 5)], [3]))

    def test_pylon_v_ties(self):
        # user sketch 2026-11-20: pylon, middle bar of a short face - a V-shaped
        # tie to the long faces + a straight tie between its ends
        r = c.design(RECT, 1500, 600, 25, 20, 7, 3)
        v = [t for t in r['ties'] if t['kind'] == 'v']
        straight = [t for t in r['ties'] if t['kind'] == 'straight']
        self.assertEqual(len(v), 2)
        self.assertTrue(all(t['apex_angle'] <= 135 for t in v))
        self.assertTrue(all(t['direction'] == c.VERTICAL for t in straight))    # short ties only
        ends = set(round(t['points'][0][0]) for t in v)
        self.assertTrue(ends <= set(round(t['at']) for t in straight))         # straight tie at each V end
        self.assertEqual(r['hoops'], [])
        self.assertTrue(all(r['restrained']))

    def test_v_tie_forces_restraint(self):
        # long faces 150 apart would need few ties; the V ends are held anyway
        self.assertEqual(c.restrain_side([0, 100, 200, 300, 400], forced=(1, 3)), [0, 1, 3, 4])

    def test_modes_compare(self):
        a = c.design(RECT, 800, 800, 25, 25, 4, 4, transverse=c.TIES)
        b = c.design(RECT, 800, 800, 25, 25, 4, 4, transverse=c.HOOPS)
        self.assertGreater(b['set_length'], a['set_length'])

    def test_single_middle_bar_over_150_is_tied(self):
        r = c.design(RECT, 400, 400, 25, 20, 3, 3)       # 155 from both corners
        self.assertEqual(len(r['ties']), 2)

    def test_too_far_even_tied(self):
        r = c.design(RECT, 800, 400, 25, 16, 2, 2)       # 715 between the corners
        self.assertIn('restrained', codes(r, RED))

    def test_corners_always_restrained(self):
        r = c.design(RECT, 400, 400, 25, 20, 2, 2)       # rule broken, corners still held
        self.assertEqual(r['restrained'], [True] * 4)

    def test_side_rule(self):
        self.assertEqual(c.restrain_side([0, 140, 280]), [0, 2])
        self.assertEqual(c.restrain_side([0, 160, 320]), [0, 1, 2])
        self.assertIsNone(c.restrain_side([0, 310]))
        got = c.restrain_side([0, 100, 200, 300, 400, 500, 600])
        self.assertEqual(got, sorted(6 - k for k in got))   # symmetric

    def test_circle_all_restrained(self):
        r = c.design(CIRCLE, 500, None, 30, 16, 8)
        self.assertTrue(all(r['restrained']))
        self.assertEqual(r['ties'], [])
        self.assertIn('restrained', codes(c.design(CIRCLE, 1200, None, 30, 20, 6), RED))


class Rounded(unittest.TestCase):

    def test_round2_counts_and_ties(self):
        r = c.design(c.ROUND2, 500, 1500, 25, 20, 3, 6)         # pylon: ties across
        self.assertEqual(len(r['bars']), 2 * 3 + 2 * 6)
        self.assertTrue(all(r['restrained']))
        self.assertEqual(len(r['ties']), 4)
        self.assertEqual(r['hoops'], [])
        self.assertFalse(c.blocked(r))

    def test_round2_column_uses_hoops(self):
        r = c.design(c.ROUND2, 600, 1200, 25, 20, 3, 4)          # h / b = 2, side bars 200 apart
        self.assertEqual([x['kind'] for x in r['hoops']], ['rect'])
        self.assertEqual(r['ties'], [])
        one = c.design(c.ROUND2, 500, 900, 25, 20, 3, 5)         # a single middle bar: a tie
        self.assertEqual((len(one['ties']), one['hoops']), (1, []))

    def test_round2_arc_too_long(self):
        r = c.design(c.ROUND2, 600, 1200, 25, 20, 1, 4)
        self.assertIn('restrained', codes(r, RED))

    def test_round1_flat_end_v_tie(self):
        r = c.design(c.ROUND1, 400, 800, 25, 20, 1, 3)
        v = [t for t in r['ties'] if t['kind'] == 'v']
        self.assertEqual(len(v), 1)
        self.assertLessEqual(v[0]['apex_angle'], 135)
        straight = [t for t in r['ties'] if t['kind'] == 'straight']
        self.assertEqual([round(t['at']) for t in straight], [round(v[0]['points'][0][1])])
        self.assertEqual(len(r['bars']), 8)
        self.assertTrue(all(r['restrained']))

    def test_round_needs_long_h(self):
        self.assertIn('round_sides', codes(c.design(c.ROUND2, 800, 400, 25, 20, 2, 3), RED))

    def test_area(self):
        r = c.design(c.ROUND2, 400, 1000, 25, 20, 2, 4)
        ac = 400 * 1000 - 2 * (2 - 3.141592653589793 / 2) * 200 ** 2
        self.assertAlmostEqual(r['rho'], 12 * 3.141592653589793 * 100 / ac)


class Contour(unittest.TestCase):
    """User 2026-11-21: a rounded column - a rect hoop over the straight part +
    half-round U-bars (default), or one stirrup along the outline."""

    def test_round2_split_default(self):
        r = c.design(c.ROUND2, 500, 1250, 25, 20, 3, 6)
        st = r['stirrup']
        self.assertEqual(st['contour'], c.CONTOUR_SPLIT)
        self.assertEqual((st['rect']['a'], st['rect']['b']), (450, 750 + 20 + 16))
        self.assertEqual((st['u']['leg'], st['u']['count'], st['u']['b']), (320, 2, 320 + 225))
        self.assertAlmostEqual(st['length'], st['rect']['length'] + 2 * st['u']['length'])
        self.assertEqual(codes(r, YELLOW), [])

    def test_one_keeps_the_outline(self):
        r = c.design(c.ROUND2, 500, 1250, 25, 20, 3, 6, contour=c.CONTOUR_ONE)
        self.assertEqual(r['stirrup']['contour'], c.CONTOUR_ONE)
        self.assertNotIn('u', r['stirrup'])

    def test_round1_one_u(self):
        r = c.design(c.ROUND1, 400, 800, 25, 20, 1, 3)
        u = r['stirrup']['u']
        self.assertEqual((u['count'], u['leg']), (1, 320))
        self.assertAlmostEqual(r['stirrup']['rect']['b'], 800 - 200 - 25 + 10 + 8)

    def test_short_straight_part_warns(self):
        r = c.design(c.ROUND2, 600, 700, 25, 20, 3, 2)
        self.assertEqual(r['stirrup']['u']['leg'], 100)
        self.assertIn('u_leg', codes(r, YELLOW))

    def test_from_text(self):
        self.assertEqual(c.contour_from_text(u'One'), c.CONTOUR_ONE)
        self.assertEqual(c.contour_from_text(None), c.CONTOUR_SPLIT)


class WideV(unittest.TestCase):
    """User 2026-11-21: two middle bars on the short face of a pylon - one V
    with a flat end round both (bend <= 135 deg)."""

    def test_pylon_two_middle_bars(self):
        r = c.design(c.RECT, 600, 1500, 25, 20, 4, 7)
        v = [t for t in r['ties'] if t.get('kind') == 'v']
        self.assertEqual(len(v), 2)
        for t in v:
            self.assertTrue(t.get('flat'))
            self.assertLessEqual(t['apex_angle'], 135.0 + 1e-6)
            (a1, a2) = t['flat']
            self.assertAlmostEqual(a2[0] - a1[0], 170.0, places=0)      # the two middle bars
        self.assertFalse(c.blocked(r))

    def test_one_middle_bar_keeps_the_point(self):
        r = c.design(c.RECT, 1500, 600, 25, 20, 7, 3)
        v = [t for t in r['ties'] if t.get('kind') == 'v']
        self.assertEqual(len(v), 2)
        self.assertFalse(any(t.get('flat') for t in v))


class Circle(unittest.TestCase):

    def test_round_column(self):
        r = c.design(c.CIRCLE, 600, 600, 25, 20, 10)
        self.assertEqual(len(r['bars']), 10)
        self.assertEqual((r['ties'], r['hoops']), ([], []))
        self.assertFalse(c.blocked(r))


class Alternate(unittest.TestCase):
    """User 2026-11-20: a face needing one of two symmetric bars held - the tie
    goes in turn on one and on the other (the mirror one drawn dashed)."""

    def test_four_bar_faces(self):
        r = c.design(RECT, 400, 400, 25, 16, 4, 4)
        alt = [t for t in r['ties'] if t.get('alt')]
        solid = [t for t in r['ties'] if not t.get('alt')]
        self.assertEqual((len(solid), len(alt)), (2, 2))
        for s in solid:
            m = [a for a in alt if a['direction'] == s['direction']][0]
            self.assertAlmostEqual(s['at'] + m['at'], 400)          # the mirror bar
        self.assertEqual(c.summary(r), u'Ø8@200/100; 2 ties (alternating)')

    def test_symmetric_face_has_no_alternate(self):
        r = c.design(RECT, 600, 600, 25, 16, 5, 5)
        self.assertFalse(any(t.get('alt') for t in r['ties']))

    def test_steel_counts_one_of_the_pair(self):
        r = c.design(RECT, 400, 400, 25, 16, 4, 4)
        ties = [t['length'] for t in r['ties'] if not t.get('alt')]
        self.assertAlmostEqual(r['set_length'], r['stirrup']['length'] + sum(ties))


class FlatEnd(unittest.TestCase):

    def test_round1_flat_end_pairs_get_hoops(self):
        # user 2026-11-20: 2+ bars of the flat end - inner hoops on pairs
        r = c.design(c.ROUND1, 600, 1000, 25, 20, 2, 4)
        flat = [x for x in r['hoops'] if x['direction'] == 'flat']
        self.assertEqual(len(flat), 1)
        x0, y0, x1, y1 = flat[0]['box']
        self.assertGreater(y1, 900)                 # reaches the flat end (top)
        self.assertNotIn('flat_end', codes(r))

    def test_round1_five_bars(self):
        r = c.design(c.ROUND1, 800, 1400, 25, 25, 5, 5)
        self.assertEqual(len([x for x in r['hoops'] if x['direction'] == 'flat']), 1)
        self.assertNotIn('flat_end', codes(r))


class ColumnParams(unittest.TestCase):

    def test_summary(self):
        self.assertEqual(c.summary(c.design(RECT, 800, 800, 25, 25, 4, 4)),
                         u'Ø8@200/100; 2 inner hoops')
        self.assertEqual(c.summary(c.design(RECT, 1500, 600, 25, 20, 7, 3)),
                         u'Ø8@200/100; 2 V-ties + 5 ties')
        self.assertEqual(c.summary(c.design(RECT, 300, 300, 25, 12, 2, 2)), u'Ø8@175/100')
        self.assertEqual(c.summary({'label': None}), u'')

    def test_mode_from_text(self):
        self.assertEqual(c.mode_from_text(None), c.AUTO)
        self.assertEqual(c.mode_from_text(u' Ties'), c.TIES)
        self.assertEqual(c.mode_from_text(u'hoops'), c.HOOPS)
        self.assertEqual(c.mode_from_text(u'???'), c.AUTO)


class OldLegend(unittest.TestCase):

    def test_counts(self):
        self.assertEqual(c.from_old_counts(2, 3), (4, 5))


if __name__ == '__main__':
    unittest.main()
