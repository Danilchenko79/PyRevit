# -*- coding: utf-8 -*-
"""code466.design() result -> parameters of the 'PEER_Column Section' family
(slots, see family_section.py). Pure Python, millimetres; the Revit side only
converts units and sets the values.

The family places the bars itself, evenly between the corner bars at CoverR
= cover + stirrup + bar / 2 from the faces; code466 puts the corner bar a
little deeper (in the bend of the stirrup). Slot positions are therefore
snapped to the bar of the family's own layout.
"""

N_TIES, N_HOOPS = 8, 4
V_SLOTS = ('VB', 'VT', 'VL', 'VR')


def family_bars(side, n, cover_r):
    """Bar axes along a side as the family draws them."""
    if n < 2:
        return []
    return [cover_r + (side - 2.0 * cover_r) * i / (n - 1.0) for i in range(n)]


def _snap(v, pos):
    return min(pos, key=lambda p: abs(p - v)) if pos else v


def params(result, b, h, cover, bar_dia, nb, nh):
    """{family parameter: value} for a RECT result. Lengths in mm; yes/no and
    counts as int. nb / nh = bars along b / along h with the corners.
    Raises ValueError when the result needs more slots than the family has."""
    st = result['stirrup']
    dw = st['dia'] if st else 8.0
    cr = cover + dw + bar_dia / 2.0
    xs = family_bars(b, nb, cr)
    ys = family_bars(h, nh, cr)
    out = {
        'PR_Dimension_Width': float(b), 'PR_Dimension_Height': float(h),
        'Cover': float(cover), 'Rebar_Diameter': float(bar_dia), 'Stirrup_Diameter': float(dw),
        'Rebar_QuantityX': max(0, nb - 2), 'Rebar_QuantityY': max(0, nh - 2),
    }
    # every slot off, at a harmless place inside the section
    for i in range(1, N_TIES + 1):
        out['TieV%d_Vis' % i], out['TieV%d_X' % i] = 0, b / 2.0
        out['TieH%d_Vis' % i], out['TieH%d_Y' % i] = 0, h / 2.0
    for i in range(1, N_HOOPS + 1):
        out['HoopV%d_Vis' % i], out['HoopV%d_X' % i], out['HoopV%d_A' % i] = 0, b / 2.0 - 50, 100.0
        out['HoopH%d_Vis' % i], out['HoopH%d_Y' % i], out['HoopH%d_A' % i] = 0, h / 2.0 - 50, 100.0
    for s in V_SLOTS:
        out[s + '_Vis'], out[s + '_W'], out[s + '_H'] = 0, 200.0, 100.0
        out[s + ('_X' if s in ('VB', 'VT') else '_Y')] = (b if s in ('VB', 'VT') else h) / 2.0

    tv = th = hv = hh = 0
    for t in result.get('ties') or []:
        if t.get('kind') == 'v':
            p1, apex, p2 = t['points']
            if t['direction'] == 'vertical':             # apex on the bottom / top face
                s = 'VB' if apex[1] < h / 2.0 else 'VT'
                out[s + '_X'] = _snap(apex[0], xs)
                out[s + '_W'] = abs(_snap(p2[0], xs) - _snap(p1[0], xs))
                out[s + '_H'] = abs(_snap(p1[1], ys) - _snap(apex[1], ys))
            else:                                        # apex on the left / right face
                s = 'VL' if apex[0] < b / 2.0 else 'VR'
                out[s + '_Y'] = _snap(apex[1], ys)
                out[s + '_W'] = abs(_snap(p2[1], ys) - _snap(p1[1], ys))
                out[s + '_H'] = abs(_snap(p1[0], xs) - _snap(apex[0], xs))
            out[s + '_Vis'] = 1
        elif t['direction'] == 'vertical':
            tv += 1
            if tv > N_TIES:
                raise ValueError('more than %d ties along h' % N_TIES)
            out['TieV%d_Vis' % tv], out['TieV%d_X' % tv] = 1, _snap(t['at'], xs)
        else:
            th += 1
            if th > N_TIES:
                raise ValueError('more than %d ties along b' % N_TIES)
            out['TieH%d_Vis' % th], out['TieH%d_Y' % th] = 1, _snap(t['at'], ys)
    for hp in result.get('hoops') or []:
        if hp['kind'] != 'rect':
            continue
        x0, y0, x1, y1 = hp['box']
        if hp['direction'] == 'vertical':
            hv += 1
            if hv > N_HOOPS:
                raise ValueError('more than %d inner hoops along h' % N_HOOPS)
            a, c = _snap(x0, xs), _snap(x1, xs)
            out['HoopV%d_Vis' % hv], out['HoopV%d_X' % hv], out['HoopV%d_A' % hv] = 1, a, c - a
        else:
            hh += 1
            if hh > N_HOOPS:
                raise ValueError('more than %d inner hoops along b' % N_HOOPS)
            a, c = _snap(y0, ys), _snap(y1, ys)
            out['HoopH%d_Vis' % hh], out['HoopH%d_Y' % hh], out['HoopH%d_A' % hh] = 1, a, c - a
    return out
