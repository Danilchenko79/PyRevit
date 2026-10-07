# -*- coding: utf-8 -*-
"""Положение опоры относительно края плиты: внутренняя / крайняя / угловая. Всё в мм."""
import math

from tributary.trib import SLAB, HOLE


def _march(grid, c, d, face, across, perp, limit):
    """Расстояние от грани до выхода из плиты вдоль d (3 луча по ширине грани).
    -> (расстояние, 'edge'|'hole') или (None, None), если плита не кончилась до limit."""
    step = grid.s / 2.0
    best, cause = None, None
    for off in (0.0, 0.45 * across, -0.45 * across):
        t = 0.0
        while t <= limit:
            x = c[0] + d[0] * (face + t) + perp[0] * off
            y = c[1] + d[1] * (face + t) + perp[1] * off
            k = grid.kind_at(x, y)
            if k != SLAB:
                if best is None or t < best:
                    best, cause = t, ('hole' if k == HOLE else 'edge')
                break
            t += step
    return best, cause


def column(grid, pt, dm, p):
    """Колонна/пилон: класс и флаги по четырём направлениям локальных осей сечения.
    -> (класс, флаги, расстояние до края, ось грани у края 'u'|'v' для крайней)."""
    src = pt['src'][0]
    c = (src[1], src[2])
    u = (src[3], src[4])
    v = (-u[1], u[0])
    hx, hy = src[5], src[6]
    lim_edge = p['edge_k'] * dm
    lim_open = p['opening_k'] * dm
    dirs = [(u, hx, 2 * hy, v, 'u'), ((-u[0], -u[1]), hx, 2 * hy, v, 'u'),
            (v, hy, 2 * hx, u, 'v'), ((-v[0], -v[1]), hy, 2 * hx, u, 'v')]
    near, flags, dist_min = [], [], None
    for d, face, across, perp, axis in dirs:
        t, cause = _march(grid, c, d, face, across, perp, lim_open)
        if t is None:
            continue
        dist_min = t if dist_min is None else min(dist_min, t)
        if t <= lim_edge:
            near.append((axis, cause))
        elif cause == 'hole' and u'opening ≤ {:g}d'.format(p['opening_k']) not in flags:
            flags.append(u'opening ≤ {:g}d'.format(p['opening_k']))
    axes = [a for a, _c in near]
    if not near:
        cls = 'int'
    elif len(near) == 1:
        cls = 'edge'
    elif len(near) == 2 and axes[0] != axes[1]:
        cls = 'corner'
    elif len(near) == 2:
        cls = 'edge'
        flags.append(u'narrow strip')
    else:
        cls = 'corner'
        flags.append(u'slab narrow on 3 sides')
    if any(cz == 'hole' for _a, cz in near):
        flags.append(u'edge = opening')
    return cls, flags, dist_min, (near[0][0] if cls == 'edge' else None)


def node_near_edge(grid, pt, dm, p, reach_extra):
    """Узел/торец стены: флаг, если край плиты или проём ближе edge_k·d_m + reach_extra."""
    lim = p['edge_k'] * dm + reach_extra
    step = grid.s / 2.0
    found = None
    for a in range(16):
        ang = a * math.pi / 8.0
        d = (math.cos(ang), math.sin(ang))
        t = 0.0
        while t <= lim:
            k = grid.kind_at(pt[0] + d[0] * t, pt[1] + d[1] * t)
            if k != SLAB:
                cause = 'hole' if k == HOLE else 'edge'
                if found is None or cause == 'edge':
                    found = cause
                break
            t += step
    if found == 'edge':
        return [u'near slab edge']
    if found == 'hole':
        return [u'near opening']
    return []
