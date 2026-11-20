# -*- coding: utf-8 -*-
"""Sections for the big check of the section families (revit_check.py) and
for the gallery. Pure Python.

Each case: (name, shape, b, h, cover, bar dia, nb, nh, overrides)
RECT: nb / nh = bars along b / along h with the corners.
Rounded: nb = bars on each end without the side bars, nh = bars on each long side.
"""

RECT, ROUND1, ROUND2 = 'RECT', 'ROUND1', 'ROUND2'


def cases():
    out = []
    # rectangular columns: sizes x bars, typical covers
    rect = [
        (250, 250, 12, 2, 2), (300, 300, 14, 2, 2), (300, 300, 16, 3, 3), (300, 400, 16, 2, 3),
        (350, 350, 16, 3, 3), (400, 400, 20, 3, 3), (400, 400, 16, 4, 4), (400, 600, 20, 3, 4),
        (400, 600, 25, 3, 5), (500, 500, 20, 4, 4), (500, 500, 25, 5, 5), (500, 700, 20, 4, 5),
        (600, 600, 16, 5, 5), (600, 600, 25, 4, 4), (600, 800, 25, 4, 6), (700, 700, 25, 6, 6),
        (800, 800, 25, 4, 4), (800, 800, 32, 6, 6), (900, 900, 25, 7, 7), (1000, 1000, 20, 7, 7),
        (1000, 1000, 25, 8, 8), (1200, 1200, 25, 9, 9), (1500, 1500, 32, 9, 9),
        (300, 900, 16, 2, 5), (350, 1050, 20, 2, 6),
    ]
    for b, h, d, nb, nh in rect:
        out.append(('R%dx%d_%dx%dD%d' % (b, h, nb, nh, d), RECT, b, h, 25, d, nb, nh, {}))
    # pylons and walls
    for b, h, d, nb, nh in [(1500, 600, 20, 7, 3), (600, 1500, 20, 3, 7), (1200, 400, 16, 7, 3),
                            (1800, 500, 20, 9, 3), (1000, 300, 16, 6, 2), (2000, 400, 20, 11, 3),
                            (1600, 500, 25, 8, 3), (250, 1200, 16, 2, 7)]:
        out.append(('P%dx%d_%dx%dD%d' % (b, h, nb, nh, d), RECT, b, h, 25, d, nb, nh, {}))
    # covers, stirrup overrides, modes
    out += [
        ('R500_cover40', RECT, 500, 500, 40, 20, 4, 4, {}),
        ('R500_cover50', RECT, 500, 500, 50, 25, 4, 4, {}),
        ('R400_cover20', RECT, 400, 400, 20, 16, 3, 3, {}),
        ('R600_st12', RECT, 600, 600, 25, 25, 5, 5, {'stirrup_dia': 12}),
        ('R800_ties', RECT, 800, 800, 25, 25, 4, 4, {'transverse': 'ties'}),
        ('R1000_ties', RECT, 1000, 1000, 25, 20, 7, 7, {'transverse': 'ties'}),
        ('P1500_hoops', RECT, 1500, 600, 25, 20, 7, 3, {'transverse': 'hoops'}),
        ('P1500_ties', RECT, 1500, 600, 25, 20, 7, 3, {'transverse': 'ties'}),
        ('R1200_hoops', RECT, 1200, 1200, 25, 25, 9, 9, {'transverse': 'hoops'}),
    ]
    # bad on purpose (red messages) - the family must still draw something sane
    out += [
        ('bad_4bars_400', RECT, 400, 400, 25, 20, 2, 2, {}),
        ('bad_gap_300', RECT, 300, 300, 25, 25, 5, 5, {}),
        ('bad_far_800x400', RECT, 800, 400, 25, 16, 2, 2, {}),
    ]
    # rounded both ends
    for b, h, d, nb, nh in [(300, 600, 16, 1, 2), (300, 900, 16, 1, 3), (400, 800, 20, 1, 3),
                            (400, 1000, 20, 2, 4), (500, 900, 20, 3, 5), (500, 1500, 20, 3, 6),
                            (600, 1200, 20, 3, 4), (600, 1200, 25, 3, 5), (800, 1600, 25, 5, 6),
                            (500, 1000, 16, 3, 6), (400, 1600, 20, 2, 8), (600, 1200, 20, 1, 4)]:
        out.append(('O2_%dx%d_%d_%dD%d' % (b, h, nb, nh, d), ROUND2, b, h, 25, d, nb, nh, {}))
    # rounded one end
    for b, h, d, nb, nh in [(300, 600, 16, 1, 2), (400, 800, 20, 1, 3), (400, 1000, 20, 1, 4),
                            (500, 900, 20, 3, 4), (600, 1000, 20, 3, 4), (600, 1200, 25, 3, 5),
                            (800, 1400, 25, 5, 5), (500, 1500, 20, 3, 7), (600, 1000, 20, 2, 4),
                            (700, 1100, 20, 5, 4)]:
        out.append(('O1_%dx%d_%d_%dD%d' % (b, h, nb, nh, d), ROUND1, b, h, 25, d, nb, nh, {}))
    return out
