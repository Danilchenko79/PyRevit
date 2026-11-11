# -*- coding: utf-8 -*-
"""Режим «нагрузки на опоры»: эпюры на балках и стенах, реакции балок, нагрузка на колонны.

profiles(grid, label, owner, objs, bin_mm, floor_of) — по растру: для каждой линейной опоры
    (балка, стена) площадь по равным участкам длиной ≈ bin_mm,
    раздельно по плитам (нагрузка задаётся по плитам и меняется в схеме).
resolve(points, others, q) — q {id плиты: кН/м²} -> нагрузки. Балка — пролёты между опорами по
    её длине (свободно опёртые), консоли — на крайнюю опору; второстепенная отдаёт реакции главной
    как сосредоточенные силы, главная — колоннам/стенам.
Длины в мм на входе, результат — кН, кН/м, м.
"""

import math


def axis_of(obj):
    """(начало, ось, длина) линейной опоры по её src-отрезкам (все на одной прямой)."""
    segs = [s for s in obj['src'] if s[0] == 'seg']
    if not segs:
        return None
    ux, uy = segs[0][3], segs[0][4]
    a = obj.get('a0')
    if a is None:
        a = (segs[0][1], segs[0][2])
    return a, (ux, uy), float(obj.get('L') or 0.0)


def profiles(grid, label, owner, objs, bin_mm, floor_of):
    """owner[li] -> индекс в objs; у линейных опор (kind wall_mid/beam) заполняет
    obj['prof'] {плита: [мм² по участкам]}, obj['nb'] участков длиной obj['bin']."""
    ax = []
    for o in objs:
        lin = o['kind'] in ('wall_mid', 'beam')
        ax.append(axis_of(o) if lin else None)
        if lin:
            o['prof'] = {}
            # равные участки ≈ bin_mm (без короткого последнего: на нём q max завышался в разы)
            o['nb'] = max(int(math.floor(float(o.get('L') or 0.0) / bin_mm + 0.5)), 1)
            o['bin'] = float(o.get('L') or 0.0) / o['nb']
    nx, s = grid.nx, grid.s
    a2 = s * s
    tot = [{} for _ in objs]
    for idx, li in enumerate(label):
        if li < 0 or grid.kind[idx] != 1:
            continue
        oi = owner[li]
        A = ax[oi]
        if A is None:
            continue
        o = objs[oi]
        (x0, y0), (ux, uy), L = A
        x = grid.x0 + (idx % nx + 0.5) * s
        y = grid.y0 + (idx // nx + 0.5) * s
        t0 = (x - x0) * ux + (y - y0) * uy
        t = 0.0 if t0 < 0.0 else (L if t0 > L else t0)
        k = grid.slab[idx]
        a = grid.weight[k] * a2
        f = floor_of(k)
        nb, bw = o['nb'], o['bin']
        pr = o['prof'].get(f)
        if pr is None:
            pr = o['prof'][f] = [0.0] * nb
        tot[oi][f] = tot[oi].get(f, 0.0) + a
        # ячейка — отрезок [t0 - s/2, t0 + s/2] по оси, делится между участками по перекрытию;
        # часть за концами опоры отбрасывается, потом эпюра приводится к полной площади (ниже).
        # Иначе крайний столбец растра (наполовину за краем плиты) завышал q max у концов
        lo = max(t0 - s / 2.0, 0.0)
        hi = min(t0 + s / 2.0, L)
        if hi - lo <= 1e-9:
            pr[min(int(math.floor(t / bw)), nb - 1)] += a
            continue
        for i in range(min(int(math.floor(lo / bw)), nb - 1), min(int(math.floor(hi / bw)), nb - 1) + 1):
            ov = min(hi, (i + 1) * bw if i < nb - 1 else L) - max(lo, i * bw)
            if ov > 0.0:
                pr[i] += a * ov / s
    for oi, o in enumerate(objs):
        if ax[oi] is None:
            continue
        for f, pr in o['prof'].items():
            sm = sum(pr)
            if sm > 0.0:
                k = tot[oi][f] / sm
                o['prof'][f] = [v * k for v in pr]


def _key(t, link, i):
    return u'{}:{}:{}'.format(t, link or u'', i)


def resolve(points, others, q):
    """q {id плиты: кН/м²}. -> {'beams': [...], 'walls': {...}, 'columns': {...}, 'total': кН}.
    Площади в объектах — в мм² (area_by_floor, prof)."""
    def load(af):
        return sum(q.get(f, 0.0) * a for f, a in af.items()) / 1e6

    beams = [o for o in others if o['kind'] == 'beam']
    cols, walls = {}, {}
    for o in list(points) + list(others):
        if o['kind'] in ('column', 'column_b'):
            cols[_key('c', o['links'][0], o['ids'][0])] = {
                'ids': o['ids'], 'direct': load(o['area_by_floor']), 'beams': 0.0, 'from': []}
        elif o['kind'] in ('wall_mid', 'pylon'):
            k = _key('w', o['links'][0], o['ids'][0])
            w = walls.setdefault(k, {'ids': o['ids'], 'L': 0.0, 'W': 0.0, 'P': [], 'qmax': 0.0})
            w['W'] += load(o['area_by_floor'])
            w['L'] = (o.get('L') or o.get('dims', {}).get('b') or 0.0) / 1000.0
            if o['kind'] == 'wall_mid':
                w['qmax'] = max(w['qmax'], _qmax(o, q))
    P_on = [[] for _ in beams]
    out = [None] * len(beams)
    for n in range(len(beams) - 1, -1, -1):          # второстепенные — раньше главных
        b = beams[n]
        L = b['L'] / 1000.0
        sup = b.get('sup') or []
        ss = [r['s'] / 1000.0 for r in sup]
        R = [0.0] * len(ss)
        W = 0.0
        # распределённая нагрузка — по участкам эпюры (внутри участка равномерная)
        prof = b.get('prof') or {}
        bw = b.get('bin', 0.0) / 1000.0
        for i in range(b.get('nb', 0)):
            Wi = sum(q.get(f, 0.0) * pr[i] for f, pr in prof.items() if i < len(pr)) / 1e6
            if Wi:
                W += Wi
                _put_span(R, ss, i * bw, (i + 1) * bw, Wi)
        for s, P in P_on[n]:
            W += P
            _put_point(R, ss, s, P)
        for r, Rj in zip(sup, R):
            if r['t'] == 'c':
                c = cols.get(_key('c', r['link'], r['id']))
                if c is not None:
                    c['beams'] += Rj
                    c['from'].append(b['ids'][0])
            elif r['t'] == 'w':
                w = walls.get(_key('w', r['link'], r['id']))
                if w is not None:
                    w['P'].append((r['at'] / 1000.0, Rj, b['ids'][0]))
            else:
                P_on[r['n']].append((r['at'] / 1000.0, Rj))
        out[n] = {'ids': b['ids'], 'L': L, 'W': W, 'R': R, 'qmax': _qmax(b, q),
                  'P': list(P_on[n]), 'free': not sup}
    for c in cols.values():
        c['N'] = c['direct'] + c['beams']
    total = sum(c['direct'] for c in cols.values()) + sum(w['W'] for w in walls.values()) + \
        sum(load(b['area_by_floor']) for b in beams)
    return {'beams': out, 'walls': walls, 'columns': cols, 'total': total}


def _put_point(R, ss, x, P):
    """Сила P в точке x балки на опорах ss (по возрастанию): пролёт между соседними опорами —
    свободно опёртый, консоль за крайней опорой целиком на неё. Без опор — теряется."""
    n = len(ss)
    if n == 0:
        return
    if x <= ss[0]:
        R[0] += P
        return
    if x >= ss[n - 1]:
        R[n - 1] += P
        return
    j = 0
    while ss[j + 1] < x:
        j += 1
    f = (x - ss[j]) / (ss[j + 1] - ss[j])
    R[j] += P * (1.0 - f)
    R[j + 1] += P * f


def _put_span(R, ss, xa, xb, W):
    """Равномерная нагрузка W на [xa, xb]: режется по опорам внутри, куски — в своих центрах."""
    cuts = [xa] + [s for s in ss if xa < s < xb] + [xb]
    for k in range(len(cuts) - 1):
        _put_point(R, ss, (cuts[k] + cuts[k + 1]) / 2.0, W * (cuts[k + 1] - cuts[k]) / (xb - xa))


def _qmax(o, q):
    """Наибольшая погонная нагрузка по участкам эпюры, кН/м."""
    prof = o.get('prof') or {}
    if not prof:
        return 0.0
    nb = max(len(v) for v in prof.values())
    best = 0.0
    for i in range(nb):
        v = sum(q.get(f, 0.0) * pr[i] for f, pr in prof.items() if i < len(pr)) / 1e6
        w = o['bin'] / 1000.0
        if w > 1e-6:
            best = max(best, v / w)
    return best
