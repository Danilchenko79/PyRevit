# -*- coding: utf-8 -*-
"""code466 result -> PEER_Column Section parameters:
    py -3 -m unittest discover -s lib/column_rebar/tests"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from column_rebar import code466 as c, slots  # noqa: E402


def on(p, prefix):
    return sorted(k[:-4] for k, v in p.items() if k.startswith(prefix) and k.endswith('_Vis') and v)


class Slots(unittest.TestCase):

    def test_hoops_800(self):
        r = c.design(c.RECT, 800, 800, 25, 25, 4, 4)
        p = slots.params(r, 800, 800, 25, 25, 4, 4)
        self.assertEqual(on(p, 'Hoop'), ['HoopH1', 'HoopV1'])
        self.assertEqual(on(p, 'Tie'), [])
        cr = 25 + 8 + 12.5
        step = (800 - 2 * cr) / 3.0
        self.assertAlmostEqual(p['HoopV1_X'], cr + step)
        self.assertAlmostEqual(p['HoopV1_A'], step)
        self.assertEqual((p['Rebar_QuantityX'], p['Rebar_QuantityY']), (2, 2))

    def test_pylon_v(self):
        r = c.design(c.RECT, 1500, 600, 25, 20, 7, 3)
        p = slots.params(r, 1500, 600, 25, 20, 7, 3)
        self.assertEqual(on(p, 'V'), ['VL', 'VR'])
        self.assertEqual(len(on(p, 'TieV')), 5)
        cr = 25 + 8 + 10
        self.assertAlmostEqual(p['VL_Y'], 300)
        self.assertAlmostEqual(p['VL_W'], 600 - 2 * cr)
        step = (1500 - 2 * cr) / 6.0
        self.assertAlmostEqual(p['VL_H'], step)          # apex to the first long-face bar
        self.assertAlmostEqual(p['VR_H'], step)

    def test_all_off_by_default(self):
        r = c.design(c.RECT, 300, 300, 25, 12, 2, 2)
        p = slots.params(r, 300, 300, 25, 12, 2, 2)
        self.assertEqual([k for k, v in p.items() if k.endswith('_Vis') and v], [])

    def test_contour(self):
        r = c.design(c.ROUND2, 500, 1250, 25, 20, 3, 6)
        p = slots.params(r, 500, 1250, 25, 20, 3, 6, c.ROUND2)
        self.assertEqual((p['Contour_Split'], p['U_Leg']), (1, 320))
        r = c.design(c.ROUND2, 500, 1250, 25, 20, 3, 6, contour=c.CONTOUR_ONE)
        self.assertEqual(slots.params(r, 500, 1250, 25, 20, 3, 6, c.ROUND2)['Contour_Split'], 0)

    def test_too_many(self):
        r = {'stirrup': {'dia': 8.0}, 'ties': [{'kind': 'straight', 'direction': 'vertical', 'at': 100.0}] * 13,
             'hoops': []}
        with self.assertRaises(ValueError):
            slots.params(r, 2000, 400, 25, 20, 11, 2)


if __name__ == '__main__':
    unittest.main()
