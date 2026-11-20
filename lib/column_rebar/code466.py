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
# Rounded shapes of the Create Column families (b = short side = diameter of
# the rounded end, h = long side; the round ends are at y = 0 / y = h):
#   ROUND2  both ends half circles;  ROUND1  bottom end half circle, top end flat
# Bars as in the families' legend: nb = bars on each rounded / flat end WITHOUT
# the side bars, nh = bars on each long side WITH the end bars of the side.
ROUND1, ROUND2 = 'ROUND1', 'ROUND2'       # ROUND1: round end at the BOTTOM (as the family)
ROUNDED = (ROUND1, ROUND2)
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
MIN_BARS = {RECT: 4, CIRCLE: 6, ROUND1: 4, ROUND2: 4}
RHO_MIN, RHO_REDUCED, RHO_MAX = 0.008, 0.004, 0.04
CLEAR_GAP_MIN = 35.0            # aggregate size unknown -> 4/3 * 26 ~ 35 (guide, 3)
UNRESTRAINED_MAX = 150.0        # unrestrained bar to the nearest restrained one, axes
RESTRAINED_MAX = 300.0          # between neighbouring restrained bars, axes
STIRRUP_DIA_MIN = 6.0
STIRRUP_SERIES = (8.0, 10.0, 12.0, 14.0, 16.0)
SPACING_MAX = 250.0
SPACING_BAR_FACTOR = 16.0
DENSE_FACTOR, DENSE_MAX = 0.6, 100.0
# office default when the column has no spacing: 200 / 100 (user, 20.11.2026);
# smaller only when SI 466 asks for it
DEFAULT_SPACING, DEFAULT_DENSE = 200.0, 100.0
SPACING_ROUND = 25.0
WALL_RATIO, WALL_LONG_SIDE = 4.0, 800.0

# How restrained inner bars are held (466-2 28.6.2 allows closed or open
# stirrups; the choice is office practice, user 2026-11-20):
#   AUTO   column (long / short <= PYLON_RATIO): ALWAYS (user 2026-11-20) neighbouring restrained bars of
#          a face are paired into inner closed hoops (two ties -> one hoop);
#          pylon: ties across the short dimension; the middle bar of a short
#          face is held by a V-shaped tie to the long faces + a straight tie
#          between its ends, instead of a long tie (user sketch 2026-11-20).
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


def restrain_side(pos, forced=()):
    """Indices of restrained bars on a side: the corners and as few of the
    others as the 150 / 300 rule allows, symmetric about the middle.
    forced: bars held anyway (the ends of a V-shaped tie).
    None when the rule cannot be met (bars too far apart even if all tied)."""
    n = len(pos)
    if not _valid(pos, range(n)):
        return None
    if n <= 2:
        return list(range(n))
    forced = set(k for k in forced if 0 < k < n - 1)
    # the fewest ties that pass; of equal ones the symmetric, then the
    # one closest to the middle (ties do not have to be symmetric, bars do)
    inner = [k for k in range(1, n - 1) if k not in forced]
    if len(inner) <= 14:
        best, best_key = None, None
        for mask in range(1 << len(inner)):
            chosen = [0, n - 1] + sorted(forced) + [k for b, k in enumerate(inner) if mask >> b & 1]
            sym = set(chosen) == set(n - 1 - k for k in chosen)
            key = (len(chosen), not sym, sum(abs(k - (n - 1) / 2.0) for k in chosen))
            if best_key is not None and key >= best_key:
                continue
            if _valid(pos, chosen):
                best, best_key = chosen, key
        return sorted(best)
    chosen, i = [0] + sorted(forced), 0           # long sides: greedy, then made symmetric
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
    """Ties (straight and V-shaped) and inner hoops of a RECT section (see AUTO).

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
        if out.get('_v') and out['_v'][0] == direction:
            _v_ties(out, direction, pos, other, out['_v'][1], corner, dw, dl, b, h)
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
            out['ties'].append({'kind': 'straight', 'direction': direction, 'at': pos[i], 'dia': dw,
                                'length': tie_cut_length(span, dw)})
        _alternate(out, direction, pos, inner, singles, across - 2.0 * corner, dw)


def _alternate(out, direction, pos, tied, singles, span, dw):
    """A tie whose mirror bar is not held (the 150 / 300 rule needs only one of
    two symmetric bars) is placed in turn - on one bar at one level, on the
    mirror bar at the next (user 2026-11-20): the mirror one is drawn dashed.
    Same tie, so it adds nothing to the count per level."""
    n = len(pos)
    for i in singles:
        k = n - 1 - i
        if k != i and k not in tied:
            out['ties'].append({'kind': 'straight', 'direction': direction, 'at': pos[k], 'dia': dw,
                                'length': tie_cut_length(span, dw), 'alt': True})


def v_base(mid, corner, other):
    """Index on the long faces where a V-shaped tie from the middle bar of a
    short face (at `mid` along it, `corner` from its end) may end: the first
    bar from that end at which the angle of the V is <= 135 degrees.
    None if there is none before the middle of the long face."""
    half = mid - corner
    need = half / math.tan(math.radians(APEX_MAX / 2.0))
    for idx in range(1, len(other) - 1):
        if other[idx] - other[0] >= need - 1e-6:
            return idx if other[idx] < other[-1 - idx] else None
    return None


def v_tie(apex, p1, p2, dw, dl):
    """A V-shaped tie bent round `apex`, hooked on p1 and p2."""
    legs = math.hypot(apex[0] - p1[0], apex[1] - p1[1]) + math.hypot(apex[0] - p2[0], apex[1] - p2[1])
    a1 = math.atan2(p1[1] - apex[1], p1[0] - apex[0])
    a2 = math.atan2(p2[1] - apex[1], p2[0] - apex[0])
    ang = abs(math.degrees(a1 - a2))
    ang = 360.0 - ang if ang > 180.0 else ang
    return {'kind': 'v', 'points': [p1, apex, p2], 'apex_angle': ang, 'dia': dw,
            'length': legs + math.pi * (dl + dw) / 2.0 + TIE_HOOKS * dw}


def _v_ties(out, direction, pos, other, k, corner, dw, dl, b, h):
    """V-shaped ties holding the middle bar of both short faces (user sketch
    2026-11-20, pylon): apex on the middle bar, ends on bar k of the long faces
    from that end; the straight tie between those two bars comes from the long
    faces (bar k is forced restrained there)."""
    mid = pos[len(pos) // 2]
    n = len(other)
    for kk, end in ((k, other[0]), (n - 1 - k, other[-1])):
        x = other[kk]
        if direction == HORIZONTAL:             # short faces are left / right
            t = v_tie((end, mid), (x, corner), (x, h - corner), dw, dl)
        else:                                   # short faces are bottom / top
            t = v_tie((mid, end), (corner, x), (b - corner, x), dw, dl)
        t['direction'] = direction
        out['ties'].append(t)


def _rounded(out, shape, b, h, cover, dw, dl, ne, ns, mode):
    """Bars and transverse reinforcement of ROUND1 / ROUND2 (see ROUNDED).

    Rule (to be confirmed by the user, 2026-11-20):
    - the stirrup follows the outline; bars on a rounded end, and the side bars
      where the side meets it, are held by the curved stirrup (as in a round
      column) - along the arc at most 300 between bars;
    - the inner bars of the long sides follow the 150 / 300 rule and are held
      across b like a RECT column: inner hoops in pairs (column) or ties (pylon);
    - ROUND1 flat end: corners held by the stirrup; a middle bar that needs it -
      a V-shaped tie to the side bars + a straight tie between them; more than one - by hand (yellow)."""
    m = out['messages']
    R = b / 2.0
    off = bar_offset(cover, dw, dl)
    r = R - off
    corner = corner_offset(cover, dw, dl)
    need = max(CLEAR_GAP_MIN, dl)
    if ns < 2 or r <= dl:
        return
    two = shape == ROUND2
    y_top = h - R                                   # centre of the top half circle
    y_bot = R if two else corner
    if y_top <= y_bot:
        m.append(msg(RED, 'round_sides', u'The section is too short for its rounded ends.',
                     u'geometry'))
        return
    ys = [y_bot + (y_top - y_bot) * i / (ns - 1.0) for i in range(ns)]
    xl, xr = R - r, R + r
    bars, flags = [], []

    # ROUND1 flat end: which bars need holding; a middle one -> V-shaped tie to
    # the side bars at index kv (forced restrained there, plus a straight tie)
    # 2+ bars that need holding: inner hoops on pairs (user 2026-11-20) from the
    # flat end to the first row of side bars; an odd middle one keeps the V-tie
    kv, xs, rf, inner_f, f_pairs, f_mid = None, [], [], [], [], None
    if not two and ne > 0:
        xs = side_positions(b, ne + 2, corner)
        rf = restrain_side(xs)
        inner_f = (rf or [])[1:-1]
        f_pairs, f_single = pair_up(inner_f) if len(inner_f) >= 2 else ([], inner_f)
        if len(f_single) == 1 and ne % 2 == 1 and f_single[0] == (ne + 1) // 2:
            f_mid = f_single[0]
            need_y = (xs[f_mid] - xl) / math.tan(math.radians(APEX_MAX / 2.0))
            kv = next((i for i in range(1, ns - 1) if ys[i] - ys[0] >= need_y - 1e-6), None)
        f_left = [i for i in f_single if i != f_mid or kv is None]

    # long sides
    rs = restrain_side(ys, (kv,) if kv is not None else ())
    ok, _ = _side_gap_ok(ys, dl)
    if not ok:
        gap = min(q - p for p, q in zip(ys, ys[1:])) - dl
        m.append(msg(RED, 'gap', u'Along the long sides bars are %d mm apart in the clear, '
                     u'at least %d. Take fewer or thinner bars.' % (round(gap), need), CL_GAP, u'h'))
    if rs is None:
        step = max(q - p for p, q in zip(ys, ys[1:]))
        m.append(msg(RED, 'restrained', u'Along the long sides bars are %d mm apart, at most %d '
                     u'even when every bar is tied. Add a bar on the long sides.'
                     % (round(step), RESTRAINED_MAX), CL_RESTRAINT, u'h'))
    for side_x, corner_x in ((xl, corner), (xr, b - corner)):
        for i, y in enumerate(ys):
            x = corner_x if (not two and i == 0) else side_x
            bars.append((x, y))
            flags.append(i in (0, ns - 1) or (rs is not None and i in rs))

    # rounded ends: bars between the tangent points, all held by the curved stirrup
    arcs = [(y_top, 0.0)] + ([(R, math.pi)] if two else [])
    dth = math.pi / (ne + 1.0)
    for yc, start in arcs:
        for k in range(1, ne + 1):
            th = start + k * dth
            bars.append((R + r * math.cos(th), yc + r * math.sin(th)))
            flags.append(True)
    chord = 2.0 * r * math.sin(dth / 2.0)
    if chord - dl < need - 1e-6:
        m.append(msg(RED, 'gap', u'On the rounded end bars are %d mm apart in the clear, at least %d. '
                     u'Take fewer bars on the end.' % (round(chord - dl), need), CL_GAP, u'b'))
    if r * dth > RESTRAINED_MAX + 1e-6:
        m.append(msg(RED, 'restrained', u'On the rounded end bars are %d mm apart along the arc, '
                     u'at most %d. Add bars on the end.' % (round(r * dth), RESTRAINED_MAX),
                     CL_BARS, u'b'))

    # ROUND1 flat end
    if xs:
        for x in xs[1:-1]:
            bars.append((x, corner))
        flags.extend([i in (rf or []) for i in range(1, ne + 1)])
        ok, _ = _side_gap_ok(xs, dl)
        if not ok:
            m.append(msg(RED, 'gap', u'Along the flat end bars are %d mm apart in the clear, at least %d.'
                         % (round(xs[1] - xs[0] - dl), need), CL_GAP, u'b'))
        if rf is None:
            m.append(msg(RED, 'restrained', u'Along the flat end bars are %d mm apart, at most %d. '
                         u'Add a bar on the flat end.' % (round(xs[1] - xs[0]), RESTRAINED_MAX),
                         CL_RESTRAINT, u'b'))
        else:
            if kv is not None:
                t = v_tie((xs[f_mid], corner), (xl, ys[kv]), (xr, ys[kv]), dw, dl)
                t['direction'] = VERTICAL
                out['ties'].append(t)
            y_row = ys[1] if ns > 2 else ys[-1]
            for i, j in f_pairs:
                w = xs[j] - xs[i] + dl + 2.0 * dw
                d = y_row - corner + dl + 2.0 * dw
                out['hoops'].append({'kind': 'rect', 'direction': 'flat', 'bars': (i, j),
                                     'box': (xs[i], corner, xs[j], y_row), 'a': w, 'b': d, 'dia': dw,
                                     'length': 2.0 * (w + d) + HOOP_HOOKS * dw})
            if f_left:
                m.append(msg(YELLOW, 'flat_end', u'%d bar(s) of the flat end need holding; hold them by hand.'
                             % len(f_left), CL_STIRRUP, u'b'))
    out['bars'], out['restrained'] = bars, flags

    # inner bars of the long sides: across b; the end of a V-shaped tie keeps a straight tie
    inner = [i for i in (rs or [])[1:-1] if i != kv]
    pylon = h / float(b) > PYLON_RATIO
    if mode == HOOPS or (mode != TIES and not pylon):
        pairs, singles = pair_up(inner) if len(inner) >= 2 else ([], inner)
    else:
        pairs, singles = [], inner
    if kv is not None:
        singles = sorted(singles + [kv])
    for i, j in pairs:
        w = ys[j] - ys[i] + dl + 2.0 * dw
        out['hoops'].append({'kind': 'rect', 'direction': HORIZONTAL, 'bars': (i, j),
                             'box': (xl, ys[i], xr, ys[j]), 'a': w, 'b': b - 2.0 * cover,
                             'dia': dw, 'length': 2.0 * (w + b - 2.0 * cover) + HOOP_HOOKS * dw})
    for i in singles:
        out['ties'].append({'kind': 'straight', 'direction': HORIZONTAL, 'at': ys[i], 'dia': dw,
                            'length': tie_cut_length(xr - xl, dw)})
    if two:      # ROUND1 is not symmetric along h: its ties are not alternated
        _alternate(out, HORIZONTAL, ys, inner, singles, xr - xl, dw)
    if not two:
        _mirror_y(out, h)


def _mirror_y(out, h):
    """ROUND1 is worked out with the round end on top; the family has it at the
    bottom (flat end on top) - mirror every y."""
    out['bars'] = [(x, h - y) for x, y in out['bars']]
    for t in out['ties']:
        if t.get('kind') == 'v':
            t['points'] = [(x, h - y) for x, y in t['points']]
        elif t['direction'] == HORIZONTAL:
            t['at'] = h - t['at']
    for hp in out['hoops']:
        if hp['kind'] == 'rect':
            x0, y0, x1, y1 = hp['box']
            hp['box'] = (x0, h - y1, x1, h - y0)


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
    elif shape in ROUNDED:
        ends = 2 if shape == ROUND2 else 1
        ac = b * h - ends * (2.0 - math.pi / 2.0) * (b / 2.0) ** 2
        short, long_ = b, h
        n = 2 * nb + 2 * nh
        if h < b:
            m.append(msg(RED, 'round_sides', u'For a rounded column give b as the short side '
                         u'(diameter of the round end) and h as the long one.', u'geometry'))
            return out
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
    if shape == CIRCLE:
        per = math.pi * sa
    elif shape == ROUND2:
        per = 2.0 * (sb - sa) + math.pi * sa
    elif shape == ROUND1:
        per = 2.0 * (sb - sa / 2.0) + sa + math.pi * sa / 2.0
    else:
        per = 2.0 * (sa + sb)
    out['stirrup'] = {'shape': shape, 'dia': stirrup_dia, 'a': sa, 'b': sb,
                      'length': per + HOOP_HOOKS * stirrup_dia}

    if shape in ROUNDED:
        _rounded(out, shape, b, h, cover, stirrup_dia, bar_dia, nb, nh, transverse)
        out['set_length'] = (out['stirrup']['length'] + sum(t['length'] for t in out['ties'] if not t.get('alt'))
                             + sum(x['length'] for x in out['hoops']))
    elif shape == CIRCLE:
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
        # pylon, AUTO: the middle bar of a short face by a V-shaped tie + a straight one
        if (transverse or AUTO) == AUTO and long_ / float(short) > PYLON_RATIO:
            if b < h:      # short faces bottom / top, their ties would run along h
                sp, sr, lp, sdir = pb, rb, ph, VERTICAL
            else:
                sp, sr, lp, sdir = ph, rh, pb, HORIZONTAL
            inner_s = (sr or [])[1:-1]
            if len(inner_s) == 1 and len(sp) % 2 == 1 and inner_s[0] == len(sp) // 2:
                k = v_base(sp[len(sp) // 2], sp[0], lp)
                if k is not None:
                    forced = (k, len(lp) - 1 - k)
                    if sdir == VERTICAL:
                        rh = restrain_side(ph, forced)
                    else:
                        rb = restrain_side(pb, forced)
                    out['_v'] = (sdir, k)
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
        out.pop('_v', None)
        out['set_length'] = (out['stirrup']['length'] + sum(t['length'] for t in out['ties'] if not t.get('alt'))
                             + sum(x['length'] for x in out['hoops']))

    # 5. spacing along the column
    s_max = main_spacing(short, bar_dia) if bar_dia else floor_to(min(short, SPACING_MAX))
    s = min(s_max, DEFAULT_SPACING) if spacing is None else float(spacing)
    if s > min(short, SPACING_BAR_FACTOR * bar_dia, SPACING_MAX) + 1e-6:
        m.append(msg(RED, 'spacing', u'Stirrups every %d mm, at most %d here '
                     u'(smaller side, 16 bar diameters, 250).' % (s, s_max), CL_STIRRUP))
    s1_max = dense_spacing(s)
    s1 = min(s1_max, DEFAULT_DENSE) if dense is None else float(dense)
    if s1 > min(DENSE_FACTOR * s, DENSE_MAX) + 1e-6:
        m.append(msg(RED, 'dense', u'Dense stirrups every %d mm, at most %d at joints and laps.'
                     % (s1, s1_max), CL_DENSE))
    out['spacing'], out['dense'] = s, s1
    out['label'] = spacing_label(stirrup_dia, s, s1)
    return out


def summary(result):
    """Text for Rebar_Stirrup Label: 'D8@250/100; 2 inner hoops + 1 tie'."""
    if not result.get('label'):
        return u''
    parts = []
    rect = len([x for x in result.get('hoops') or [] if x['kind'] == 'rect'])
    tl = result.get('ties') or []
    vt = len([x for x in tl if x.get('kind') == 'v'])
    alt = len([x for x in tl if x.get('alt')])
    ties = len(tl) - vt - alt
    for n, one, many in ((rect, u'inner hoop', u'inner hoops'), (vt, u'V-tie', u'V-ties'),
                         (ties, u'tie', u'ties')):
        if n:
            parts.append(u'%d %s' % (n, one if n == 1 else many))
    if alt:
        parts[-1] += u' (alternating)'
    return result['label'] + (u'; ' + u' + '.join(parts) if parts else u'')


def mode_from_text(text):
    """Rebar_Transverse value -> AUTO / TIES / HOOPS (empty or unknown -> AUTO)."""
    t = (text or u'').strip().lower()
    if t.startswith(u'tie'):
        return TIES
    if t.startswith(u'hoop'):
        return HOOPS
    return AUTO


def blocked(result):
    """True when the drawing may not be issued (a RED message)."""
    return any(x['level'] == RED for x in result['messages'])


def from_old_counts(qb, qh):
    """Old legend (bars of one side without the 4 corners) -> counts with corners."""
    return int(qb) + 2, int(qh) + 2
