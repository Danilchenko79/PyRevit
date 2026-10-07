# -*- coding: utf-8 -*-
"""Опоры плиты: колонны, пилоны, узлы стен (L/T/X), торцы, середины стен, балки.

Вход — dict'ы в мм (см. collect.py):
    wall   {'id','link','name','p0':[x,y],'p1':[x,y],'t'}
    column {'id','link','name','x','y','b','h','ux','uy','shape'}   b — вдоль (ux,uy)
    beam   {'id','link','name','p0','p1','b'}

Выход build():
    points  — точки продавливания: {'kind','x','y','ids','links','names','dims','flags','src'}
    others  — прочие опоры, забирающие площадь: {'kind','ids','links','names','src'}
    notes   — предупреждения
src — геометрия для trib (всегда 7 полей): ('rect', cx, cy, ux, uy, hx, hy)
      | ('round', cx, cy, ux, uy, r, r) | ('seg', ax, ay, ux, uy, L, half_t)
"""
from tributary.geom import (sub, dot, unit, dist, seg_param, dist_to_seg, line_intersection,
                            angle_deg, rect_dist)

# узлы, где проверяется продавливание: торец и ВЫПУКЛЫЙ угол L (плита снаружи угла).
# Вогнутые углы (внутренняя сторона L, узлы T и X) продавливания не дают — их полки
# остаются «серединой стены» и площадь уходит в стену.
KINDS_NODE = ('wall_L', 'wall_end')


class _Wall(object):
    def __init__(self, i, w):
        self.i = i
        self.id = w['id']
        self.link = w.get('link') or u''
        self.name = w.get('name') or u''
        self.a = (float(w['p0'][0]), float(w['p0'][1]))
        self.b = (float(w['p1'][0]), float(w['p1'][1]))
        self.t = float(w['t'])
        self.L = dist(self.a, self.b)
        self.u = unit(sub(self.b, self.a))
        self.lo = (min(self.a[0], self.b[0]), min(self.a[1], self.b[1]))
        self.hi = (max(self.a[0], self.b[0]), max(self.a[1], self.b[1]))

    def end(self, e):
        return self.a if e == 0 else self.b

    def into(self, e):
        """Направление от конца e внутрь стены."""
        return self.u if e == 0 else (-self.u[0], -self.u[1])

    def pt(self, s):
        return (self.a[0] + s * self.u[0], self.a[1] + s * self.u[1])

    def s_of(self, p):
        s = dot(sub(p, self.a), self.u)
        return min(max(s, 0.0), self.L)

    def near_box(self, p, r):
        return (self.lo[0] - r <= p[0] <= self.hi[0] + r and
                self.lo[1] - r <= p[1] <= self.hi[1] + r)


class _UF(object):
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _column_point(c):
    u = unit((float(c.get('ux', 1.0)), float(c.get('uy', 0.0))))
    x, y = float(c['x']), float(c['y'])
    b, h = float(c['b']), float(c['h'])
    if c.get('shape') == 'round':
        src = ('round', x, y, u[0], u[1], b / 2.0, b / 2.0)
    else:
        src = ('rect', x, y, u[0], u[1], b / 2.0, h / 2.0)
    return {'kind': 'column', 'x': x, 'y': y, 'ids': [c['id']], 'links': [c.get('link') or u''],
            'names': [c.get('name') or u''], 'flags': [],
            'dims': {'shape': c.get('shape') or 'rect', 'b': b, 'h': h, 'ux': u[0], 'uy': u[1]},
            'src': [src]}


def _col_contains(col, p, r):
    """Точка p ближе r к контуру колонны (или внутри)."""
    s = col['src'][0]
    if s[0] == 'round':
        return dist(p, (s[1], s[2])) - s[5] <= r
    return rect_dist(p, (s[1], s[2]), (s[3], s[4]), s[5], s[6]) <= r


def _slab_along(slab_at, pt, d, tmax, dm_at):
    """Есть ли плита в направлении d от точки (2 из 3 проб на расстояниях t/√2 + (0.5..1.5)·d_m)."""
    dm = dm_at(pt[0], pt[1])
    hits = 0
    for f in (0.5, 1.0, 1.5):
        r = tmax * 0.75 + f * dm
        if slab_at(pt[0] + d[0] * r, pt[1] + d[1] * r):
            hits += 1
    return hits >= 2


BEAM_END_TOL = 100.0     # конец балки дальше грани опоры на столько — считается не опёртым


def _supported_beams(beams, W, cols, notes):
    """Балка — линейная опора, только если оба конца лежат на стене / колонне / другой принятой
    балке. Краевые балки-бортики консольных балконов так не проходят и площадь не забирают."""
    cand = []
    for b in beams:
        a = (float(b['p0'][0]), float(b['p0'][1]))
        c = (float(b['p1'][0]), float(b['p1'][1]))
        L = dist(a, c)
        if L < 1.0:
            continue
        bm = dict(b)
        bm['_geo'] = (a, unit(sub(c, a)), L, float(b.get('b') or 200.0))
        bm['_ends'] = (a, c)
        cand.append(bm)

    def on_fixed(P):
        for w in W:
            if dist_to_seg(P, w.a, w.u, w.L) <= w.t / 2.0 + BEAM_END_TOL:
                return True
        for col in cols:
            if _col_contains(col, P, BEAM_END_TOL):
                return True
        return False

    ok = [False] * len(cand)
    fixed = [[on_fixed(P) for P in bm['_ends']] for bm in cand]
    changed = True
    while changed:
        changed = False
        for i, bm in enumerate(cand):
            if ok[i]:
                continue
            ends_ok = []
            for e, P in enumerate(bm['_ends']):
                good = fixed[i][e]
                if not good:
                    for k, other in enumerate(cand):
                        if k != i and ok[k]:
                            oa, ou, oL, ob = other['_geo']
                            if dist_to_seg(P, oa, ou, oL) <= ob / 2.0 + BEAM_END_TOL:
                                good = True
                                break
                ends_ok.append(good)
            if all(ends_ok):
                ok[i] = True
                changed = True
    rejected = [bm['id'] for i, bm in enumerate(cand) if not ok[i]]
    if rejected:
        notes.append(u'beams not supported at both ends are not used as supports ({}): {}'.format(
            len(rejected), u', '.join(u'{}'.format(i) for i in rejected[:20])))
    return [bm for i, bm in enumerate(cand) if ok[i]]


def build(walls, columns, beams, p, dm_at, slab_at=None):
    tol = p['node_tol']
    min_ang = p['min_angle']
    notes = []
    points = [_column_point(c) for c in columns]
    cols = list(points)
    W = [_Wall(i, w) for i, w in enumerate(walls)]
    W = [w for w in W if w.L > 1.0 and w.t > 1.0]
    for i, w in enumerate(W):
        w.i = i
    n = len(W)
    uf = _UF(2 * n)
    mids = {}          # handle -> [(j, s)]
    col_of = {}        # handle -> индекс колонны
    has_contact = [False] * (2 * n)
    mids_on = [[] for _ in range(n)]

    # --- контакты концов стен
    for wi in W:
        for e in (0, 1):
            h = 2 * wi.i + e
            P = wi.end(e)
            for ci, col in enumerate(cols):
                if _col_contains(col, P, wi.t / 2.0 + tol):
                    col_of[h] = ci
                    has_contact[h] = True
                    break
            for wj in W:
                if wj.i == wi.i:
                    continue
                reach = (wi.t + wj.t) / 2.0 + tol
                if not wj.near_box(P, reach):
                    continue
                if dist_to_seg(P, wj.a, wj.u, wj.L) > reach:
                    continue
                s, perp = seg_param(P, wj.a, wj.u, wj.L)
                ang = angle_deg(wi.u, wj.u)
                parallel = ang < min_ang or ang > 180.0 - min_ang
                if parallel and perp > max(wi.t, wj.t) / 2.0 + tol:
                    continue                  # параллельные стены рядом, не продолжение
                if s <= reach:
                    uf.union(h, 2 * wj.i)
                    has_contact[h] = has_contact[2 * wj.i] = True
                elif s >= wj.L - reach:
                    uf.union(h, 2 * wj.i + 1)
                    has_contact[h] = has_contact[2 * wj.i + 1] = True
                elif parallel:
                    notes.append(u'walls {} and {}: parallel and overlapping'.format(wi.id, wj.id))
                else:
                    mids.setdefault(h, []).append((wj.i, s))
                    mids_on[wj.i].append(s)
                    has_contact[h] = True

    # --- пилоны: короткая стена со свободными концами, на которую никто не опирается
    pylon = [False] * n
    for w in W:
        if (not has_contact[2 * w.i] and not has_contact[2 * w.i + 1] and not mids_on[w.i]
                and w.L <= p['pylon_ratio'] * w.t):
            pylon[w.i] = True
            c = w.pt(w.L / 2.0)
            points.append({'kind': 'pylon', 'x': c[0], 'y': c[1], 'ids': [w.id],
                           'links': [w.link], 'names': [w.name], 'flags': [],
                           'dims': {'shape': 'rect', 'b': w.L, 'h': w.t, 'ux': w.u[0], 'uy': w.u[1]},
                           'src': [('rect', c[0], c[1], w.u[0], w.u[1], w.L / 2.0, w.t / 2.0)]})

    # --- группы концов -> узлы
    groups = {}
    for w in W:
        if pylon[w.i]:
            continue
        for e in (0, 1):
            h = 2 * w.i + e
            groups.setdefault(uf.find(h), []).append(h)

    nodes = []
    for hs in groups.values():
        walls_here = set(h // 2 for h in hs)
        legs = []
        lines = []
        ends = []
        for h in hs:
            w = W[h // 2]
            e = h % 2
            legs.append((w.i, w.into(e)))
            lines.append((w.end(e), w.u))
            ends.append(w.end(e))
        passing = {}
        for h in hs:
            for j, s in mids.get(h, []):
                if j not in walls_here:
                    passing.setdefault(j, []).append(s)
        for j, ss in passing.items():
            w = W[j]
            legs.append((j, w.u))
            legs.append((j, (-w.u[0], -w.u[1])))
            lines.append((w.a, w.u))
        nodes.append({'legs': legs, 'lines': lines, 'ends': ends,
                      'col': [col_of[h] for h in hs if h in col_of], 'flags': []})

    # --- пересечения «середина по середине» (крест без разрезки стен)
    for wi in W:
        for wj in W:
            if wj.i <= wi.i or pylon[wi.i] or pylon[wj.i]:
                continue
            ang = angle_deg(wi.u, wj.u)
            if ang < min_ang or ang > 180.0 - min_ang:
                continue
            x = line_intersection(wi.a, wi.u, wj.a, wj.u)
            if x is None:
                continue
            si, sj = dot(sub(x, wi.a), wi.u), dot(sub(x, wj.a), wj.u)
            ri, rj = wj.t + tol, wi.t + tol
            if ri < si < wi.L - ri and rj < sj < wj.L - rj:
                nodes.append({'legs': [(wi.i, wi.u), (wi.i, (-wi.u[0], -wi.u[1])),
                                       (wj.i, wj.u), (wj.i, (-wj.u[0], -wj.u[1]))],
                              'lines': [(wi.a, wi.u), (wj.a, wj.u)], 'ends': [x],
                              'col': [], 'flags': []})

    # --- положение и тип узла
    for nd in nodes:
        pt = None
        ln = nd['lines']
        for a in range(len(ln)):
            for b in range(a + 1, len(ln)):
                ang = angle_deg(ln[a][1], ln[b][1])
                if min_ang <= ang <= 180.0 - min_ang:
                    pt = line_intersection(ln[a][0], ln[a][1], ln[b][0], ln[b][1])
                    break
            if pt is not None:
                break
        cx = sum(q[0] for q in nd['ends']) / len(nd['ends'])
        cy = sum(q[1] for q in nd['ends']) / len(nd['ends'])
        if pt is None or dist(pt, (cx, cy)) > 1000.0:
            pt = (cx, cy)
        nd['pt'] = pt
        k = len(nd['legs'])
        if nd['col']:
            nd['kind'] = 'col_join'
        elif k == 1:
            nd['kind'] = 'wall_end'
        elif k == 2:
            ang = angle_deg(nd['legs'][0][1], nd['legs'][1][1])
            nd['kind'] = 'cont' if ang > 180.0 - min_ang else 'wall_L'
            nd['angle'] = ang
        elif k == 3:
            nd['kind'] = 'wall_T'
        else:
            nd['kind'] = 'wall_X'
    for nd in nodes:
        for ci in nd['col']:
            if u'wall attached' not in cols[ci]['flags']:
                cols[ci]['flags'].append(u'wall attached')
        if slab_at is None:
            continue
        tmax = max(W[j].t for j, _d in nd['legs'])
        if nd['kind'] == 'wall_L':
            # наружная (выпуклая) сторона угла — против суммы направлений полок
            d1, d2 = nd['legs'][0][1], nd['legs'][1][1]
            out = unit((-(d1[0] + d2[0]), -(d1[1] + d2[1])))
            if not _slab_along(slab_at, nd['pt'], out, tmax, dm_at):
                nd['kind'] = 'wall_L_in'          # снаружи угла нет плиты — угол вогнутый
        elif nd['kind'] == 'wall_end':
            d = nd['legs'][0][1]
            if not _slab_along(slab_at, nd['pt'], (-d[0], -d[1]), tmax * 0.0, dm_at):
                nd['flags'].append(u'wall end at slab edge')

    # --- позиции узлов на стенах (для длин полок)
    pos_on = [[] for _ in range(n)]
    for ni, nd in enumerate(nodes):
        for j, _d in nd['legs']:
            s = W[j].s_of(nd['pt'])
            if not pos_on[j] or all(abs(s - q) > 1.0 for q in pos_on[j]):
                pos_on[j].append(s)

    def leg_len(j, s, d):
        w = W[j]
        fwd = dot(d, w.u) > 0
        cand = [q - s for q in pos_on[j] if q - s > 1.0] if fwd else \
               [s - q for q in pos_on[j] if s - q > 1.0]
        end = (w.L - s) if fwd else s
        return min(cand) if cand else end

    # --- зоны k·d_m на осях
    intervals = [[] for _ in range(n)]     # (lo, hi, node_idx, s_node)
    for ni, nd in enumerate(nodes):
        if nd['kind'] not in KINDS_NODE:
            continue
        dm = dm_at(nd['pt'][0], nd['pt'][1])
        nd['dm'] = dm
        leg_info = []
        for li, (j, d) in enumerate(nd['legs']):
            w = W[j]
            others = [W[jj].t for (jj, _dd) in nd['legs'] if jj != j]
            zlen = p['k_zone'] * dm + (max(others) / 2.0 if others else 0.0)
            s = w.s_of(nd['pt'])
            if dot(d, w.u) > 0:
                lo, hi = s, min(s + zlen, w.L)
            else:
                lo, hi = max(s - zlen, 0.0), s
            if hi - lo > 1.0:
                intervals[j].append([lo, hi, ni, s])
            leg_info.append({'wall': w.id, 't': w.t, 'len': leg_len(j, s, d), 'ux': d[0], 'uy': d[1]})
        nd['leg_info'] = leg_info

    others = []
    for w in W:
        if pylon[w.i]:
            continue
        iv = sorted(intervals[w.i], key=lambda r: (r[0], r[1]))
        for a in range(len(iv) - 1):
            p1, p2 = iv[a], iv[a + 1]
            if p1[2] != p2[2] and p1[1] > p2[0] + 1.0:
                cut = (p1[3] + p2[3]) / 2.0
                p1[1] = min(p1[1], cut)
                p2[0] = max(p2[0], cut)
                for q in (p1, p2):
                    if u'short leg' not in nodes[q[2]]['flags']:
                        nodes[q[2]]['flags'].append(u'short leg')
        mid_src = []
        cur = 0.0
        for lo, hi, ni, _s in iv:
            if hi - lo > 1.0:
                a = w.pt(lo)
                nodes[ni].setdefault('src', []).append(
                    ('seg', a[0], a[1], w.u[0], w.u[1], hi - lo, w.t / 2.0))
            if lo - cur > 1.0:
                a = w.pt(cur)
                mid_src.append(('seg', a[0], a[1], w.u[0], w.u[1], lo - cur, w.t / 2.0))
            cur = max(cur, hi)
        if w.L - cur > 1.0:
            a = w.pt(cur)
            mid_src.append(('seg', a[0], a[1], w.u[0], w.u[1], w.L - cur, w.t / 2.0))
        if mid_src:
            others.append({'kind': 'wall_mid', 'ids': [w.id], 'links': [w.link],
                           'names': [w.name], 'src': mid_src, 'L': w.L, 't': w.t})

    for nd in nodes:
        if nd['kind'] not in KINDS_NODE or not nd.get('src'):
            continue
        ids, links, names = [], [], []
        for j, _d in nd['legs']:
            if W[j].id not in ids:
                ids.append(W[j].id)
                links.append(W[j].link)
                names.append(W[j].name)
        dims = {'legs': nd['leg_info'], 'dm': nd['dm']}
        if 'angle' in nd:
            dims['angle'] = nd['angle']
        points.append({'kind': nd['kind'], 'x': nd['pt'][0], 'y': nd['pt'][1], 'ids': ids,
                       'links': links, 'names': names, 'dims': dims, 'flags': nd['flags'],
                       'src': nd['src']})

    for bm in _supported_beams(beams, W, cols, notes):
        a, u, L, bw = bm['_geo']
        others.append({'kind': 'beam', 'ids': [bm['id']], 'links': [bm.get('link') or u''],
                       'names': [bm.get('name') or u''], 'L': L, 't': bw,
                       'src': [('seg', a[0], a[1], u[0], u[1], L, bw / 2.0)]})

    stats = {'nodes': {}}
    for nd in nodes:
        stats['nodes'][nd['kind']] = stats['nodes'].get(nd['kind'], 0) + 1
    stats['pylons'] = sum(1 for x in pylon if x)
    return {'points': points, 'others': others, 'notes': notes, 'stats': stats}
