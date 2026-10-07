# -*- coding: utf-8 -*-
"""Векторизация растра грузовых площадей: контуры областей опор без «лесенки». Всё в мм.

1. Метки ячеек -> владелец (точка / середина стены / балка / без опоры). За край плиты метки
   «разливаются» на pad ячеек — граница зон уходит за кромку, а схема обрезается точным
   контуром плиты (clipPath), поэтому край плиты ровный.
2. Рёбра между ячейками разных владельцев собираются в цепочки между узлами (где сходятся 3+
   зоны). Каждая цепочка упрощается Дугласом–Пекером ОДИН раз и используется обеими зонами —
   щелей и нахлёстов между соседями нет.
3. Цепочки владельца сшиваются в кольца (зона слева по обходу -> внешние кольца против часовой,
   дыры по часовой; рисовать fill-rule="nonzero").
"""
import math

from tributary.trib import SLAB


def owner_grid(grid, label, owner_of_src, none_owner, pad=2):
    nx, ny = grid.nx, grid.ny
    kind = grid.kind
    O = [-1] * (nx * ny)
    for idx in range(nx * ny):
        if kind[idx] == SLAB:
            li = label[idx]
            O[idx] = owner_of_src[li] if li >= 0 else none_owner
    frontier = []
    for idx in range(nx * ny):
        if O[idx] < 0:
            continue
        i, j = idx % nx, idx // nx
        if ((i > 0 and O[idx - 1] < 0) or (i < nx - 1 and O[idx + 1] < 0) or
                (j > 0 and O[idx - nx] < 0) or (j < ny - 1 and O[idx + nx] < 0)):
            frontier.append(idx)
    for _step in range(pad):
        nxt = []
        for idx in frontier:
            i, j = idx % nx, idx // nx
            for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < nx and 0 <= jj < ny:
                    k = jj * nx + ii
                    if O[k] < 0:
                        O[k] = O[idx]
                        nxt.append(k)
        frontier = nxt
    return O


def _dp(pts, tol):
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = math.sqrt(dx * dx + dy * dy)
        best, bi = -1.0, -1
        for k in range(a + 1, b):
            px, py = pts[k]
            if L < 1e-9:
                d = math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
            else:
                d = abs(dx * (py - ay) - dy * (px - ax)) / L
            if d > best:
                best, bi = d, k
        if best > tol:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return [pts[k] for k in range(n) if keep[k]]


def regions(grid, O, tol_cells=1.0):
    # 1.0 ячейки: ступенька 45° отстоит от прямой на 0.71 ячейки — при 0.6 оставалась «лесенка»
    """{владелец: [кольцо [(x, y), ...], ...]} по сетке владельцев O."""
    nx, ny, s = grid.nx, grid.ny, grid.s
    W = nx + 1

    def own(i, j):
        if 0 <= i < nx and 0 <= j < ny:
            return O[j * nx + i]
        return -1

    edges = []                 # (va, vb, left, right) для направления va -> vb
    adj = {}

    def add(va, vb, left, right):
        e = len(edges)
        edges.append((va, vb, left, right))
        adj.setdefault(va, []).append(e)
        adj.setdefault(vb, []).append(e)

    for j in range(ny + 1):
        for i in range(nx):
            below, above = own(i, j - 1), own(i, j)
            if below != above:
                add(j * W + i, j * W + i + 1, above, below)
    for i in range(nx + 1):
        for j in range(ny):
            lc, rc = own(i - 1, j), own(i, j)
            if lc != rc:
                add(j * W + i, (j + 1) * W + i, lc, rc)

    used = [False] * len(edges)

    def walk(v0, e0):
        verts = [v0]
        v, e = v0, e0
        va, vb, L, R = edges[e0]
        left, right = (L, R) if va == v0 else (R, L)
        while True:
            used[e] = True
            a, b, _l, _r = edges[e]
            u = b if a == v else a
            verts.append(u)
            if len(adj[u]) != 2:
                break
            nxt = [ee for ee in adj[u] if not used[ee]]
            if not nxt:
                break
            v, e = u, nxt[0]
        return verts, left, right

    chains = []
    for v, es in adj.items():
        if len(es) == 2:
            continue
        for e in es:
            if not used[e]:
                chains.append(walk(v, e))
    for e in range(len(edges)):
        if not used[e]:
            chains.append(walk(edges[e][0], e))

    tol = tol_cells * s
    x0, y0 = grid.x0, grid.y0

    def xy(v):
        return (x0 + (v % W) * s, y0 + (v // W) * s)

    pieces = {}
    for verts, left, right in chains:
        pts = [xy(v) for v in verts]
        if verts[0] == verts[-1] and len(pts) > 3:
            far = max(range(len(pts)), key=lambda k: (pts[k][0] - pts[0][0]) ** 2 + (pts[k][1] - pts[0][1]) ** 2)
            sp = _dp(pts[:far + 1], tol)[:-1] + _dp(pts[far:], tol)
        else:
            sp = _dp(pts, tol)
        vs, ve = verts[0], verts[-1]
        if left >= 0:
            pieces.setdefault(left, []).append((vs, ve, sp))
        if right >= 0:
            pieces.setdefault(right, []).append((ve, vs, sp[::-1]))

    out = {}
    for owner, ps in pieces.items():
        by_start = {}
        for k, (vs, _ve, _sp) in enumerate(ps):
            by_start.setdefault(vs, []).append(k)
        done = [False] * len(ps)
        rings = []
        for k0 in range(len(ps)):
            if done[k0]:
                continue
            done[k0] = True
            vs, ve, sp = ps[k0]
            ring = list(sp)
            start = vs
            guard = 0
            while ve != start and guard < len(ps):
                guard += 1
                cand = [k for k in by_start.get(ve, []) if not done[k]]
                if not cand:
                    break
                k = cand[0]
                done[k] = True
                _vs, ve, sp = ps[k]
                ring.extend(sp[1:])
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring.pop()
            if len(ring) >= 3:
                rings.append(ring)
        out[owner] = rings
    return out


def ring_area(ring):
    a = 0.0
    n = len(ring)
    for k in range(n):
        x1, y1 = ring[k]
        x2, y2 = ring[(k + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0
