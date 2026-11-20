# -*- coding: utf-8 -*-
"""Column section by SI 466 (non-seismic). Pure Python, millimetres.

Source: the office guide "Column reinforcement by SI 466 / SI 413 - guide
and checklist" (2026-11-20), which cites
    SI 466-2 (2015) 28.6.1, 28.6.2, fig. 28.7   - longitudinal bars, stirrups
    SI 466-1 (2022) 7.2, 7.3, 7.7               - bends, clear gaps, ties
Every number below says which clause it stands for (CLAUSE_*).

Input is what the user gives (guide, section 2): shape and size, cover to
the stirrup, bar diameter, bars along b and along h (corners counted in
both), stirrup diameter (optional, else the smallest allowed).
design() returns the section: bar coordinates, which bars are restrained,
stirrup, ties, the spacing label 'D8@250/100' and the messages.

Messages: level RED (the drawing may not be issued) or YELLOW (check it,
issue allowed); text in plain words with what to do; clause separately.

Origin: bottom left corner of the concrete, x along b, y along h.
"""

import math

RECT, CIRCLE = 'RECT', 'CIRCLE'
RED, YELLOW = 'red', 'yellow'
VERTICAL, HORIZONTAL = 'vertical', 'horizontal'

CL_BARS = u'466-2, 28.6.1'
CL_RESTRAINT = u'466-2, 28.6.1, fig. 28.7(b)'
CL_STIRRUP = u'466-2, 28.6.2'
CL_DENSE = u'466-2, 28.6.2, fig. 28.7(d)'
CL_GAP = u'466-1, 7.3'
CL_BEND = u'466-1, 7.2'
CL_TIE = u'466-1, 7.7.2'
CL_WALL = u'466-2, 29.1'
CL_OFFICE = u'office practice'

MIN_BAR_DIA = 12.0
MIN_BARS = {RECT: 4, CIRCLE: 6}
RHO_MIN, RHO_REDUCED, RHO_MAX = 0.008, 0.004, 0.04
CLEAR_GAP_MIN = 35.0            # aggregate size unknown -> 4/3 * 26 ~ 35 (guide, 3)
UNRESTRAINED_MAX = 150.0        # unrestrained bar to the nearest restrained one, axes
RESTRAINED_MAX = 300.0          # between neighbouring restrained bars, axes
STIRRUP_DIA_MIN = 6.0
STIRRUP_SERIES = (8.0, 10.0, 12.0, 14.0, 16.0)
SPACING_MAX = 250.0
SPACING_BAR_FACTOR = 16.0
DENSE_FACTOR, DENSE_MAX = 0.6, 100.0
SPACING_ROUND = 25.0
WALL_RATIO, WALL_LONG_SIDE = 4.0, 800.0

# How restrained inner bars are held (466-2 28.6.2 allows closed or open
# stirrups; the choice is office practice, user 2026-11-20):
#   AUTO   column (long / short <= PYLON_RATIO): ALWAYS (user 2026-11-20) neighbouring restrained bars of
#          a face are paired into inner closed hoops (two ties -> one hoop);
#          pylon: ties across the short dimension; the middle bar of a short
#          face is held by a triangular hoop instead of a long tie.
#   TIES   ties only.   HOOPS  inner hoops wherever two bars can be paired.
AUTO, TIES, HOOPS = 'auto', 'ties', 'hoops'
PYLON_RATIO = 2.0               # office rule, to be confirmed
APEX_MAX = 135.0                # angle of a hoop at a restrained bar, 466-2 28.6.2
TIE_HOOKS = 20.0                # both 135 deg hooks of a tie, in tie diameters   [estimate]
HOOP_HOOKS = 20.0               # hooks of a closed hoop (Shape 52: + 20 D)


def msg(level, code, text, clause, where=None):
    """where: 'b' / 'h' - the side of the section the message is about."""
    return {'level': level, 'code': code, 'text': text, 'clause': clause, 'where': where}


def mandrel(dia):
    """Bend mandrel diameter: 4D below 20 mm, 7D from 20.   [466-1 7.2, check table 7.1]"""
    return (4.0 if dia < 20.0 else 7.0) * dia


def stirrup_dia_min(bar_dia):
    """max(6, D/4) rounded up to the series 8, 10, 12...    [466-2 28.6.2 + guide, 6.3]"""
    need = max(STIRRUP_DIA_MIN, bar_dia / 4.0)
    for d in STIRRUP_SERIES:
        if d >= need - 1e-9:
            return d
    return STIRRUP_SERIES[-1]


def floor_to(value, step=SPACING_ROUND):
    return math.floor(value / step + 1e-9) * step


def main_spacing(short_side, bar_dia):
    """S = min(b_c, 16 D, 250), down to 25.                 [466-2 28.6.2]"""
    return floor_to(min(short_side, SPACING_BAR_FACTOR * bar_dia, SPACING_MAX))


def dense_spacing(s):
    """S1 = min(0.6 S, 100), down to 25: joints and laps.   [466-2 28.6.2]"""
    return floor_to(min(DENSE_FACTOR * s, DENSE_MAX))


def spacing_label(stirrup_dia, s, s1):
    return u'Ø%d@%d/%d' % (int(round(stirrup_dia)), int(round(s)), int(round(s1)))


def bar_offset(cover, stirrup_dia, bar_dia):
    """Axis of a side bar from the concrete face: c + Dw + D/2."""
    return cover + stirrup_dia + bar_dia / 2.0


def corner_offset(cover, stirrup_dia, bar_dia):
    """Axis of a corner bar from both faces: the bar sits in the bend arc.

    Inner bend radius r = mandrel / 2. A bar thinner than the arc touches
    the arc on the diagonal; a thicker one touches the straight legs."""
    r = mandrel(stirrup_dia) / 2.0
    inside = cover + stirrup_dia
    if r <= bar_dia / 2.0:
        return inside + bar_dia / 2.0
    return inside + r - (r - bar_dia / 2.0) / math.sqrt(2.0)


def side_positions(length, n, corner):
    """Bar axes along one side: corners at `corner` from both ends, the
    rest evenly between."""
    if n < 2:
        return [length / 2.0] if n == 1 else []
    a, b = corner, length - corner
    return [a + (b - a) * i / (n - 1.0) for i in range(n)]


def _valid(pos, chosen):
    """Restraint rules on one side for the restrained indices `chosen`."""
    chosen = sorted(chosen)
    for i, j in zip(chosen, chosen[1:]):
        if pos[j] - pos[i] > RESTRAINED_MAX + 1e-6:
            return False
        for k in range(i + 1, j):
            if min(pos[k] - pos[i], pos[j] - pos[k]) > UNRESTRAINED_MAX + 1e-6:
                return False
    return True


def restrain_side(pos):
    """Indices of restrained bars on a side: the corners and as few of the
    others as the 150 / 300 rule allows, symmetric about the middle.
    None when the rule cannot be met (bars too far apart even if all tied)."""
    n = len(pos)
    if not _valid(pos, range(n)):
        return None
    if n <= 2:
        return list(range(n))
    # the fewest ties that pass; of equal ones the symmetric, then the
    # one closest to the middle (ties do not have to be symmetric, bars do)
    inner = list(range(1, n - 1))
    if len(inner) <= 14:
        best, best_key = None, None
        for mask in range(1 << len(inner)):
            chosen = [0, n - 1] + [k for b, k in enumerate(inner) if mask >> b & 1]
            sym = set(chosen) == set(n - 1 - k for k in chosen)
            key = (len(chosen), not sym, sum(abs(k - (n - 1) / 2.0) for k in chosen))
            if best_key is not None and key >= best_key:
                continue
            if _valid(pos, chosen):
                best, best_key = chosen, key
        return sorted(best)
    chosen, i = [0], 0           # long sides: greedy, then made symmetric
    while i < n - 1:
        j = n - 1
        while j > i + 1 and not _valid(pos, [i, j]):
            j -= 1
        chosen.append(j)
        i = j
    mirror = set(n - 1 - k for k in chosen)
    if mirror != set(chosen):
        chosen = sorted(set(chosen) | mirror)
    return sorted(chosen)


def _side_gap_ok(pos, bar_dia):
    need = max(CLEAR_GAP_MIN, bar_dia)
    return all(b - a - bar_dia >= need - 1e-6 for a, b in zip(pos, pos[1:])), need


def pair_up(idx):
    """Restrained inner bars of one face -> (pairs for inner hoops, single ties).
    Neighbours are paired from both ends inwards, so the result stays
    symmetric; an odd one in the middle keeps a tie; of three, the outer two
    share a hoop and the middle one keeps a tie."""
    idx = sorted(idx)
    pairs, singles = [], []
    while len(idx) >= 4:
        pairs.append((idx[0], idx[1]))
        pairs.append((idx[-2], idx[-1]))
        idx = idx[2:-2]
    if len(idx) == 3:
        pairs.append((idx[0], idx[2]))
        singles.append(idx[1])
    elif len(idx) == 2:
        pairs.append((idx[0], idx[1]))
    elif len(idx) == 1:
        singles.append(idx[0])
    return sorted(pairs), singles


def tie_cut_length(span, dia):
    """Tie between bar axes `span` apart: hooks round the bars.   [estimate]"""
    return span + TIE_HOOKS * dia


def _transverse(out, mode, b, h, cover, dw, dl, corner, pb, ph, rb, rh):
    """Ties, inner hoops and triangles of a RECT section (see TRANSVERSE_*).

    VERTICAL ties run along h and hold the inner bars of the b faces
    (bottom / top); HORIZONTAL ties run along b and hold the h faces."""
    out['ties'], out['hoops'] = [], []
    if mode not in (AUTO, TIES, HOOPS):
        mode = AUTO
    short, long_ = min(b, h), max(b, h)
    pylon = long_ / float(short) > PYLON_RATIO
    out['transverse'] = mode
    sa, sb = b - 2.0 * cover, h - 2.0 * cover
    faces = (
        # direction, positions, restrained, across (tie runs this long), other face positions
        (VERTICAL, pb, rb, h, ph),
        (HORIZONTAL, ph, rh, b, pb),
    )
    for direction, pos, restr, across, other in faces:
        inner = [i for i in (restr or [])[1:-1]]
        if not inner:
            continue
        long_ties = across == long_ and pylon            # a tie along the pylon
        use_hoops = mode == HOOPS or (mode == AUTO and not pylon)
        triangle = (mode == AUTO and long_ties and len(inner) == 1
                    and len(pos) % 2 == 1 and inner[0] == len(pos) // 2)
        if triangle:
            if _triangles(out, direction, pos, other, corner, b, h, dw, dl):
                continue
        if use_hoops and len(inner) >= 2:
            pairs, singles = pair_up(inner)
        else:
            pairs, singles = [], inner
        for i, j in pairs:
            w = pos[j] - pos[i] + dl + 2.0 * dw                   # outer, across the face
            d = sb if direction == VERTICAL else sa               # outer, like the perimeter
            if direction == VERTICAL:
                box = (pos[i], corner, pos[j], h - corner)
            else:
                box = (corner, pos[i], b - corner, pos[j])
            out['hoops'].append({'kind': 'rect', 'direction': direction, 'bars': (i, j),
                                 'box': box, 'a': w, 'b': d, 'dia': dw,
                                 'length': 2.0 * (w + d) + HOOP_HOOKS * dw})
        for i in singles:
            span = across - 2.0 * corner
            out['ties'].append({'direction': direction, 'at': pos[i], 'dia': dw,
                                'length': tie_cut_length(span, dw)})
    # a triangle leg on a long face replaces the tie at the same bar
    legs = set((x['leg_direction'], round(x['leg_at'], 3)) for x in out['hoops']
               if x['kind'] == 'triangle')
    out['ties'] = [t for t in out['ties'] if (t['direction'], round(t['at'], 3)) not in legs]


def _triangles(out, direction, pos, other, corner, b, h, dw, dl):
    """Triangular hoops holding the middle bar of the two short faces: apex on
    the middle bar, the other two corners on the nearest bars of the long
    faces at which the angle at the apex is <= 135 degrees.  False if none."""
    mid = pos[len(pos) // 2]                    # along the short face
    half = mid - corner
    need = half / math.tan(math.radians(APEX_MAX / 2.0))
    k = None
    for idx in range(1, len(other) - 1):        # bars of the long faces, from the end
        if other[idx] - corner >= need - 1e-6:
            k = idx
            break
    if k is None or other[k] >= other[-1 - k]:
        return False
    for kk, end in ((k, corner), (len(other) - 1 - k, None)):
        x = other[kk]
        apex_x = corner if end is not None else other[-1]
        angle = 2.0 * math.degrees(math.atan2(half, abs(x - apex_x)))
        if direction == HORIZONTAL:             # short faces are left / right
            pts = [(apex_x, mid), (x, corner), (x, h - corner)]
            leg_dir = VERTICAL
        else:                                   # short faces are bottom / top
            pts = [(mid, apex_x), (corner, x), (b - corner, x)]
            leg_dir = HORIZONTAL
        per = sum(math.hypot(p[0] - q[0], p[1] - q[1])
                  for p, q in zip(pts, pts[1:] + pts[:1]))
        out['hoops'].append({'kind': 'triangle', 'points': pts, 'dia': dw,
                             'apex_angle': angle, 'leg_direction': leg_dir, 'leg_at': x,
                             'length': per + math.pi * (dl + dw) + HOOP_HOOKS * dw})
    return True


def design(shape, b, h, cover, bar_dia, nb, nh=None, stirrup_dia=None,
           spacing=None, dense=None, transverse=None):
    """Section by the guide. RECT: nb / nh = bars along b / along h, corners
    in both. CIRCLE: b = diameter, nb = all bars, nh unused.
    stirrup_dia, spacing, dense: user overrides (checked, not replaced).
    transverse: AUTO (default), TIES or HOOPS - how restrained inner bars
    are held (see TRANSVERSE rule above)."""
    out = {'shape': shape, 'messages': [], 'bars': [], 'restrained': [],
           'stirrup': None, 'ties': [], 'hoops': [], 'spacing': None, 'dense': None,
           'label': None, 'rho': None, 'set_length': None, 'transverse': None}
    transverse = transverse or AUTO
    m = out['messages']
    nb = int(nb or 0)
    nh = int(nh or 0)
    bar_dia = float(bar_dia or 0)

    # 1. geometry
    if shape == CIRCLE:
        ac = math.pi * b * b / 4.0
        short = long_ = b
        n = nb
    else:
        ac = b * h
        short, long_ = min(b, h), max(b, h)
        n = 2 * nb + 2 * nh - 4 if nb >= 2 and nh >= 2 else 0
        if long_ / float(short) > WALL_RATIO and long_ >= WALL_LONG_SIDE:
            m.append(msg(YELLOW, 'wall', u'Sides %d x %d: this is a wall, not a column. '
                         u'Check that the column rules apply.' % (b, h), CL_WALL))

    # 2. longitudinal bars
    if bar_dia < MIN_BAR_DIA:
        m.append(msg(RED, 'bar_dia', u'Bar diameter %d mm, at least %d is needed. '
                     u'Take D%d or larger.' % (bar_dia, MIN_BAR_DIA, MIN_BAR_DIA), CL_BARS))
    if shape == RECT and (nb < 2 or nh < 2):
        m.append(msg(RED, 'bar_count', u'Give at least 2 bars along each side '
                     u'(the corners).', CL_BARS))
    elif n < MIN_BARS[shape]:
        m.append(msg(RED, 'bar_count', u'%d bars, at least %d are needed for this shape. '
                     u'Add bars.' % (n, MIN_BARS[shape]), CL_BARS))
    if ac > 0 and bar_dia > 0 and n > 0:
        rho = n * math.pi * bar_dia ** 2 / 4.0 / ac
        out['rho'] = rho
        pct = rho * 100.0
        if rho < RHO_REDUCED - 1e-12:
            m.append(msg(RED, 'rho_min', u'Reinforcement %.2f%% of the section, at least 0.8%% '
                         u'(0.4%% only with spare section). Add bars or take a larger diameter.'
                         % pct, CL_BARS))
        elif rho < RHO_MIN - 1e-12:
            m.append(msg(YELLOW, 'rho_reduced', u'Reinforcement %.2f%% is below 0.8%%. Allowed '
                         u'only if the section has spare capacity; check it.' % pct, CL_BARS))
        elif rho > RHO_MAX + 1e-12:
            m.append(msg(RED, 'rho_max', u'Reinforcement %.2f%% of the section, at most 4%%. '
                         u'Take fewer or thinner bars, or a larger section.' % pct, CL_BARS))

    # 3. stirrup diameter
    need_w = stirrup_dia_min(bar_dia) if bar_dia else STIRRUP_SERIES[0]
    if stirrup_dia is None:
        stirrup_dia = need_w
    elif stirrup_dia < max(STIRRUP_DIA_MIN, bar_dia / 4.0) - 1e-9:
        m.append(msg(RED, 'stirrup_dia', u'Stirrup D%d is too thin for bars D%d: at least D%d.'
                     % (stirrup_dia, bar_dia, need_w), CL_STIRRUP))
    if bar_dia and stirrup_dia > bar_dia:
        m.append(msg(RED, 'tie_hook', u'Tie D%d is thicker than the bars D%d it has to hold. '
                     u'Take a thinner stirrup or thicker bars.' % (stirrup_dia, bar_dia), CL_TIE))

    # 4. stirrup and coordinates
    sa, sb = (b - 2.0 * cover, b - 2.0 * cover) if shape == CIRCLE else \
             (b - 2.0 * cover, h - 2.0 * cover)
    inner = 2.0 * stirrup_dia + 2.0 * bar_dia
    if sa <= inner or sb <= inner:
        m.append(msg(RED, 'stirrup_fit', u'Cover %d leaves no room for the stirrup and bars. '
                     u'Reduce the cover or enlarge the section.' % cover, u'geometry'))
        return out
    out['stirrup'] = {'shape': shape, 'dia': stirrup_dia, 'a': sa, 'b': sb,
                      'length': (math.pi * sa if shape == CIRCLE else 2.0 * (sa + sb))
                      + HOOP_HOOKS * stirrup_dia}

    if shape == CIRCLE:
        if n < 1:
            return out
        r = b / 2.0 - bar_offset(cover, stirrup_dia, bar_dia)
        out['bars'] = [(b / 2.0 + r * math.cos(2 * math.pi * i / n),
                        b / 2.0 + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        out['restrained'] = [True] * n
        arc = 2 * math.pi * r / n
        chord = 2 * r * math.sin(math.pi / n)
        need = max(CLEAR_GAP_MIN, bar_dia)
        if chord - bar_dia < need - 1e-6:
            m.append(msg(RED, 'gap', u'Bars %d mm apart in the clear, at least %d. '
                         u'Take fewer bars.' % (chord - bar_dia, need), CL_GAP))
        if arc > RESTRAINED_MAX + 1e-6:
            m.append(msg(RED, 'restrained', u'Bars %d mm apart along the ring, at most %d. '
                         u'Add bars.' % (arc, RESTRAINED_MAX), CL_BARS))
    else:
        if nb < 2 or nh < 2:
            return out
        corner = corner_offset(cover, stirrup_dia, bar_dia)
        pb = side_positions(b, nb, corner)      # x of bars on the bottom / top sides
        ph = side_positions(h, nh, corner)      # y of bars on the left / right sides
        bars, flags = [], []
        rb, rh = restrain_side(pb), restrain_side(ph)
        for pos, restr, side, name in ((pb, rb, b, u'b'), (ph, rh, h, u'h')):
            ok, need = _side_gap_ok(pos, bar_dia)
            if not ok:
                gap = min(q - p for p, q in zip(pos, pos[1:])) - bar_dia
                m.append(msg(RED, 'gap', u'Along side %s (%d) bars are %d mm apart in the clear, '
                             u'at least %d. Take fewer or thinner bars.'
                             % (name, side, round(gap), need), CL_GAP, name))
            if restr is None:
                step = max(q - p for p, q in zip(pos, pos[1:]))
                m.append(msg(RED, 'restrained', u'Along side %s (%d) bars are %d mm apart, '
                             u'at most %d even when every bar is tied. Add a bar on this side.'
                             % (name, side, round(step), RESTRAINED_MAX), CL_RESTRAINT, name))
        # bars: bottom side left to right, top side, then the inner bars of left / right
        top = h - corner
        corner_i = (0, len(pb) - 1)             # corners are always held by the stirrup
        for i, x in enumerate(pb):
            bars.append((x, corner))
            flags.append(i in corner_i or (rb is not None and i in rb))
        for i, x in enumerate(pb):
            bars.append((x, top))
            flags.append(i in corner_i or (rb is not None and i in rb))
        for i, y in enumerate(ph[1:-1], 1):
            bars.append((corner, y))
            flags.append(rh is not None and i in rh)
        for i, y in enumerate(ph[1:-1], 1):
            bars.append((b - corner, y))
            flags.append(rh is not None and i in rh)
        out['bars'], out['restrained'] = bars, flags
        _transverse(out, transverse, b, h, cover, stirrup_dia, bar_dia, corner,
                    pb, ph, rb, rh)
        out['set_length'] = (out['stirrup']['length'] + sum(t['length'] for t in out['ties'])
                             + sum(x['length'] for x in out['hoops']))

    # 5. spacing along the column
    s_max = main_spacing(short, bar_dia) if bar_dia else floor_to(min(short, SPACING_MAX))
    s = s_max if spacing is None else float(spacing)
    if s > min(short, SPACING_BAR_FACTOR * bar_dia, SPACING_MAX) + 1e-6:
        m.append(msg(RED, 'spacing', u'Stirrups every %d mm, at most %d here '
                     u'(smaller side, 16 bar diameters, 250).' % (s, s_max), CL_STIRRUP))
    s1_max = dense_spacing(s)
    s1 = s1_max if dense is None else float(dense)
    if s1 > min(DENSE_FACTOR * s, DENSE_MAX) + 1e-6:
        m.append(msg(RED, 'dense', u'Dense stirrups every %d mm, at most %d at joints and laps.'
                     % (s1, s1_max), CL_DENSE))
    out['spacing'], out['dense'] = s, s1
    out['label'] = spacing_label(stirrup_dia, s, s1)
    return out


def blocked(result):
    """True when the drawing may not be issued (a RED message)."""
    return any(x['level'] == RED for x in result['messages'])


def from_old_counts(qb, qh):
    """Old legend (bars of one side without the 4 corners) -> counts with corners."""
    return int(qb) + 2, int(qh) + 2
