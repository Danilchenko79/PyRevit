# -*- coding: utf-8 -*-
"""code466.design() result -> parameters of the section families
'PEER_Column Section' / 'Round2' / 'Round1' (see family_section.py).
Pure Python, millimetres; the Revit side only converts units and sets values.

The families place the bars themselves (evenly between the end bars, axes at
CoverR = cover + stirrup + bar / 2 from the faces); code466 puts a rectangular
corner bar a little deeper (in the bend of the stirrup). Slot positions are
therefore snapped to the bars of the family's own layout.
"""

N_TIES, N_HOOPS = 12, 4
RECT, ROUND1, ROUND2 = 'RECT', 'ROUND1', 'ROUND2'


def slot_names(shape=RECT):
    """[(slot, kind, direction)] the family of this shape has, in build order."""
    out = []
    if shape == RECT:
        out += [('TieV%d' % i, 'tie', 'V') for i in range(1, N_TIES + 1)]
    out += [('TieH%d' % i, 'tie', 'H') for i in range(1, N_TIES + 1)]
    if shape == RECT:
        out += [('HoopV%d' % i, 'hoop', 'V') for i in range(1, N_HOOPS + 1)]
    out += [('HoopH%d' % i, 'hoop', 'H') for i in range(1, N_HOOPS + 1)]
    if shape == RECT:
        out += [('VB', 'v', 'B'), ('VT', 'v', 'T'), ('VL', 'v', 'L'), ('VR', 'v', 'R')]
    elif shape == ROUND1:
        out += [('VT', 'v', 'T'), ('HoopT1', 'hoopt', 'T'), ('HoopT2', 'hoopt', 'T')]
    return out


def family_bars(side, n, cover_r):
    """Bar axes along a side as the family draws them."""
    if n < 2:
        return []
    return [cover_r + (side - 2.0 * cover_r) * i / (n - 1.0) for i in range(n)]


def _even(a, b, n):
    return [a + (b - a) * i / (n - 1.0) for i in range(n)] if n >= 2 else []


def _snap(v, pos):
    return min(pos, key=lambda p: abs(p - v)) if pos else v


def bar_lines(shape, b, h, cr, nb, nh):
    """(xs, ys): bar axes the slots snap to. RECT: along b / along h with the
    corners. Rounded: xs - the flat end of ROUND1 (corners + nb), ys - the long
    sides from the bottom tangent point up to the top tangent point (ROUND2)
    or the top corner (ROUND1)."""
    if shape == RECT:
        return family_bars(b, nb, cr), family_bars(h, nh, cr)
    top = h - b / 2.0 if shape == ROUND2 else h - cr
    xs = family_bars(b, nb + 2, cr) if shape == ROUND1 else [cr, b - cr]
    return xs, _even(b / 2.0, top, nh)


def family_bar_points(shape, b, h, cr, nb, nh):
    """Every bar axis the family draws, [(x, y)] mm from the bottom-left corner."""
    import math
    xs, ys = bar_lines(shape, b, h, cr, nb, nh)
    if shape == RECT:
        pts = [(x, cr) for x in xs] + [(x, h - cr) for x in xs]
        pts += [(cr, y) for y in ys[1:-1]] + [(b - cr, y) for y in ys[1:-1]]
        return pts
    r = b / 2.0 - cr
    pts = [(cr, y) for y in ys] + [(b - cr, y) for y in ys]
    arcs = [(b / 2.0, math.pi)]                       # bottom half circle
    if shape == ROUND2:
        arcs.append((h - b / 2.0, 0.0))
    else:
        pts += [(x, h - cr) for x in xs[1:-1]]          # flat top end
    for yc, start in arcs:
        for k in range(1, nb + 1):
            th = start + math.pi * k / (nb + 1.0)
            pts.append((b / 2.0 + r * math.cos(th), yc + r * math.sin(th)))
    return pts


def params(result, b, h, cover, bar_dia, nb, nh, shape=RECT):
    """{family parameter: value} for a code466 result. Lengths in mm; yes/no
    and counts as int. RECT: nb / nh = bars along b / h with the corners.
    Rounded: nb = bars on each end without the side bars, nh = bars on each
    long side (the families' Rebar_QuantityX / Y).
    Raises ValueError when the result needs more slots than the family has."""
    st = result['stirrup']
    dw = st['dia'] if st else 8.0
    cr = cover + dw + bar_dia / 2.0
    xs, ys = bar_lines(shape, b, h, cr, nb, nh)
    out = {
        'PR_Dimension_Width': float(b), 'PR_Dimension_Height': float(h),
        'Cover': float(cover), 'Rebar_Diameter': float(bar_dia), 'Stirrup_Diameter': float(dw),
    }
    if shape == RECT:
        out['Rebar_QuantityX'], out['Rebar_QuantityY'] = max(0, nb - 2), max(0, nh - 2)
    else:
        out['Rebar_QuantityX'], out['Rebar_QuantityY'] = nb, nh
    have = set()
    for name, kind, d in slot_names(shape):         # every slot off, somewhere harmless
        have.add(name)
        out[name + '_Vis'] = 0
        if kind == 'tie':
            out[name + ('_X' if d == 'V' else '_Y')] = (b if d == 'V' else h) / 2.0
            out[name + '_Alt'] = 0
        elif kind == 'hoopt':
            out[name + '_X'], out[name + '_Y'] = b / 2.0 - 50, h - cr - 100
            out[name + '_A'], out[name + '_B'] = 100.0, 100.0
        elif kind == 'hoop':
            out[name + ('_X' if d == 'V' else '_Y')] = (b if d == 'V' else h) / 2.0 - 50
            out[name + '_A'] = 100.0
        else:
            out[name + '_W'], out[name + '_H'] = 200.0, 100.0
            out[name + ('_X' if d in ('B', 'T') else '_Y')] = (b if d in ('B', 'T') else h) / 2.0

    def take(prefix, count, what):
        for i in range(1, count + 1):
            s = '%s%d' % (prefix, i)
            if s in have and not out[s + '_Vis']:
                return s
        raise ValueError('the family has no free slot for %s' % what)

    for t in result.get('ties') or []:
        if t.get('kind') == 'v':
            p1, apex, p2 = t['points']
            if t['direction'] == 'vertical':             # apex on the bottom / top face
                s = 'VB' if apex[1] < h / 2.0 else 'VT'
                if s not in have:
                    raise ValueError('the family has no %s slot' % s)
                out[s + '_X'] = _snap(apex[0], xs)
                out[s + '_W'] = abs(_snap(p2[0], xs) - _snap(p1[0], xs))
                out[s + '_H'] = abs(_snap(p1[1], ys) - _snap(apex[1], ys))
            else:                                        # apex on the left / right face
                s = 'VL' if apex[0] < b / 2.0 else 'VR'
                if s not in have:
                    raise ValueError('the family has no %s slot' % s)
                out[s + '_Y'] = _snap(apex[1], ys)
                out[s + '_W'] = abs(_snap(p2[1], ys) - _snap(p1[1], ys))
                out[s + '_H'] = abs(_snap(p1[0], xs) - _snap(apex[0], xs))
            out[s + '_Vis'] = 1
        elif t['direction'] == 'vertical':
            s = take('TieV', N_TIES, 'a tie along h')
            out[s + '_Vis'], out[s + '_X'] = 1, _snap(t['at'], xs)
            out[s + '_Alt'] = 1 if t.get('alt') else 0
        else:
            s = take('TieH', N_TIES, 'a tie along b')
            out[s + '_Vis'], out[s + '_Y'] = 1, _snap(t['at'], ys)
            out[s + '_Alt'] = 1 if t.get('alt') else 0
    for hp in result.get('hoops') or []:
        if hp['kind'] != 'rect':
            continue
        x0, y0, x1, y1 = hp['box']
        if hp['direction'] == 'flat':                   # ROUND1 flat end
            s = take('HoopT', 2, 'an inner hoop at the flat end')
            a, c = _snap(x0, xs), _snap(x1, xs)
            yb, yt = _snap(y0, ys), h - cr
            out[s + '_Vis'], out[s + '_X'], out[s + '_Y'] = 1, a, yb
            out[s + '_A'], out[s + '_B'] = c - a, yt - yb
        elif hp['direction'] == 'vertical':
            s = take('HoopV', N_HOOPS, 'an inner hoop along h')
            a, c = _snap(x0, xs), _snap(x1, xs)
            out[s + '_Vis'], out[s + '_X'], out[s + '_A'] = 1, a, c - a
        else:
            s = take('HoopH', N_HOOPS, 'an inner hoop along b')
            a, c = _snap(y0, ys), _snap(y1, ys)
            out[s + '_Vis'], out[s + '_Y'], out[s + '_A'] = 1, a, c - a
    return out
