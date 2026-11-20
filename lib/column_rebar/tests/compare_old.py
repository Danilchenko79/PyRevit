# -*- coding: utf-8 -*-
"""Ties on one side: family 'Klamrot 2d' vs old script vs code466 (SI 466).

    py -3 lib/column_rebar/tests/compare_old.py      (markdown table to stdout)

Family (Create Column.rfa > Klamrot 2d, formulas read 2026-11-20):
    bar axis at Cover + D/2 from the face (CoverR); spacing = axis distance;
    spacing <= 150 -> ties = (n-2)/2 if n even else (n-3)/2, first on bar 1 (n even)
    or bar 2 (n odd), every second bar; spacing > 150 -> every inner bar.
Old script: rules.tie_count (ceil(q/2) - 1 for spacing <= 150, q = n - 2).
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from column_rebar import code466, rules  # noqa: E402


def family(n, sp):
    if sp > 150.0:
        return list(range(1, n - 1))
    first = 1 if n % 2 == 0 else 2
    count = (n - 2) // 2 if n % 2 == 0 else (n - 3) // 2
    return [first + 2 * i for i in range(count)]


def ok(pos, tied):
    return code466._valid(pos, [0] + sorted(tied) + [len(pos) - 1])


def main(cover=25.0, dia=20.0):
    print(u'| side | n | axis c/c | family | old script | SI 466 (code466) |')
    print(u'|---|---|---|---|---|---|')
    for side in (300, 400, 500, 600, 700, 800, 1000):
        for n in (2, 3, 4, 5, 6, 7):
            # family geometry (cover to the bar)
            a = cover + dia / 2.0
            pos = [a + (side - 2 * a) * i / (n - 1.0) for i in range(n)]
            sp = pos[1] - pos[0]
            if sp - dia < 35:
                continue
            fam = family(n, sp)
            old = rules.tie_count(n - 2, sp, rules.RECT)
            # code466 geometry (cover to the stirrup, D8)
            r = code466.design(code466.RECT, side, side, cover, dia, n, n)
            new = len([t for t in r['ties'] if t['direction'] == code466.VERTICAL])
            gap = [x for x in r['messages'] if x['code'] in ('gap', 'restrained')]
            mark = lambda good: u'' if good else u' ✗'
            print(u'| %d | %d | %d | %d%s | %d%s | %s |' % (
                side, n, round(sp), len(fam), mark(ok(pos, fam)), old,
                u"" if old == len(fam) else u" ≠",
                (u'%d' % new) if not gap else u'нельзя: ' + gap[0]['code']))


if __name__ == '__main__':
    main()
