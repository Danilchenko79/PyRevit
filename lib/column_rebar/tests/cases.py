# -*- coding: utf-8 -*-
"""Sections for the big check of the section families (revit_check.py) and
for the gallery - by situation, not by what one project happens to have.
Pure Python.

Each case: (name, shape, b, h, cover, bar dia, nb, nh, overrides)
RECT: nb / nh = bars along b / along h with the corners.
Rounded: nb = bars on each end without the side bars, nh = bars on each long side.
"""

RECT, ROUND1, ROUND2 = 'RECT', 'ROUND1', 'ROUND2'


def _bars(side, cover, d, step, stirrup=8.0):
    """Bars along a side for a wanted centre spacing (corners included)."""
    span = side - 2 * (cover + stirrup) - d
    return max(2, int(round(span / float(step))) + 1)


def cases():
    out = []
    add = lambda name, *a: out.append((name,) + a)

    # 1. small columns, 4 corner bars only (and the limit of 300 between them)
    for b, h, d in [(200, 200, 12), (250, 250, 12), (250, 300, 14), (300, 300, 16), (300, 350, 16),
                    (350, 350, 16), (380, 380, 16), (400, 400, 20)]:
        add('small_%dx%d_D%d' % (b, h, d), RECT, b, h, 25, d, 2, 2, {})

    # 2. square columns, bars for ~120 / ~170 / ~220 mm spacing, several diameters
    for b in (400, 500, 600, 700, 800, 1000, 1200, 1500):
        for d, step in ((16, 120), (20, 170), (25, 220), (32, 170)):
            if d == 32 and b < 600:
                continue
            n = _bars(b, 25, d, step)
            add('sq%d_%dx%dD%d' % (b, n, n, d), RECT, b, b, 25, d, n, n, {})

    # 3. spacing just under / at / over 150 (the tie rule switches there)
    for b, n in ((500, 4), (600, 5), (700, 5), (760, 6)):
        add('rule150_%d_%dx%d' % (b, n, n), RECT, b, b, 25, 20, n, n, {})

    # 4. rectangles: column (h/b <= 2) -> pylon (> 2) -> wall (> 4)
    for b, h in [(400, 500), (400, 600), (400, 800), (500, 750), (500, 1000), (400, 1000),
                 (400, 1200), (300, 1200), (500, 1500), (400, 1600), (300, 1500), (250, 1200),
                 (600, 900), (600, 1200), (600, 1800), (800, 2000)]:
        d = 20
        add('rect%dx%d' % (b, h), RECT, b, h, 25, d, _bars(b, 25, d, 170), _bars(h, 25, d, 170), {})
        add('rect%dx%d_rot' % (h, b), RECT, h, b, 25, d, _bars(h, 25, d, 170), _bars(b, 25, d, 170), {})

    # 5. covers and stirrups
    for cover in (20, 30, 40, 50):
        add('cover%d_500' % cover, RECT, 500, 500, cover, 20, 4, 4, {})
    for st in (10, 12, 16):
        add('stirrup%d_600' % st, RECT, 600, 600, 25, 25, 5, 5, {'stirrup_dia': st})
    add('stirrup10_800x400', RECT, 800, 400, 25, 20, 6, 3, {'stirrup_dia': 10})

    # 6. modes
    for b, h, n1, n2 in ((800, 800, 4, 4), (1000, 1000, 7, 7), (1500, 600, 7, 3), (600, 1200, 4, 7)):
        for mode in ('ties', 'hoops'):
            add('mode_%s_%dx%d' % (mode, b, h), RECT, b, h, 25, 20, n1, n2, {'transverse': mode})

    # 7. bad on purpose: the program says why, the family must not break
    add('bad_D10', RECT, 400, 400, 25, 10, 3, 3, {})
    add('bad_rho_low', RECT, 600, 600, 25, 12, 3, 3, {})
    add('bad_rho_high', RECT, 300, 300, 25, 32, 4, 4, {})
    add('bad_gap', RECT, 300, 300, 25, 25, 5, 5, {})
    add('bad_far_bars', RECT, 900, 400, 25, 16, 2, 2, {})
    add('bad_thin_stirrup', RECT, 600, 600, 25, 36, 4, 4, {'stirrup_dia': 8})
    add('bad_cover_huge', RECT, 250, 250, 100, 16, 2, 2, {})

    # 8. rounded both ends: widths, lengths, bars on the ends and the sides
    for b in (300, 400, 500, 600, 800):
        for k in (1.6, 2.0, 2.5, 3.5):
            h = int(round(b * k / 50.0) * 50)
            d = 16 if b <= 300 else (20 if b <= 600 else 25)
            nh = max(2, _bars(h - b + 2 * 45, 0, 0, 170) - 0)
            ne = max(1, int(round(3.1416 * (b / 2.0 - 45) / 170.0)) - 1)
            add('r2_%dx%d_%d_%d' % (b, h, ne, nh), ROUND2, b, h, 25, d, ne, nh, {})
    add('r2_600x1200_arc_too_long', ROUND2, 600, 1200, 25, 20, 1, 4, {})
    add('r2_400x1600_long_sides', ROUND2, 400, 1600, 25, 20, 2, 8, {})
    add('r2_1000x2000_7_on_end', ROUND2, 1000, 2000, 25, 25, 7, 6, {})     # over the family's limit

    # 9. rounded one end: flat ends with 1..5 middle bars
    for b, h, ne, nh in [(300, 600, 1, 3), (400, 800, 1, 3), (400, 1000, 1, 4), (500, 900, 3, 4),
                         (500, 1200, 3, 5), (600, 1000, 2, 4), (600, 1000, 3, 4), (600, 1200, 3, 5),
                         (700, 1100, 4, 4), (700, 1100, 5, 4), (800, 1400, 5, 5), (800, 1600, 4, 6),
                         (500, 1500, 3, 7), (900, 1500, 6, 5)]:
        d = 20 if b <= 600 else 25
        add('r1_%dx%d_%d_%d' % (b, h, ne, nh), ROUND1, b, h, 25, d, ne, nh, {})
    return out


if __name__ == '__main__':
    cs = cases()
    print(len(cs))
    for c in cs:
        print(c[0], c[1:8])
