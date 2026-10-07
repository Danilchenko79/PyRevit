# -*- coding: utf-8 -*-
"""
Pure-python core for 2D vertical wall reinforcement.
No Revit imports: runs on IronPython 2.7 inside Revit and on CPython for tests.

Input (all lengths in mm, plan coordinates):
    walls    : list of dict(id, p0=(x,y), p1=(x,y), t=thickness, name)
    openings : list of dict(id, wall_id, s0, s1)         s = distance along wall axis from p0
    columns  : list of dict(id, xmin, xmax, ymin, ymax)
Output:
    chains, nodes, piers  (see build())
"""
import math

TOL = 15.0  # mm, geometric tolerance


# ----------------------------------------------------------------------
# small 2D helpers
# ----------------------------------------------------------------------
def _sub(a, b): return (a[0] - b[0], a[1] - b[1])
def _add(a, b): return (a[0] + b[0], a[1] + b[1])
def _mul(a, k): return (a[0] * k, a[1] * k)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1]
def _cross(a, b): return a[0] * b[1] - a[1] * b[0]
def _len(a): return math.sqrt(_dot(a, a))
def _dist(a, b): return _len(_sub(a, b))


class Axis(object):
    """A straight wall axis with thickness."""
    def __init__(self, p0, p1, t):
        self.p0, self.p1, self.t = p0, p1, t
        d = _sub(p1, p0)
        self.L = _len(d)
        self.u = _mul(d, 1.0 / self.L) if self.L else (1.0, 0.0)
        self.n = (-self.u[1], self.u[0])

    def s_of(self, p):
        """signed distance along axis from p0"""
        return _dot(_sub(p, self.p0), self.u)

    def off_of(self, p):
        """signed lateral offset from axis"""
        return _dot(_sub(p, self.p0), self.n)

    def pt(self, s):
        return _add(self.p0, _mul(self.u, s))

    def parallel(self, other):
        return abs(_cross(self.u, other.u)) < 1e-6

    def same_line(self, other):
        return self.parallel(other) and abs(self.off_of(other.p0)) < TOL


# ----------------------------------------------------------------------
# data classes
# ----------------------------------------------------------------------
class Chain(object):
    """One or more collinear walls glued into a single axis."""
    def __init__(self, cid, axis, pieces):
        self.id = cid
        self.axis = axis
        self.pieces = pieces      # list of (s0, s1, t, wall_id) sorted by s0
        self.events = []          # list of Event
        self.piers = []
        self.wall_axes = {}       # wall_id -> Axis стены (проёмы заданы вдоль неё)
        self.openings = []        # [(s0, s1, id)] в координатах цепочки
        self.blocks = []          # доп. события: ветвь узла, целиком закрытая проёмом
        self.lo, self.hi = 0.0, axis.L   # физические торцы (сдвигаются, если узел исчез)

    def t_at(self, s):
        for s0, s1, t, wid in self.pieces:
            if s0 - TOL <= s <= s1 + TOL:
                return t
        if s > self.pieces[-1][1]:
            return self.pieces[-1][2]
        return self.pieces[0][2]

    @property
    def L(self):
        return self.axis.L


class Event(object):
    """Something that blocks a stretch [s0, s1] of a chain axis."""
    def __init__(self, kind, s0, s1, ref=None):
        self.kind = kind          # 'start','end','opening','tee','cross','column','step'
        self.s0, self.s1 = s0, s1
        self.ref = ref            # node / opening id / column id
    def __repr__(self):
        return "%s[%.0f..%.0f]" % (self.kind, self.s0, self.s1)


class Node(object):
    """Junction of walls: L, T or X."""
    def __init__(self, nid, p):
        self.id = nid
        self.p = p
        self.legs = []            # list of dict(chain, dir=+1/-1, t, end=True/False)
    @property
    def kind(self):
        n = len(self.legs)
        return {2: 'L', 3: 'T', 4: 'X'}.get(n, 'N%d' % n)


class Pier(object):
    def __init__(self, chain, s0, s1, ev0, ev1):
        self.chain = chain
        self.s0, self.s1 = s0, s1
        self.ev0, self.ev1 = ev0, ev1     # events bounding the pier
        self.t = chain.t_at((s0 + s1) / 2.0)
    @property
    def L(self):
        return self.s1 - self.s0
    @property
    def p0(self):
        return self.chain.axis.pt(self.s0)
    @property
    def p1(self):
        return self.chain.axis.pt(self.s1)


# ----------------------------------------------------------------------
# geometry: chains, nodes, events, piers
# ----------------------------------------------------------------------
def _make_chains(walls):
    axes = [(w, Axis(w['p0'], w['p1'], w['t'])) for w in walls]
    used = set()
    chains = []
    for i, (w, ax) in enumerate(axes):
        if i in used:
            continue
        group = [i]
        used.add(i)
        changed = True
        while changed:
            changed = False
            for j, (w2, ax2) in enumerate(axes):
                if j in used or not ax.same_line(ax2):
                    continue
                # touching end-to-end with any member of the group?
                for k in group:
                    ak = axes[k][1]
                    ends_k = (ak.p0, ak.p1)
                    ends_j = (ax2.p0, ax2.p1)
                    if any(_dist(a, b) < TOL for a in ends_k for b in ends_j):
                        group.append(j); used.add(j); changed = True
                        break
        # build merged axis along ax.u
        pts = []
        for k in group:
            pts.append(axes[k][1].p0); pts.append(axes[k][1].p1)
        svals = [ax.s_of(p) for p in pts]
        smin, smax = min(svals), max(svals)
        merged = Axis(ax.pt(smin), ax.pt(smax), ax.t)
        pieces = []
        for k in group:
            wk, ak = axes[k]
            a, b = merged.s_of(ak.p0), merged.s_of(ak.p1)
            pieces.append((min(a, b), max(a, b), wk['t'], wk['id']))
        pieces.sort()
        ch = Chain(len(chains), merged, pieces)
        for k in group:
            ch.wall_axes[axes[k][0]['id']] = axes[k][1]
        chains.append(ch)
    return chains


def _attach_openings(chains, openings):
    """Проёмы — в координаты цепочки. s проёма отсчитан от p0 СВОЕЙ стены; у склеенной цепочки
    (две стены на одной оси) и у стены, повёрнутой против оси цепочки, это не s цепочки.
    Вставка, чей хозяин — другая стена (Revit отдаёт окно соседней стены как «общую вставку»),
    проёмом этой стены не считается."""
    for c in chains:
        c.openings = []
        for op in openings:
            ax = c.wall_axes.get(op['wall_id'])
            if ax is None:
                continue
            host = op.get('host_id')
            if host is not None and host != op['wall_id']:
                continue
            a = c.axis.s_of(ax.pt(op['s0']))
            b = c.axis.s_of(ax.pt(op['s1']))
            c.openings.append((min(a, b), max(a, b), op['id']))
        c.openings.sort()


def _find_nodes(chains):
    """Detect junctions between chain ends and other chains."""
    nodes = []

    def node_at(p):
        for nd in nodes:
            if _dist(nd.p, p) < TOL * 4:
                return nd
        nd = Node(len(nodes), p)
        nodes.append(nd)
        return nd

    for c in chains:
        for end_s, d in ((0.0, +1), (c.L, -1)):   # d: direction away from the node
            p = c.axis.pt(end_s)
            t_c = c.t_at(end_s)
            for o in chains:
                if o is c or c.axis.parallel(o.axis):
                    continue
                off = abs(o.axis.off_of(p))
                s_o = o.axis.s_of(p)
                if off > o.t_at(s_o) / 2.0 + TOL:
                    continue
                if s_o < -t_c / 2.0 - TOL or s_o > o.L + t_c / 2.0 + TOL:
                    continue
                # junction point = intersection of the two axes
                jp = o.axis.pt(s_o)
                nd = node_at(jp)
                if not any(l['chain'] is c for l in nd.legs):
                    nd.legs.append(dict(chain=c, s=c.axis.s_of(jp), dir=d, t=t_c, end=True))
                o_end = s_o < t_c / 2.0 + TOL or s_o > o.L - t_c / 2.0 - TOL
                if not any(l['chain'] is o for l in nd.legs):
                    if o_end:
                        od = +1 if s_o < o.L / 2.0 else -1
                        nd.legs.append(dict(chain=o, s=s_o, dir=od, t=o.t_at(s_o), end=True))
                    else:
                        nd.legs.append(dict(chain=o, s=s_o, dir=0, t=o.t_at(s_o), end=False))
    # crossings (interior/interior)
    for i, c in enumerate(chains):
        for o in chains[i + 1:]:
            if c.axis.parallel(o.axis):
                continue
            # solve c.p0 + u*s = o.p0 + v*r
            d = _sub(o.axis.p0, c.axis.p0)
            den = _cross(c.axis.u, o.axis.u)
            s = _cross(d, o.axis.u) / den
            r = _cross(d, c.axis.u) / den
            if TOL < s < c.L - TOL and TOL < r < o.L - TOL:
                jp = c.axis.pt(s)
                nd = node_at(jp)
                for ch, sv in ((c, s), (o, r)):
                    if not any(l['chain'] is ch for l in nd.legs):
                        nd.legs.append(dict(chain=ch, s=sv, dir=0, t=ch.t_at(sv), end=False))
    # a continuous wall through a T or X contributes two legs (both directions)
    for nd in nodes:
        legs = []
        for l in nd.legs:
            if l['end']:
                legs.append(l)
            else:
                legs.append(dict(l, dir=-1)); legs.append(dict(l, dir=+1))
        nd.legs = legs
    return nodes


def _point_in_rect(p, r, tol=TOL):
    return r['xmin'] - tol <= p[0] <= r['xmax'] + tol and r['ymin'] - tol <= p[1] <= r['ymax'] + tol


def _make_events(chains, nodes, columns):
    for c in chains:
        ev = [Event('start', c.lo, c.lo), Event('end', c.hi, c.hi)]
        for s0, s1, oid in c.openings:
            ev.append(Event('opening', s0, s1, oid))
        ev.extend(c.blocks)
        for nd in nodes:
            own = [x for x in nd.legs if x['chain'] is c]
            for l in own:
                # thickness of the crossing wall(s) blocks this stretch
                others = [x for x in nd.legs if x['chain'] is not c]
                half = max([x['t'] for x in others] + [0.0]) / 2.0
                if l['end']:
                    kind = 'corner'
                    if l['s'] < c.L / 2.0:
                        e = Event(kind, c.lo, l['s'] + half, nd)
                    else:
                        e = Event(kind, l['s'] - half, c.hi, nd)
                elif len(own) == 1:
                    # сквозная стена, одна сторона которой ушла в проём: здесь у неё угол
                    e = Event('corner', l['s'] - half, l['s'] + half, nd)
                else:
                    e = Event('tee' if nd.kind == 'T' else 'cross', l['s'] - half, l['s'] + half, nd)
                ev.append(e)
                break
        # columns at chain ends
        for col in columns:
            for s_end in (0.0, c.L):
                if _point_in_rect(c.axis.pt(s_end), col):
                    if s_end == 0.0:
                        ev.append(Event('column', 0.0, min(c.L, col_extent(c, col, 0.0)), col['id']))
                    else:
                        ev.append(Event('column', max(0.0, col_extent(c, col, c.L)), c.L, col['id']))
        # thickness steps between pieces
        for k in range(1, len(c.pieces)):
            s_prev1, t_prev = c.pieces[k - 1][1], c.pieces[k - 1][2]
            t_next = c.pieces[k][2]
            if abs(t_prev - t_next) > 1.0:
                ev.append(Event('step', s_prev1, s_prev1, dict(t_from=t_prev, t_to=t_next)))
        # merge overlapping blocking events, keep steps separate
        ev.sort(key=lambda e: (e.s0, e.s1))
        c.events = ev


def col_extent(chain, col, s_end):
    """How far the column rectangle reaches along the chain axis from its end."""
    corners = [(col['xmin'], col['ymin']), (col['xmax'], col['ymin']),
               (col['xmax'], col['ymax']), (col['xmin'], col['ymax'])]
    ss = [chain.axis.s_of(p) for p in corners]
    return min(ss) if s_end > 0 else max(ss)


def _make_piers(chains):
    for c in chains:
        blocks = [e for e in c.events if e.kind not in ('step',)]
        blocks.sort(key=lambda e: e.s0)
        # union of blocked intervals (with the event that produced the boundary)
        merged = []
        for e in blocks:
            if merged and e.s0 <= merged[-1][1] + TOL:
                if e.s1 > merged[-1][1]:
                    merged[-1] = (merged[-1][0], e.s1, merged[-1][2], e)
            else:
                merged.append((e.s0, e.s1, e, e))
        piers = []
        for k in range(len(merged) - 1):
            s0, s1 = merged[k][1], merged[k + 1][0]
            if s1 - s0 > TOL:
                piers.append(Pier(c, s0, s1, merged[k][3], merged[k + 1][2]))
        # split piers at thickness steps
        steps = [e for e in c.events if e.kind == 'step']
        out = []
        for p in piers:
            cuts = [e for e in steps if p.s0 + TOL < e.s0 < p.s1 - TOL]
            if not cuts:
                out.append(p); continue
            last_s, last_e = p.s0, p.ev0
            for e in cuts:
                out.append(Pier(c, last_s, e.s0, last_e, e))
                last_s, last_e = e.s0, e
            out.append(Pier(c, last_s, p.s1, last_e, p.ev1))
        c.piers = out


def opening_splits(op, S):
    """Мелкое отверстие (меньше порога и по ширине, и по высоте) стену не делит."""
    if S is None:
        return True
    if not S.get('opening_splits_pier', True):
        return False
    w_mm = abs(op['s1'] - op['s0'])
    h_mm = op.get('h')
    w_min = S.get('opening_min_w_cm', 0) * 10
    h_min = S.get('opening_min_h_cm', 0) * 10
    if h_mm is None:
        return w_mm >= w_min
    return not (w_mm < w_min and h_mm < h_min)


DROPPED_STUBS = []   # id стен-огрызков, выкинутых из геометрии в последнем build()


def _drop_stubs(chains, S):
    """Перпендикулярный огрызок не считается пересечением ВООБЩЕ (пользователь, 20.09):
    стена, которая одним концом упирается в другую стену, другим свободна и выступает за её
    грань не больше stub_max_cm, выкидывается до поиска узлов. Основная стена не режется,
    углового семейства там нет. (Огрызок на ОДНОЙ ОСИ с настоящей стеной склеен с ней в цепочку
    и сюда не попадает — его обрабатывает правило r['stub'] в design.)"""
    del DROPPED_STUBS[:]
    if S is None:
        return chains
    lim = S.get('stub_max_cm', 15) * 10.0 + TOL
    keep = []
    for c in chains:
        inside = []                               # по концам: сколько оси лежит в теле чужой стены
        at_end = [False]
        for end_s, far_s in ((0.0, c.L), (c.L, 0.0)):
            p, pf = c.axis.pt(end_s), c.axis.pt(far_s)
            best = None
            for o in chains:
                if o is c or c.axis.parallel(o.axis):
                    continue
                off = o.axis.off_of(p)
                s_o = o.axis.s_of(p)
                t_o = o.t_at(s_o)
                if abs(off) > t_o / 2.0 + TOL:
                    continue
                if s_o < -c.t_at(end_s) / 2.0 - TOL or s_o > o.L + c.t_at(end_s) / 2.0 + TOL:
                    continue
                # огрызок у НАЧАЛА / КОНЦА другой стены — это настоящий угол (угловое семейство,
                # хомут от края стены); арматуры нет только в самом огрызке (r['stub'] в design).
                # Пересечением не считается только огрызок посередине стены.
                t_c = c.t_at(end_s)
                if s_o < t_c / 2.0 + TOL or s_o > o.L - t_c / 2.0 - TOL:
                    at_end[0] = True
                sign = 1.0 if o.axis.off_of(pf) >= 0 else -1.0
                val = t_o / 2.0 - sign * off
                best = val if best is None else max(best, val)
            inside.append(best)
        hits = [x for x in inside if x is not None]
        if len(hits) == 1 and not at_end[0] and c.L - hits[0] <= lim:
            DROPPED_STUBS.extend(wid for s0, s1, t, wid in c.pieces)
            continue
        keep.append(c)
    return keep


OPEN_LEGS = []   # (wall_id, x, y) ветвей узлов, снятых в последнем build(): проём на весь луч


def _leg_half(nd, c):
    return max([x['t'] for x in nd.legs if x['chain'] is not c] + [0.0]) / 2.0


def _covered(intervals, a, b, rest):
    """Участок [a, b] оси занят проёмами целиком; у краёв допускается остаток стены <= rest."""
    if not any(s0 < b - TOL and s1 > a + TOL for s0, s1, _i in intervals):
        return False
    pos = a + rest
    for s0, s1, _i in intervals:
        if s1 <= pos:
            continue
        if s0 > pos + TOL:
            break
        pos = s1
    return pos >= b - rest - TOL


def _opening_at_face(intervals, face, d, rest):
    """Первый проём по лучу (от грани узла в сторону d) начинается не дальше rest от грани —
    стены у узла на уровне плана нет. -> дальний край этого проёма (s) или None."""
    best = None
    for s0, s1, _i in intervals:
        near, far_e = (s0, s1) if d > 0 else (s1, s0)
        if (far_e - face) * d <= TOL:            # проём целиком по другую сторону грани
            continue
        dist = max(0.0, (near - face) * d)
        if best is None or dist < best[0]:
            best = (dist, far_e)
    if best is not None and best[0] <= rest + TOL:
        return best[1]
    return None


def _leg_rest(c, face, S):
    """Сколько стены между гранью узла и проёмом ещё не считается стеной: не меньше
    open_wall_rest_cm и не меньше open_wall_rest_t_factor * толщина этой стены."""
    return max(S.get('open_wall_rest_cm', 5) * 10.0,
               float(S.get('open_wall_rest_t_factor', 0.0)) * c.t_at(face))


def _drop_open_legs(chains, nodes, S):
    """Проём на всю стену (пользователь, 05.10): если по лучу узла от его грани до соседнего узла
    или до торца стены стоит проём (окно на всю длину), стены на этом луче нет — луч из узла
    снимается. Узел, где осталась одна стена (или одна сквозная), пересечением не считается:
    L -> торец оставшейся стены (торец продлевается на квадрат узла), T -> угол или сквозная стена.
    Решения принимаются по исходным узлам, потом применяются разом.
    06.10.2026: то же, если окно начинается у самой грани узла — остаток стены до окна не больше
    толщины стены (`_leg_rest`): стена кончается окном, остаток стеной не считается."""
    del OPEN_LEGS[:]
    if S is None:
        return nodes
    rest = S.get('open_wall_rest_cm', 5) * 10.0
    # где на каждой цепочке стоят узлы: [(s, half, node)]
    stops = {}
    for nd in nodes:
        seen = set()
        for l in nd.legs:
            if id(l['chain']) in seen:
                continue
            seen.add(id(l['chain']))
            stops.setdefault(id(l['chain']), []).append((l['s'], _leg_half(nd, l['chain']), nd))
    gone = []                                     # (nd, leg, face, far)
    for nd in nodes:
        for l in nd.legs:
            c, d = l['chain'], l['dir']
            if d == 0:
                continue
            face = l['s'] + d * _leg_half(nd, c)
            far = c.hi if d > 0 else c.lo
            for s2, h2, nd2 in stops.get(id(c), []):
                if nd2 is nd or (s2 - l['s']) * d <= TOL:
                    continue
                f2 = s2 - d * h2
                if (f2 - far) * d < 0:
                    far = f2
            a, b = min(face, far), max(face, far)
            r_leg = _leg_rest(c, face, S)
            if b - a > TOL and _covered(c.openings, a, b, r_leg):
                gone.append((nd, l, face, far))
                continue
            # окно у самого узла (остаток <= r_leg): стена у узла кончается окном (06.10.2026)
            hit = _opening_at_face(c.openings, face, d, r_leg)
            if hit is not None and (far - hit) * d >= -TOL:
                gone.append((nd, l, face, hit))
    if not gone:
        return nodes
    for nd, l, face, far in gone:
        c = l['chain']
        start = (c.lo if l['dir'] > 0 else c.hi) if l['end'] else face
        c.blocks.append(Event('opening', min(start, far), max(start, far), 'open wall'))
        OPEN_LEGS.append((c.pieces[0][3], int(round(nd.p[0])), int(round(nd.p[1]))))
    keep = []
    for nd in nodes:
        drop = [g for g in gone if g[0] is nd]
        if not drop:
            keep.append(nd)
            continue
        removed = [g[1] for g in drop]
        nd.legs = [l for l in nd.legs if not any(l is x for x in removed)]
        chs = []
        for l in nd.legs:
            if not any(l['chain'] is x for x in chs):
                chs.append(l['chain'])
        if len(chs) > 1:
            keep.append(nd)
            continue
        # узла больше нет; торец оставшейся стены доходит до дальней грани снятой стены
        half_r = max([x['t'] for x in removed if x['chain'] not in chs] + [0.0]) / 2.0
        for l in nd.legs:
            if not l['end']:
                continue
            c = l['chain']
            if l['dir'] > 0:
                c.lo = min(c.lo, l['s'] - half_r)
            else:
                c.hi = max(c.hi, l['s'] + half_r)
    return keep


def build(walls, openings, columns, S=None):
    openings = [o for o in openings if opening_splits(o, S)]
    chains = _drop_stubs(_make_chains(walls), S)
    _attach_openings(chains, openings)
    nodes = _drop_open_legs(chains, _find_nodes(chains), S)
    _make_events(chains, nodes, columns)
    _make_piers(chains)
    return chains, nodes


# ----------------------------------------------------------------------
# reinforcement rules
# ----------------------------------------------------------------------
def _rows_for(b_cm, S):
    # rows_min: семейства не умеют один ряд («2 Line Quantity» при Quantity y = 1 не рисует
    # ни одной точки, «2 Line Spacing» рисует два ряда, а считает один) — проверено 20.09.2026
    for bmin, bmax, rows in S['edge_rows_by_thickness']:
        if bmin <= b_cm < bmax:
            return max(rows, int(S.get('rows_min', 2)))
    return 2


def _inner_for(b_cm, S):
    row = S['inner_by_thickness'][-1]
    for bmin, bmax, dia, sp, rows in S['inner_by_thickness']:
        if bmin <= b_cm < bmax:
            row = (bmin, bmax, dia, sp, rows)
            break
    pool = sorted(S.get('inner_diameters') or S.get('allowed_diameters') or [10, 12])
    dia = row[2]
    for d in pool:
        if d >= dia:
            dia = d
            break
    else:
        dia = pool[-1]
    return dia, row[3], max(row[4], int(S.get('rows_min', 2)))


def allowed(S):
    """Разрешённые на этаж диаметры, по возрастанию."""
    return sorted(S.get('allowed_diameters') or [12, 16, 20])


def snap_up(dia, S):
    """Поднимает диаметр до ближайшего разрешённого."""
    for d in allowed(S):
        if d >= dia:
            return d
    return allowed(S)[-1]


def _dias(S):
    d_min = S.get('edge_min_diameter', 12)
    out = [d for d in allowed(S) if d >= d_min]
    return out or allowed(S)


def _grow(n_start, n_max, step, dias, As_req, areas):
    """Держим количество, растим диаметр. Количество поднимаем только когда
    максимального диаметра не хватило. -> (n, dia, ok)"""
    n = n_start
    while n <= n_max:
        for d in dias:
            if n * areas[d] >= As_req:
                return n, d, True
        n += step
    return n_max, dias[-1], False


def pick_edge(b_cm, L_cm, S, areas, n_fixed=None):
    """Краевая зона (торец, край проёма). As = b*L/1000 на одну зону."""
    L_eff = L_cm if S['edge_L_cap_cm'] is None else min(L_cm, S['edge_L_cap_cm'])
    As_req = b_cm * L_eff / 1000.0 * (1 + S.get('design_margin_pct', 0) / 100.0)
    rows = _rows_for(b_cm, S)
    n0 = n_fixed if n_fixed else S.get('edge_bars_per_zone', 4)
    n0 = max(int(n0), rows)
    n_max = max(n0, S.get('edge_max_bars', 8))
    n, d, ok = _grow(n0, n_max, rows, _dias(S), As_req, areas)
    per_row = int(math.ceil(n / float(rows)))
    n = per_row * rows
    return dict(per_row=per_row, rows=rows, dia=d, n=n, As_req=As_req,
                As_prov=n * areas[d], zone_cm=S['edge_zone_factor'] * b_cm, ok=ok)


def _distribute(k, weights, max_diff):
    """k позиций по лучам пропорционально weights, минимум 1 на луч,
    разница между лучами не больше max_diff."""
    n = len(weights)
    if n == 0:
        return []
    if k <= n:
        return [1] * n
    rest = k - n
    tot = float(sum(weights)) or 1.0
    raw = [w / tot * rest for w in weights]
    add = [int(math.floor(x)) for x in raw]
    left = rest - sum(add)
    order = sorted(range(n), key=lambda i: raw[i] - add[i], reverse=True)
    for i in range(left):
        add[order[i % n]] += 1
    res = [1 + add[i] for i in range(n)]
    guard = 0
    while max(res) - min(res) > max_diff and guard < 200:
        hi = res.index(max(res))
        lo = res.index(min(res))
        res[hi] -= 1
        res[lo] += 1
        guard += 1
    return res


def corner_options(b_cm, leg_L_cm, S, areas, caps=None, as_req=None):
    """Все допустимые раскладки угла. -> (As_req, [вариант, ...])

    Вариант: узел + 2*(сумма позиций ветвей), один диаметр на весь узел.
    Позиции ветвей делятся пропорционально длинам лучей, разница ограничена.
    """
    n_legs = len(leg_L_cm)
    L_gov = max(leg_L_cm) if leg_L_cm else 0.0
    As_req = b_cm * L_gov / 1000.0 * (1 + S.get('design_margin_pct', 0) / 100.0)
    if as_req is not None:                       # задано снаружи: по длине стены каждой ветви
        As_req = as_req
    cb, ch = S['corner_block_bars']
    node = ch * 2 + (cb - 2) * 2
    k_max = max(n_legs, int(S.get('corner_extra_bars_max', 6)) // 2)
    max_diff = S.get('corner_wing_max_diff', 2)
    dias = _dias(S)
    opts = []
    for k in range(n_legs, k_max + 1):
        wings = _distribute(k, leg_L_cm, max_diff)
        if caps:                                 # в короткий выступ помещается не больше caps[i] позиций
            capped = [min(w, caps[i]) if i < len(caps) else w for i, w in enumerate(wings)]
            lost = sum(wings) - sum(capped)
            wings = capped
            # позиции, не поместившиеся в короткий луч, уходят на лучи, где место есть (длинные первыми)
            order = sorted(range(len(wings)), key=lambda i: -leg_L_cm[i])
            while lost > 0:
                moved = False
                for i in order:
                    room = caps[i] if i < len(caps) else 99
                    if lost > 0 and wings[i] < room:
                        wings[i] += 1
                        lost -= 1
                        moved = True
                if not moved:
                    break
        n = node + 2 * sum(wings)
        for d in dias:
            opts.append(dict(n=n, dia=d, k=k, wings=list(wings), node=node,
                             n_legs=n_legs, rows=2, per_row=max(wings),
                             L_gov=L_gov, As_req=As_req,
                             As_prov=n * areas[d], ok=n * areas[d] >= As_req,
                             zone_cm=S['edge_zone_factor'] * b_cm))
    opts.sort(key=lambda o: (o['As_prov'], o['n']))
    return As_req, opts


def pick_corner(b_cm, leg_L_cm, S, areas, caps=None, as_req=None):
    """Самый лёгкий по стали вариант, который проходит по площади.
    caps — предел позиций ветви по каждому лучу (сколько помещается в выступ стены)."""
    As_req, opts = corner_options(b_cm, leg_L_cm, S, areas, caps, as_req)
    good = [o for o in opts if o['ok']]
    if good:
        best = dict(good[0])
        best['options'] = opts
        return best
    best = dict(opts[-1]) if opts else dict(n=0, dia=0, As_prov=0.0, As_req=As_req,
                                            wings=[], node=0, n_legs=len(leg_L_cm),
                                            rows=2, per_row=1, L_gov=0.0,
                                            zone_cm=S['edge_zone_factor'] * b_cm)
    best['ok'] = False
    best['options'] = opts
    return best


def edge_bar_x_cm(edge, S):
    """Положение самого внутреннего стержня краевой группы от торца простенка."""
    per_row = edge.get('per_row', 1) if edge else 1
    return S['edge_offset_cm'] + (per_row - 1) * S['edge_bar_spacing_mm'] / 10.0


def pick_inner(b_cm, L_cm, S, edge=None, x0_cm=None, x1_cm=None):
    """Внутренние стержни между арматурой двух концов простенка.

    x0_cm / x1_cm — докуда от начала / конца простенка доходит арматура этого конца
    (последний стержень краевой группы или ветви угла). Чистое расстояние между ними
    делится на равные промежутки, поэтому зазор от крайнего стержня до первого внутреннего
    РАВЕН шагу между внутренними. Количество — минимальное, при котором шаг не реже требуемого.
    Если чистое расстояние и так не больше требуемого шага — внутренних стержней не нужно.
    """
    dia, sp_req_mm, rows = _inner_for(b_cm, S)
    s_req = sp_req_mm / 10.0
    s_min = S.get('inner_min_gap_cm', 10)
    x0 = edge_bar_x_cm(edge, S) if x0_cm is None else x0_cm
    x1 = x0 if x1_cm is None else x1_cm
    Lin = L_cm - x0 - x1
    if Lin <= s_req or s_req <= 0:
        return None
    k = int(math.ceil(Lin / s_req))          # промежутков
    per_row = k - 1                          # стержней в ряду
    step = Lin / float(k)
    while per_row > 0 and step < s_min:
        per_row -= 1
        k = per_row + 1
        step = Lin / float(k)
    if per_row <= 0:
        return None
    capped = False
    if S.get('inner_governed_by') == 'count':
        max_per_row = max(1, int(S.get('inner_max_bars', 6) // rows))
        if per_row > max_per_row:
            per_row = max_per_row
            k = per_row + 1
            step = Lin / float(k)
            capped = True
    return dict(dia=dia, spacing_mm=round(step * 10, 1), rows=rows, per_row=per_row,
                n=per_row * rows, length_cm=Lin, x_start_cm=x0, gap_cm=step,
                s_req_mm=sp_req_mm, capped=capped,
                ok=step <= s_req + 1e-6 and step >= s_min - 1e-6)


def stirrup_for(r, S):
    """Хомут короткой стены: A вдоль стены, B поперёк, оба минус 2*stirrup_cover.
    Только если вся стена (цепочка) короткая — простенок длинной стены не считается."""
    if not S.get('stirrup_on', True) or not r.get('short'):
        return None
    p = r['pier']
    if S.get('stirrup_whole_wall_only', True) and p.chain.L > S['short_wall_max_cm'] * 10.0 + TOL:
        return None
    c = float(S.get('stirrup_cover_mm', 25))
    # длина хомута — вся стена вместе с углом: до ДАЛЬНЕЙ грани примыкающей стены
    s_lo, s_hi = p.s0, p.s1
    if S.get('stirrup_include_corner', True):
        e0, e1 = p.ev0, p.ev1
        if e0.kind == 'corner':
            s_lo = e0.s0 - (e0.s1 - e0.s0)
        elif e0.kind in ('tee', 'cross'):
            s_lo = e0.s0
        if e1.kind == 'corner':
            s_hi = e1.s1 + (e1.s1 - e1.s0)
        elif e1.kind in ('tee', 'cross'):
            s_hi = e1.s1
    A_mm = (s_hi - s_lo) - 2 * c
    B_mm = p.t - 2 * c
    if A_mm <= 0 or B_mm <= 0:
        return None
    return dict(A_mm=A_mm, B_mm=B_mm, dia=S.get('stirrup_diameter', 8),
                spacing_mm=S.get('stirrup_spacing_mm', 200), s_lo=s_lo, s_hi=s_hi)


def box_aabb(c, u, ha, hb):
    """Осевой прямоугольник (xmin, ymin, xmax, ymax) бокса с центром c, осью u,
    полуразмерами ha вдоль u и hb поперёк."""
    ex = abs(u[0]) * ha + abs(u[1]) * hb
    ey = abs(u[1]) * ha + abs(u[0]) * hb
    return (c[0] - ex, c[1] - ey, c[0] + ex, c[1] + ey)


def rects_overlap(a, b, gap=0.0):
    return (a[0] < b[2] + gap and b[0] < a[2] + gap and
            a[1] < b[3] + gap and b[1] < a[3] + gap)


def rect_hits_walls(rect, axes, gap):
    """Прямоугольник (xmin, ymin, xmax, ymax) ближе gap к любой стене из axes (список Axis)."""
    x0, y0, x1, y1 = rect
    pts = []
    for k in range(9):
        f = k / 8.0
        pts.append((x0 + (x1 - x0) * f, y0)); pts.append((x0 + (x1 - x0) * f, y1))
        pts.append((x0, y0 + (y1 - y0) * f)); pts.append((x1, y0 + (y1 - y0) * f))
    for wax in axes:
        lim = wax.t / 2.0 + gap
        for q in pts:
            s = max(0.0, min(wax.L, wax.s_of(q)))
            if _dist(q, wax.pt(s)) < lim:
                return True
        for e in (wax.p0, wax.p1, wax.pt(wax.L / 2.0)):     # стена внутри прямоугольника
            if x0 < e[0] < x1 and y0 < e[1] < y1:
                return True
    return False


def stirrup_place(layout, walls, S, boxes=None):
    """Место выноски-хомута: рядом со стеной снаружи так, чтобы ВЕСЬ бокс
    (контур + поля размеров) не касался ни одной стены с зазором stirrup_gap_mm.

    layout: dict(axis, s_lo, s_hi, t, side, A, B, m_along, m_across)
    walls:  список dict(p0, p1, t) — все стены вида
    -> (center, half_along, half_across). Детерминировано: один и тот же
    результат при каждом запуске, поэтому обновление не считает это сдвигом.
    Порядок перебора: сдвиг вдоль стены (0, ±шаг, ±2 шага…), потом дальше от стены.
    """
    ax = layout['axis']
    u = ax.u
    n = _mul(ax.n, layout['side'] or 1)
    ha = layout['A'] / 2.0 + layout['m_along']
    hb = layout['B'] / 2.0 + layout['m_across']
    gap = float(S.get('stirrup_gap_mm', 100))
    step = float(S.get('stirrup_shift_step_mm', 250))
    s_mid = (layout['s_lo'] + layout['s_hi']) / 2.0
    d0 = layout['t'] / 2.0 + gap + hb
    axes = [Axis(w['p0'], w['p1'], w['t']) for w in walls]

    def box_pts(c):
        pts = []
        for k in range(13):
            f = -1.0 + k / 6.0
            pts.append(_add(_add(c, _mul(u, ha * f)), _mul(n, hb)))
            pts.append(_add(_add(c, _mul(u, ha * f)), _mul(n, -hb)))
            pts.append(_add(_add(c, _mul(u, ha)), _mul(n, hb * f)))
            pts.append(_add(_add(c, _mul(u, -ha)), _mul(n, hb * f)))
        return pts

    def conflict(c):
        if boxes:                                   # уже поставленные выноски (осевые прямоугольники)
            mine = box_aabb(c, u, ha, hb)
            for b in boxes:
                if rects_overlap(mine, b, gap):
                    return True
        pts = box_pts(c)
        for wax in axes:
            lim = wax.t / 2.0 + gap - 1.0
            for q in pts:
                s = max(0.0, min(wax.L, wax.s_of(q)))
                if _dist(q, wax.pt(s)) < lim:
                    return True
            for e in (wax.p0, wax.p1):          # торец стены внутри бокса
                v = _sub(e, c)
                if abs(_dot(v, u)) < ha and abs(_dot(v, n)) < hb:
                    return True
        return False

    for j in range(int(S.get('stirrup_search_rings', 12))):   # шагов наружу (было 4 — не хватало)
        d = d0 + j * step
        for k in range(9):
            for sgn in ((0,) if k == 0 else (+1, -1)):
                c = _add(ax.pt(s_mid + sgn * k * step), _mul(n, d))
                if not conflict(c):
                    return c, ha, hb
    return _add(ax.pt(s_mid), _mul(n, d0)), ha, hb


def _ray_hit(p, d, a, b):
    """Расстояние вдоль луча p + d*s (s > 0) до отрезка ab; None, если не пересекает."""
    e = _sub(b, a)
    den = _cross(d, e)
    if abs(den) < 1e-9:
        return None
    w = _sub(a, p)
    s = _cross(w, e) / den
    r = _cross(w, d) / den
    if s > TOL and -1e-6 <= r <= 1 + 1e-6:
        return s
    return None


def walls_centroid(chains):
    """Центр тяжести осей стен вида (взвешен длиной)."""
    sx = sy = wsum = 0.0
    for c in chains:
        m = c.axis.pt(c.L / 2.0)
        sx += m[0] * c.L
        sy += m[1] * c.L
        wsum += c.L
    if wsum <= 0:
        return (0.0, 0.0)
    return (sx / wsum, sy / wsum)


def outer_side(pier, chains, centroid, S=None):
    """+1 / -1 — множитель к нормали оси (axis.n): с какой стороны стены «наружа».

    Меряем просвет по нормали от трёх точек простенка (у концов и середина)
    до ближайшей другой стены. Свободнее — значит наружу. Если с обеих сторон
    ничего нет или просвет одинаковый — сторона, обращённая от центра стен вида.
    """
    mode = (S or {}).get('stirrup_side', 'outside')
    if mode == 'left':
        return +1
    if mode == 'right':
        return -1
    ax = pier.chain.axis
    mid = ax.pt((pier.s0 + pier.s1) / 2.0)
    probes = (pier.s0 + TOL, (pier.s0 + pier.s1) / 2.0, pier.s1 - TOL)
    clear = {}
    for sign in (+1, -1):
        d = _mul(ax.n, sign)
        best = None
        for c in chains:
            if c is pier.chain:
                continue
            for s_probe in probes:
                hit = _ray_hit(ax.pt(s_probe), d, c.axis.p0, c.axis.p1)
                if hit is not None and (best is None or hit < best):
                    best = hit
        clear[sign] = best
    away = +1 if _dot(_sub(mid, centroid), ax.n) >= 0 else -1
    if clear[+1] is None and clear[-1] is None:
        return away
    if clear[+1] is None:
        return +1
    if clear[-1] is None:
        return -1
    if abs(clear[+1] - clear[-1]) < TOL:
        return away
    return +1 if clear[+1] > clear[-1] else -1


NODE_KINDS = ('corner', 'tee', 'cross')
FREE_KINDS = ('start', 'end', 'opening')
# «Стена» для формулы As = b*L/1000: отрезок между проёмами / дверями / балками и торцами.
# Пересечения с другими стенами стену НЕ режут (пользователь, 22.09).
SEG_CUTS = ('opening', 'column', 'step')


def wall_segments(chain):
    """[(s_lo, s_hi)] — куски оси цепочки между проёмами, балками и уступами толщины."""
    cuts = sorted((e.s0, e.s1) for e in chain.events if e.kind in SEG_CUTS)
    segs = []
    pos = chain.lo
    for a, b in cuts:
        if a - pos > TOL:
            segs.append((pos, a))
        pos = max(pos, b)
    if chain.hi - pos > TOL:
        segs.append((pos, chain.hi))
    return segs or [(chain.lo, chain.hi)]


def segment_len(segs, s_mid, default):
    for a, b in segs:
        if a - TOL <= s_mid <= b + TOL:
            return b - a
    return default


def pick_column(b_cm, L_cm, S, areas):
    """Простенок-колонна (L <= 4b, без пересечений): стержни равномерно вдоль обеих граней
    от торца до торца, шаг не больше column_max_spacing_mm, угловые обязательны.
    Площадь — как у двух краевых зон: 2 * b*L/1000. Растёт диаметр, количество задаёт шаг."""
    As_req = 2.0 * b_cm * L_cm / 1000.0 * (1 + S.get('design_margin_pct', 0) / 100.0)
    rows = _rows_for(b_cm, S)
    off = S['edge_offset_cm'] * 10.0
    span = max(L_cm * 10.0 - 2 * off, 0.0)
    s_max = float(S.get('column_max_spacing_mm', 200))
    per_row = max(2, int(math.ceil(span / s_max - 1e-9)) + 1) if span > TOL else 1
    step = span / (per_row - 1) if per_row > 1 else 0.0
    n = per_row * rows
    dia, ok = _dias(S)[-1], False
    for d in _dias(S):
        if n * areas[d] >= As_req:
            dia, ok = d, True
            break
    return dict(per_row=per_row, rows=rows, n=n, dia=dia, spacing_mm=round(step, 1),
                offset_mm=off, As_req=As_req, As_prov=n * areas[dia], ok=ok)


def _node_span(chain, nd):
    """(s_lo, s_hi) — участок оси цепочки, занятый узлом: от ближней до дальней грани
    примыкающих стен."""
    s_node = None
    for l in nd.legs:
        if l['chain'] is chain:
            s_node = l['s']
            break
    if s_node is None:
        return None
    half = max([x['t'] for x in nd.legs if x['chain'] is not chain] + [0.0]) / 2.0
    return s_node - half, s_node + half


def wall_groups(ch, rs):
    """[(s_lo, s_hi, [results])] — куски СТЕНЫ между проёмами: проём (окно, дверь, отверстие,
    балка) стену заканчивает, пересечение с другой стеной — нет. На физическом конце стены
    длина берётся вместе с углом (до дальней грани примыкающей стены)."""
    lo, hi = _chain_span(ch)
    groups, cur = [], []
    for r in sorted(rs, key=lambda r: r['pier'].s0):
        cur.append(r)
        if r['pier'].ev1.kind == 'opening':
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        p0, p1 = g[0]['pier'], g[-1]['pier']
        s_lo = p0.ev0.s1 if p0.ev0.kind == 'opening' else lo
        s_hi = p1.ev1.s0 if p1.ev1.kind == 'opening' else hi
        out.append((s_lo, s_hi, g))
    return out


def _assign_hairpins(results, S):
    """Короткий простенок (<= hairpin_max_clear_cm, 50 см) в стене, которая целиком длиннее и не
    детализируется, между ТОРЦОМ стены у узла ('corner' на конце цепочки) и СКВОЗНЫМ узлом
    ('tee' / 'cross'). Пользователь, 06.10.2026: середину заполнить внутренним рядом (r['fill'])
    и поставить пешку — П-стержень Ø hairpin_diameter @ hairpin_spacing_mm (по минимальной сетке
    стены, по умолчанию 8@200): закрыта у торца стены, ветви вдоль граней заходят за сквозной
    узел на hairpin_lap_d * Ø от его дальней грани (не дальше конца стены и края проёма)."""
    for r in results:
        r['hairpin'] = None
    if not S.get('hairpin_on', True):
        return
    # только короткий огрызок у торца: чистый простенок между гранью угла и ближней гранью
    # сквозного узла не больше hairpin_max_clear_cm (пользователь, 07.10: 40 см — да, 135 — нет)
    lim = S.get('hairpin_max_clear_cm', 50) * 10.0 + TOL
    lap_d = float(S.get('hairpin_lap_d', 65))
    cov = float(S.get('stirrup_cover_mm', 25))
    for r in results:
        if r['short'] or r.get('stub') or r.get('column'):
            continue
        p = r['pier']
        if p.L > lim:
            continue
        c = p.chain
        # Ø и шаг пешки — по минимальной сетке этой стены (таблица inner_by_thickness)
        m_dia, m_sp, _rows = _inner_for(p.t / 10.0, S)
        dia = S.get('hairpin_diameter') or m_dia
        sp_h = S.get('hairpin_spacing_mm') or m_sp
        lap = lap_d * dia
        lo, hi = _chain_span(c)
        e0, e1 = p.ev0, p.ev1
        if e0.kind == 'corner' and e0.s0 <= c.lo + TOL and e1.kind in ('tee', 'cross'):
            d, closed, node_far = +1, lo + cov, e1.s1
        elif e1.kind == 'corner' and e1.s1 >= c.hi - TOL and e0.kind in ('tee', 'cross'):
            d, closed, node_far = -1, hi - cov, e0.s0
        else:
            continue
        limit = (hi - cov) if d > 0 else (lo + cov)
        for e in c.events:
            if e.kind != 'opening':
                continue
            face = e.s0 if d > 0 else e.s1
            if (face - node_far) * d > -TOL:
                lim_o = face - d * cov
                if (lim_o - limit) * d < 0:
                    limit = lim_o
        open_ = node_far + d * lap
        if (open_ - limit) * d > 0:
            open_ = limit
        r['fill'] = True
        r['hairpin'] = dict(closed=closed, open=open_, d=d, t=p.t, cov=cov,
                            leg=abs(open_ - closed), base=p.t - 2 * cov, dia=dia,
                            spacing_mm=sp_h)


def _assign_stirrups(chains, results, S):
    """Хомут — на СТЕНУ целиком (цепочку с учётом склейки), если она не длиннее short_wall_max_cm.
    Пересечение с другой стеной стену не режет: хомут идёт сквозь узел, на угловом конце —
    до дальней грани примыкающей стены. Проём режет: свой хомут по каждую сторону проёма.
    Участок из одних огрызков хомут не получает. Результат кладётся в r['stirrup'] первого
    простенка участка."""
    c_mm = float(S.get('stirrup_cover_mm', 25))
    by_chain = {}
    for r in results:
        by_chain.setdefault(r['pier'].chain.id, []).append(r)
    lim = S['short_wall_max_cm'] * 10.0 + TOL
    for ch in chains:
        rs = by_chain.get(ch.id, [])
        if not rs:
            continue
        for s_lo, s_hi, g in wall_groups(ch, rs):
            # порог 2 м — по КУСКУ МЕЖДУ ПРОЁМАМИ (пользователь, 24.09): простенок между окнами
            # длинной стены — тоже «стена», его так же детализируем и даём хомут
            if s_hi - s_lo > lim:
                continue
            if all(r.get('stub') for r in g):
                continue
            for r in g:
                r['short'] = True                 # кусок ≤ 2 м: детализируем (ряд + хомут)
            if not S.get('stirrup_on', True):
                continue
            host = max(g, key=lambda r: r['pier'].L)
            A_mm = (s_hi - s_lo) - 2 * c_mm
            B_mm = host['pier'].t - 2 * c_mm
            if A_mm <= 0 or B_mm <= 0:
                continue
            g[0]['stirrup'] = dict(A_mm=A_mm, B_mm=B_mm, t=host['pier'].t,
                                   dia=S.get('stirrup_diameter', 8),
                                   spacing_mm=S.get('stirrup_spacing_mm', 200),
                                   s_lo=s_lo, s_hi=s_hi)
            g[0]['stirrup_side'] = g[0]['out_side']


def design(chains, nodes, S, areas):
    """Attach reinforcement decisions to piers and nodes. Returns list of result dicts."""
    results = []
    centroid = walls_centroid(chains)
    for c in chains:
        segs = wall_segments(c)
        for p in c.piers:
            b_cm, L_cm = p.t / 10.0, p.L / 10.0
            # As считается по ДЛИНЕ СТЕНЫ (отрезок между проёмами/балками), а не по участку
            # между пересечениями; краевые группы всё так же ставятся по концам участка
            L_wall_cm = segment_len(segs, (p.s0 + p.s1) / 2.0, p.L) / 10.0
            # «короткая» = детализируем (внутренний ряд): решает _assign_stirrups по СТЕНЕ целиком,
            # там же, где ставится хомут; простенок длинной стены между узлами ряд не получает (22.09)
            short = False
            edge = pick_edge(b_cm, L_wall_cm, S, areas)
            r = dict(pier=p, b_cm=b_cm, L_cm=L_cm, L_wall_cm=L_wall_cm,
                     short=short, edge=edge, edges=[])
            for ev in (p.ev0, p.ev1):
                if ev.kind == 'column':
                    r['edges'].append(('column', None))
                elif ev.kind in ('corner', 'tee', 'cross'):
                    r['edges'].append((ev.kind, ev.ref))       # handled by the node
                elif ev.kind == 'step':
                    r['edges'].append(('step', ev.ref))
                else:
                    r['edges'].append((ev.kind, edge))         # start/end/opening -> edge group
            kinds = (p.ev0.kind, p.ev1.kind)
            at_node = any(k in NODE_KINDS for k in kinds)
            # огрызок: выступ за перпендикулярную стену не больше stub_max_cm —
            # ни хомута, ни краёв, ни внутреннего ряда; работает только угловое семейство
            r['stub'] = at_node and p.L <= S.get('stub_max_cm', 15) * 10.0 + TOL
            # маленький кусок у окна (07.10.2026): между узлом и проёмом / торцом, не длиннее
            # small_piece_t_factor * b — своей арматуры нет (ни края, ни ветви узла), а угол остаётся
            if (not r['stub'] and at_node and any(k in FREE_KINDS for k in kinds)
                    and p.L <= float(S.get('small_piece_t_factor', 1.0)) * p.t + TOL):
                r['stub'] = True
            # колонна: отдельный простенок (оба конца — торец/проём, пересечений нет), L <= column_ratio * b
            r['column'] = None
            if (not at_node and all(k in FREE_KINDS for k in kinds)
                    and p.L <= S.get('column_ratio', 4.0) * p.t + TOL):
                r['column'] = pick_column(b_cm, L_cm, S, areas)
            if r['stub'] or r['column']:
                r['edges'] = [(('stub' if r['stub'] else 'column_pier') if k in FREE_KINDS else k, v)
                              for k, v in r['edges']]
            # pier shorter than two edge zones -> one group in the middle, no inner zone
            # «Одной группы по центру» больше нет (20.09): смысл правила — чтобы арматура одного
            # конца не заходила на арматуру другого. Это решает _fill_between после подбора узлов.
            single = False
            r['single_group'] = single
            if single:
                spacing_cm = S['edge_bar_spacing_mm'] / 10.0
                fit = int(math.floor((L_cm - 2 * S['edge_offset_cm']) / spacing_cm)) + 1
                r['single_per_row'] = max(1, min(edge['per_row'], fit))
            r['inner'] = None                     # считает _fill_between, когда известны ветви углов
            r['skip_edge'] = [False, False]
            r['edge0'] = r['edge1'] = edge
            r['out_side'] = outer_side(p, chains, centroid, S)     # «наружа» простенка: +1/-1 к axis.n
            r['stirrup'] = None
            r['stirrup_side'] = 0
            results.append(r)
    _assign_stirrups(chains, results, S)
    _assign_hairpins(results, S)
    _unify_edges(chains, results, S, areas)
    # nodes: длина простенка на каждом луче + подбор по самому длинному
    for nd in nodes:
        leg_L = []
        caps = []
        best = None
        leg_as = []                              # As по каждой ветви: b * L стены / 1000 (как у края)
        stub_piers = set(id(x['pier']) for x in results if x.get('stub'))
        wall_len = dict((id(x['pier']), x.get('L_wall_cm')) for x in results)
        sp_w = float(S.get('corner_wing_spacing_mm', 70))
        for l in nd.legs:
            c = l['chain']
            d = l['dir']
            own = 0.0
            own_pier = None
            for p in c.piers:
                touches = (p.ev0.ref is nd) if d > 0 else (p.ev1.ref is nd)
                if touches and p.L > own:
                    own = p.L
                    own_pier = p
                if (p.ev0.ref is nd or p.ev1.ref is nd) and (best is None or p.L > best.L):
                    best = p
            leg_L.append(own / 10.0)
            if own_pier is not None and id(own_pier) not in stub_piers:
                Lw = wall_len.get(id(own_pier)) or own / 10.0
                leg_as.append(own_pier.t / 10.0 * Lw / 1000.0 * (1 + S.get('design_margin_pct', 0) / 100.0))
            # ветвь: стержни в sp, 2*sp, ... от грани узла; до торца выступа должен остаться защитный слой.
            # Огрызок, в который не помещается ни одна позиция, ветвь не получает.
            cap = max(0, int((own - S['cover_cm'] * 10.0 + 1e-6) // sp_w)) if own > 0 else 0
            if own_pier is not None:
                other = own_pier.ev1 if d > 0 else own_pier.ev0
                if other.kind in NODE_KINDS:
                    # простенок МЕЖДУ ДВУМЯ УЗЛАМИ: ветви идут навстречу, место делится на обе.
                    # Между последними стержнями ветвей должен остаться хотя бы шаг ветви:
                    # n0 + n1 <= L / шаг - 1. Поровну, нечётная позиция — узлу у начала простенка.
                    total = max(0, int((own + 1e-6) // sp_w) - 1)
                    cap = min(cap, total // 2 + (total % 2 if d > 0 else 0))
            if own > 0 and own <= S.get('stub_max_cm', 15) * 10.0 + TOL:
                cap = 0                           # в огрызке арматуры нет вообще, даже если позиция помещается
            if own_pier is not None and id(own_pier) in stub_piers:
                cap = 0                           # маленький кусок у окна: ветвь в него не заходит
            caps.append(cap)
        if best is None or not leg_L:
            nd.design = None
            continue
        # если на луче не нашли простенок (упёрся в другой узел), берём длину цепочки
        leg_L = [x if x > 0 else best.L / 10.0 for x in leg_L]
        # угол обслуживает концы нескольких стен — берём наибольшее требование (07.10.2026:
        # «от окна до угла одно расстояние» — край и угол одного куска стены считаются одинаково)
        nd.design = pick_corner(best.t / 10.0, leg_L, S, areas, caps,
                                as_req=max(leg_as) if leg_as else None)
        nd.design['caps'] = caps
        nd.design['from_pier'] = best
        nd.design['leg_L_cm'] = leg_L
        nd.outward = node_outward(nd)
    _fill_between(results, S)
    _unify_short_walls(chains, results, nodes, S, areas)
    return results


def _chain_span(ch):
    """(lo, hi) — стена от края до края: с учётом угловых узлов на концах (до дальней грани
    примыкающей стены)."""
    lo, hi = ch.lo, ch.hi
    for e in ch.events:
        if e.kind == 'corner':
            span = _node_span(ch, e.ref)
            if span:
                lo, hi = min(lo, span[0]), max(hi, span[1])
    return lo, hi


def _unify_short_walls(chains, results, nodes, S, areas):
    """Стенка короче unify_short_wall_cm, у которой есть угол: ВСЯ арматура одним диаметром —
    максимальным из тех, что в ней получились (угол, края, внутренний ряд). Иначе на 60-70 см
    стены выходит разброс Ø10 / Ø12 / Ø16 (пользователь, 20.09). Диаметр только растёт."""
    lim = S.get('unify_short_wall_cm', 80) * 10.0
    if lim <= 0:
        return
    by_chain = {}
    for r in results:
        by_chain.setdefault(r['pier'].chain.id, []).append(r)
    for _pass in range(2):                        # второй проход: узел общий с соседней короткой стенкой
        for ch in chains:
            for s_lo, s_hi, rs in wall_groups(ch, by_chain.get(ch.id, [])):
                if s_hi - s_lo >= lim - TOL:
                    continue
                nds = []
                for r in rs:
                    for ev in (r['pier'].ev0, r['pier'].ev1):
                        if ev.kind in NODE_KINDS and getattr(ev.ref, 'design', None) and ev.ref not in nds:
                            nds.append(ev.ref)
                if not nds:
                    continue
                dias = [nd.design['dia'] for nd in nds]
                for r in rs:
                    if r.get('stub'):
                        continue
                    if r.get('column'):
                        dias.append(r['column']['dia'])
                        continue
                    for i in (0, 1):
                        if r['edges'][i][0] in FREE_KINDS and not r['skip_edge'][i]:
                            dias.append((r['edge0'], r['edge1'])[i]['dia'])
                    if r.get('inner'):
                        dias.append(r['inner']['dia'])
                d_max = max(dias)
                for nd in nds:
                    if nd.design['dia'] != d_max:
                        nd.design['dia'] = d_max
                        nd.design['As_prov'] = nd.design['n'] * areas[d_max]
                        nd.design['ok'] = nd.design['As_prov'] >= nd.design['As_req']
                for r in rs:
                    if r.get('stub') or r.get('column'):
                        continue
                    for key in ('edge0', 'edge1'):
                        e = dict(r[key])
                        e['dia'] = d_max
                        e['As_prov'] = e['n'] * areas[d_max]
                        r[key] = e
                    r['edge'] = r['edge0']
                    r['edges'] = [(k, (r['edge0'], r['edge1'])[i] if k in FREE_KINDS else v)
                                  for i, (k, v) in enumerate(r['edges'])]
                    if r.get('inner'):
                        r['inner'] = dict(r['inner'], dia=d_max)
                    r['unified_dia'] = d_max


def check_piers(results, S):
    """САМОПРОВЕРКА расчёта: по каждому простенку выписывает положения всех стержней вдоль него
    (краевые группы, ветви углов, внутренний ряд, колонна) и ищет:
      - стержни разных элементов ближе check_min_gap_mm друг к другу (наложение);
      - стержни за пределами простенка или ближе защитного слоя к свободному торцу.
    -> список dict(wall, s0, kind, text). Пустой список — всё чисто. Общая сетка безопасности:
    ловит ошибки правил на любом здании, а не только там, где их заметили глазами."""
    sp_e = float(S.get('edge_bar_spacing_mm', 70))
    sp_w = float(S.get('corner_wing_spacing_mm', 70))
    off = S['edge_offset_cm'] * 10.0
    gap_min = float(S.get('check_min_gap_mm', 40))
    out = []
    for r in results:
        p = r['pier']
        L = p.L
        bars = []                                  # (s от начала простенка, источник)
        if r.get('column'):
            col = r['column']
            for i in range(col['per_row']):
                bars.append((col['offset_mm'] + i * col['spacing_mm'], u'column'))
        elif not r.get('stub'):
            ends = ((p.ev0, +1, r['edge0'], 0), (p.ev1, -1, r['edge1'], 1))
            for ev, leg_dir, ee, i in ends:
                kind = r['edges'][i][0]
                pos = []
                if kind in FREE_KINDS and not r['skip_edge'][i]:
                    pos = [(off + k * sp_e, u'edge') for k in range(ee['per_row'])]
                elif kind in NODE_KINDS:
                    pos = [((k + 1) * sp_w, u'corner leg') for k in range(wing_n(ev.ref, p.chain, leg_dir))]
                for s_, src in pos:
                    bars.append((s_ if i == 0 else L - s_, src + (u' (start)' if i == 0 else u' (end)')))
            inn = r.get('inner')
            if inn:
                x0 = inn['x_start_cm'] * 10.0
                for k in range(inn['per_row']):
                    bars.append((x0 + (k + 1) * inn['spacing_mm'], u'inner row'))
        else:                                       # огрызок: арматуры быть не должно, но ветвь угла могла зайти
            for ev, leg_dir in ((p.ev0, +1), (p.ev1, -1)):
                if ev.kind in NODE_KINDS and wing_n(ev.ref, p.chain, leg_dir):
                    out.append(dict(wall=p.chain.pieces[0][3], s0=round(p.s0), kind=u'stub',
                                    text=u'a corner leg reaches into the %.0f mm stub' % L))
        bars.sort()
        wid = p.chain.pieces[0][3]
        zone = S['edge_zone_factor'] * p.t
        for i, (ev, ee) in enumerate(((p.ev0, r.get('edge0')), (p.ev1, r.get('edge1')))):
            if not ee or r['edges'][i][0] not in FREE_KINDS or r['skip_edge'][i]:
                continue
            row = 2 * S['edge_offset_cm'] * 10.0 + (ee['per_row'] - 1) * S['edge_bar_spacing_mm']
            if row > zone + 1.0:
                out.append(dict(wall=wid, s0=round(p.s0), kind=u'edge zone',
                                text=u'%dØ%d: the %.0f mm row does not fit the 2b = %.0f mm edge zone '
                                     u'(needs a bigger Ø or fewer bars)'
                                     % (ee['n'], ee['dia'], row, zone)))
            if not ee['ok']:
                out.append(dict(wall=wid, s0=round(p.s0), kind=u'As not reached',
                                text=u'edge %dØ%d = %.1f cm2 against the required %.1f cm2'
                                     % (ee['n'], ee['dia'], ee['As_prov'], ee['As_req'])))
        for s_, src in bars:
            if s_ < -1.0 or s_ > L + 1.0:
                out.append(dict(wall=wid, s0=round(p.s0), kind=u'outside the wall',
                                text=u'%s: bar at %.0f mm while the pier is %.0f long' % (src, s_, L)))
        for (a, sa), (b, sb) in zip(bars, bars[1:]):
            if sa != sb and b - a < gap_min:
                out.append(dict(wall=wid, s0=round(p.s0), kind=u'overlap',
                                text=u'%s (%.0f) and %s (%.0f): %.0f mm between bars, pier %.0f'
                                     % (sa, a, sb, b, b - a, L)))
    seen = set()
    for r in results:
        for ev in (r['pier'].ev0, r['pier'].ev1):
            nd = ev.ref if ev.kind in NODE_KINDS else None
            d = getattr(nd, 'design', None)
            if not d or id(nd) in seen:
                continue
            seen.add(id(nd))
            if not d.get('ok', True):
                out.append(dict(wall=d['from_pier'].chain.pieces[0][3], s0=round(d['from_pier'].s0),
                                kind=u'As not reached',
                                text=u'corner %s at (%.0f, %.0f): %dØ%d = %.1f cm2 against the required '
                                     u'%.1f cm2 (allow a bigger Ø or raise corner_extra_bars_max)'
                                     % (nd.kind, nd.p[0], nd.p[1], d['n'], d['dia'], d['As_prov'], d['As_req'])))
    return out


def wing_n(nd, chain, leg_dir):
    """Сколько позиций у ветви углового семейства на луче (chain, leg_dir) узла nd."""
    d = getattr(nd, 'design', None)
    if not d:
        return 0
    wings = d.get('wings') or []
    for i, l in enumerate(nd.legs):
        if l['chain'] is chain and l['dir'] == leg_dir and i < len(wings):
            return wings[i]
    return 0


def _fill_between(results, S):
    """Середина простенка — по ЧИСТОМУ расстоянию между арматурой его концов.

    Конец-торец/проём: краевая группа, последний стержень в offset + (в ряду - 1) * шаг.
    Конец-узел: ветвь угла, последний стержень в n * шаг ветви от грани узла.
    Если арматура концов сходится ближе шага краевой группы — краевая группа у свободного
    конца не ставится (там работает угол). Дальше, только для простенков до short_wall_max_cm:
    чистое расстояние больше требуемого шага -> внутренний ряд с равным шагом не реже требуемого."""
    sp_w = float(S.get('corner_wing_spacing_mm', 70))
    min_gap = float(S.get('edge_bar_spacing_mm', 70))
    for r in results:
        if r.get('stub') or r.get('column'):
            continue
        p = r['pier']
        ends = ((p.ev0, +1, r['edge0']), (p.ev1, -1, r['edge1']))
        reach = [0.0, 0.0]
        free = [False, False]
        for i, (ev, leg_dir, ee) in enumerate(ends):
            kind = r['edges'][i][0]
            if kind in FREE_KINDS:
                reach[i] = edge_bar_x_cm(ee, S) * 10.0
                free[i] = True
            elif kind in NODE_KINDS:
                reach[i] = wing_n(ev.ref, p.chain, leg_dir) * sp_w
        if any(free) and not all(free) and p.L - reach[0] - reach[1] < min_gap:
            for i in (0, 1):
                if free[i]:
                    r['skip_edge'][i] = True
                    reach[i] = 0.0
        r['reach_mm'] = reach
        r['clear_mm'] = p.L - reach[0] - reach[1]
        if r['short'] or r.get('fill'):
            r['inner'] = pick_inner(r['b_cm'], r['L_cm'], S, r['edge'],
                                    x0_cm=reach[0] / 10.0, x1_cm=reach[1] / 10.0)


def node_outward(nd):
    """Единичный вектор «от узла наружу» = минус сумма направлений лучей.
    Г-угол — диагональ наружу, Т — от ножки, крест — (0,0) -> берём перпендикуляр к первому лучу."""
    sx = sy = 0.0
    for l in nd.legs:
        u = l['chain'].axis.u
        sx += u[0] * l['dir']
        sy += u[1] * l['dir']
    v = (-sx, -sy)
    n = _len(v)
    if n < 1e-6:
        u = nd.legs[0]['chain'].axis.u if nd.legs else (1.0, 0.0)
        return (-u[1], u[0])
    return (v[0] / n, v[1] / n)


def _unify_edges(chains, results, S, areas):
    """Apply S['edge_unify']: 'pier' (as computed), 'opening' (both sides of an opening
    take the longer pier), 'wall' (whole chain takes the longest pier)."""
    mode = S.get('edge_unify', 'pier')
    if mode == 'pier':
        return
    by_chain = {}
    for r in results:
        by_chain.setdefault(r['pier'].chain.id, []).append(r)
    for cid, rs in by_chain.items():
        rs.sort(key=lambda r: r['pier'].s0)
        if mode == 'wall':
            longest = max(rs, key=lambda r: r['pier'].L)
            for r in rs:
                e = pick_edge(r['b_cm'], longest['L_cm'], S, areas)
                r['edge'] = r['edge0'] = r['edge1'] = e
                r['edges'] = [(k, e if k in ('start', 'end', 'opening') else v) for k, v in r['edges']]
        elif mode == 'opening':
            for a, b in zip(rs, rs[1:]):
                if a['pier'].ev1 is b['pier'].ev0 and a['pier'].ev1.kind == 'opening':
                    L_use = max(a['L_cm'], b['L_cm'])
                    a['edge1'] = pick_edge(a['b_cm'], L_use, S, areas)
                    b['edge0'] = pick_edge(b['b_cm'], L_use, S, areas)
            for r in rs:
                r['edge'] = max((r['edge0'], r['edge1']), key=lambda e: e['As_prov'])
                r['edges'] = [(r['edges'][0][0], r['edge0'] if r['edges'][0][0] in ('start', 'end', 'opening') else r['edges'][0][1]),
                              (r['edges'][1][0], r['edge1'] if r['edges'][1][0] in ('start', 'end', 'opening') else r['edges'][1][1])]
        for r in rs:
            if r['single_group']:
                spacing_cm = S['edge_bar_spacing_mm'] / 10.0
                fit = int(math.floor((r['L_cm'] - 2 * S['edge_offset_cm']) / spacing_cm)) + 1
                r['single_per_row'] = max(1, min(r['edge']['per_row'], fit))
