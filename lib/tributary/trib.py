# -*- coding: utf-8 -*-
"""Растровое разбиение плиты по ближайшей опоре (грузовые площади). Всё в мм.

Grid  — растр плит уровня: 0 вне плиты, 1 плита, 2 проём (внутри контура плиты).
assign — метки опор распространяются от опор по 8 соседям, приоритет — евклидово
         расстояние от ячейки до геометрии опоры. Это диаграмма Вороного «по ближайшей
         опоре», которая обходит проёмы и входящие углы (площадь не тянется через шахту).
"""
import math
import heapq

from tributary.geom import poly_area

OUT, SLAB, HOLE = 0, 1, 2
_SEG, _RECT, _ROUND = 0, 1, 2
_CODE = {'seg': _SEG, 'rect': _RECT, 'round': _ROUND}
SEED_TOL = 50.0      # зазор опора–край плиты, который ещё считается опиранием, мм


def _spans(loops, y):
    """Интервалы по x внутри набора контуров (чёт-нечет) на горизонтали y."""
    xs = []
    for pts in loops:
        n = len(pts)
        for a in range(n):
            x1, y1 = pts[a]
            x2, y2 = pts[(a + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    return [(xs[k], xs[k + 1]) for k in range(0, len(xs) - 1, 2)]


class Grid(object):
    def __init__(self, slabs, step):
        self.s = s = float(step)
        xs = [q[0] for sl in slabs for q in sl['outer']]
        ys = [q[1] for sl in slabs for q in sl['outer']]
        if not xs:
            raise ValueError(u'no slab outlines')
        self.x0 = min(xs) - s
        self.y0 = min(ys) - s
        self.nx = int(math.ceil((max(xs) - self.x0) / s)) + 2
        self.ny = int(math.ceil((max(ys) - self.y0) / s)) + 2
        N = self.nx * self.ny
        self.kind = [OUT] * N
        self.slab = [-1] * N
        self.h = [float(sl['h']) for sl in slabs]
        polys = []
        for k, sl in enumerate(slabs):
            self._fill(k, sl)
            polys.append(max(poly_area(sl['outer']) - sum(poly_area(hl) for hl in sl.get('holes', [])), 0.0))
        self.area_poly = sum(polys)
        # вес ячейки: растр каждого куска плиты приводится к точной площади его контура
        # (убирает систематическую ошибку, когда край плиты совпадает с рядом ячеек)
        cnt = [0] * len(slabs)
        for k in self.slab:
            if k >= 0:
                cnt[k] += 1
        self.weight = []
        self.overlaps = []
        for k in range(len(slabs)):
            f = polys[k] / (cnt[k] * s * s) if cnt[k] else 1.0
            if not 0.8 <= f <= 1.25:
                if cnt[k]:
                    self.overlaps.append(slabs[k].get('id'))
                f = 1.0
            self.weight.append(f)
        self._close_gaps()

    def cx(self, i):
        return self.x0 + (i + 0.5) * self.s

    def cy(self, j):
        return self.y0 + (j + 0.5) * self.s

    def _irange(self, xa, xb):
        i0 = int(math.ceil((xa - self.x0) / self.s - 0.5))
        i1 = int(math.floor((xb - self.x0) / self.s - 0.5))
        return max(i0, 0), min(i1, self.nx - 1)

    def _fill(self, k, sl):
        outer = [tuple(q) for q in sl['outer']]
        holes = [[tuple(q) for q in hl] for hl in sl.get('holes', [])]
        ys = [q[1] for q in outer]
        j0 = max(int((min(ys) - self.y0) / self.s) - 1, 0)
        j1 = min(int((max(ys) - self.y0) / self.s) + 1, self.ny - 1)
        nx = self.nx
        for j in range(j0, j1 + 1):
            y = self.cy(j)
            for xa, xb in _spans([outer] + holes, y):
                i0, i1 = self._irange(xa, xb)
                for i in range(i0, i1 + 1):
                    idx = j * nx + i
                    if self.kind[idx] != SLAB:
                        self.kind[idx] = SLAB
                        self.slab[idx] = k
            if holes:
                for xa, xb in _spans(holes, y):
                    i0, i1 = self._irange(xa, xb)
                    for i in range(i0, i1 + 1):
                        idx = j * nx + i
                        if self.kind[idx] == OUT:
                            self.kind[idx] = HOLE

    def _close_gaps(self):
        """Щели в 1 ячейку на стыках соседних плит -> плита (иначе ложный «край»).
        Проёмы (HOLE) не трогаются — узкий проём остаётся проёмом."""
        nx, ny = self.nx, self.ny
        kind = self.kind
        fix = []
        for j in range(1, ny - 1):
            for i in range(1, nx - 1):
                idx = j * nx + i
                if kind[idx] != OUT:
                    continue
                if kind[idx - 1] == SLAB and kind[idx + 1] == SLAB:
                    fix.append((idx, self.slab[idx - 1]))
                elif kind[idx - nx] == SLAB and kind[idx + nx] == SLAB:
                    fix.append((idx, self.slab[idx - nx]))
        for idx, k in fix:
            kind[idx] = SLAB
            self.slab[idx] = k
        self.closed_cells = len(fix)

    def index(self, x, y):
        i = int(math.floor((x - self.x0) / self.s))
        j = int(math.floor((y - self.y0) / self.s))
        if i < 0 or j < 0 or i >= self.nx or j >= self.ny:
            return -1
        return j * self.nx + i

    def kind_at(self, x, y):
        idx = self.index(x, y)
        return OUT if idx < 0 else self.kind[idx]

    def h_near(self, x, y, r=1500.0):
        """Толщина плиты в точке; если точка не на плите — ближайшая в радиусе r, иначе max."""
        idx = self.index(x, y)
        if idx >= 0 and self.slab[idx] >= 0:
            return self.h[self.slab[idx]]
        n = int(r / self.s)
        i0 = int(math.floor((x - self.x0) / self.s))
        j0 = int(math.floor((y - self.y0) / self.s))
        best, bh = None, None
        for j in range(max(j0 - n, 0), min(j0 + n, self.ny - 1) + 1):
            for i in range(max(i0 - n, 0), min(i0 + n, self.nx - 1) + 1):
                k = self.slab[j * self.nx + i]
                if k >= 0:
                    d = (i - i0) ** 2 + (j - j0) ** 2
                    if best is None or d < best:
                        best, bh = d, self.h[k]
        return bh if bh is not None else max(self.h)

    def slab_cells(self):
        return sum(1 for k in self.kind if k == SLAB)

    def slab_area(self):
        """Площадь растра с весами (мм²)."""
        w = self.weight
        return sum(w[k] for k in self.slab if k >= 0) * self.s * self.s


def _compile(src):
    return (_CODE[src[0]],) + tuple(float(v) for v in src[1:])


def _dist(c, x, y):
    dx = x - c[1]
    dy = y - c[2]
    t = c[0]
    if t == _SEG:
        # стена/балка — прямоугольник с ПЛОСКИМИ торцами (не капсула): иначе торец толстой
        # стены, упёртой в тонкую, вылезал на (t1 - t2)/2 за её грань и забирал площадь за ней
        s = dx * c[3] + dy * c[4]
        q = abs(dy * c[3] - dx * c[4]) - c[6]
        ea = -s if s < 0.0 else (s - c[5] if s > c[5] else 0.0)
        eb = q if q > 0.0 else 0.0
        d = math.sqrt(ea * ea + eb * eb)
    elif t == _RECT:
        a = abs(dx * c[3] + dy * c[4]) - c[5]
        b = abs(dy * c[3] - dx * c[4]) - c[6]
        a = a if a > 0.0 else 0.0
        b = b if b > 0.0 else 0.0
        d = math.sqrt(a * a + b * b)
    else:
        d = math.sqrt(dx * dx + dy * dy) - c[5]
    return d if d > 0.0 else 0.0


def _bbox(c):
    if c[0] == _SEG:
        x2, y2 = c[1] + c[3] * c[5], c[2] + c[4] * c[5]
        r = c[6]
        return min(c[1], x2) - r, min(c[2], y2) - r, max(c[1], x2) + r, max(c[2], y2) + r
    r = c[5] + c[6]
    return c[1] - r, c[2] - r, c[1] + r, c[2] + r


def assign(grid, sources):
    """sources — список src-кортежей (см. supports). Возвращает (labels, dist):
    labels[idx] — индекс источника или -1 (ячейка плиты без опоры / вне плиты)."""
    comp = [_compile(s) for s in sources]
    nx, ny, s = grid.nx, grid.ny, grid.s
    kind = grid.kind
    N = nx * ny
    INF = float('inf')
    dist = [INF] * N
    label = [-1] * N
    heap = []
    # затравка — ячейки ближе s + SEED_TOL к опоре. Стена может стоять СНАРУЖИ контура плиты
    # (край плиты по внутренней грани): ближайший центр ячейки тогда до s от грани, и при 0.75·s
    # стена без единой затравки не забирала ничего (зависело от того, как лёг растр)
    seed_r = s + SEED_TOL
    for li, c in enumerate(comp):
        x1, y1, x2, y2 = _bbox(c)
        i0 = max(int(math.floor((x1 - grid.x0) / s)) - 1, 0)
        i1 = min(int(math.floor((x2 - grid.x0) / s)) + 1, nx - 1)
        j0 = max(int(math.floor((y1 - grid.y0) / s)) - 1, 0)
        j1 = min(int(math.floor((y2 - grid.y0) / s)) + 1, ny - 1)
        for j in range(j0, j1 + 1):
            y = grid.y0 + (j + 0.5) * s
            for i in range(i0, i1 + 1):
                idx = j * nx + i
                if kind[idx] != SLAB:
                    continue
                d = _dist(c, grid.x0 + (i + 0.5) * s, y)
                if d <= seed_r and d < dist[idx]:
                    dist[idx] = d
                    label[idx] = li
                    heapq.heappush(heap, (d, idx, li))
    x0, y0 = grid.x0, grid.y0
    # проход 1: евклидово расстояние, метка идёт только «от опоры» (расстояние не убывает) —
    # так она не заворачивает за угол проёма и не забирает площадь за шахтой
    while heap:
        d, idx, li = heapq.heappop(heap)
        if label[idx] != li or d > dist[idx]:
            continue
        c = comp[li]
        i = idx % nx
        j = idx // nx
        for di, dj in _NBS:
            ii = i + di
            jj = j + dj
            if ii < 0 or jj < 0 or ii >= nx or jj >= ny:
                continue
            k = jj * nx + ii
            if kind[k] != SLAB:
                continue
            if di and dj and (kind[j * nx + ii] != SLAB or kind[jj * nx + i] != SLAB):
                continue                      # не просачиваться по диагонали через угол проёма
            nd = _dist(c, x0 + (ii + 0.5) * s, y0 + (jj + 0.5) * s)
            if nd < d - 1e-6:
                continue                      # движение к опоре = обход препятствия
            if nd < dist[k] - 1e-6:
                dist[k] = nd
                label[k] = li
                heapq.heappush(heap, (nd, k, li))
    _fill_hidden(grid, label, dist)
    return label, dist


_NBS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1))


def _fill_hidden(grid, label, dist):
    """Проход 2: ячейки плиты, не видимые ни от одной опоры (карман за шахтой, за входящим
    углом), получают метку по кратчайшему пути в обход (геодезическое расстояние по сетке)."""
    nx, ny, s = grid.nx, grid.ny, grid.s
    kind = grid.kind
    hidden = set(idx for idx in range(nx * ny) if kind[idx] == SLAB and label[idx] < 0)
    if not hidden:
        return
    heap = []
    for idx in hidden:
        i, j = idx % nx, idx // nx
        for di, dj in _NBS:
            ii, jj = i + di, j + dj
            if 0 <= ii < nx and 0 <= jj < ny:
                k = jj * nx + ii
                if label[k] >= 0 and k not in hidden:
                    heapq.heappush(heap, (dist[k], k, label[k]))
    diag = s * math.sqrt(2.0)
    while heap:
        d, idx, li = heapq.heappop(heap)
        if label[idx] != li or d > dist[idx]:
            continue
        i, j = idx % nx, idx // nx
        for di, dj in _NBS:
            ii, jj = i + di, j + dj
            if ii < 0 or jj < 0 or ii >= nx or jj >= ny:
                continue
            k = jj * nx + ii
            if k not in hidden:
                continue
            if di and dj and (kind[j * nx + ii] != SLAB or kind[jj * nx + i] != SLAB):
                continue
            nd = d + (diag if (di and dj) else s)
            if nd < dist[k] - 1e-6:
                dist[k] = nd
                label[k] = li
                heapq.heappush(heap, (nd, k, li))


def areas_by_slab(grid, label, n_sources):
    """[{кусок плиты: мм²}] по каждому источнику + {кусок: мм²} для ячеек без опоры."""
    out = [dict() for _ in range(n_sources)]
    none = {}
    kind, w, slab = grid.kind, grid.weight, grid.slab
    a = grid.s * grid.s
    for idx in range(len(label)):
        if kind[idx] != SLAB:
            continue
        k = slab[idx]
        li = label[idx]
        d = none if li < 0 else out[li]
        d[k] = d.get(k, 0.0) + w[k] * a
    return out, none


def areas(grid, label, n_sources):
    """Площадь (мм²) по каждому источнику и площадь ячеек плиты без опоры."""
    cnt = [0.0] * n_sources
    none = 0.0
    kind = grid.kind
    w = grid.weight
    slab = grid.slab
    for idx in range(len(label)):
        if kind[idx] != SLAB:
            continue
        li = label[idx]
        if li < 0:
            none += w[slab[idx]]
        else:
            cnt[li] += w[slab[idx]]
    a = grid.s * grid.s
    return [c * a for c in cnt], none * a
