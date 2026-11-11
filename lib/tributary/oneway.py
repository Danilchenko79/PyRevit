# -*- coding: utf-8 -*-
"""Сборные плиты (לוחדים, «30+5»), работающие в одном направлении. Всё в мм.

Ячейка такой плиты отдаёт нагрузку только вдоль пролёта: ближайшей опоре на луче «вперёд» или
«назад» (половина пролёта — каждой). Опоры, параллельные пролёту, нагрузки не получают.

    is_precast(name, mask)   — плита сборная по имени типа
    setup(slabs, p)          — [единичный вектор пролёта | None] по кускам плит
    assign(grid, sources, dirs, label, dist) — дописать метки ячеек сборных плит
"""
import math
import re

from tributary.geom import sub, unit, dist, cross
from tributary import trib

# «לוחד» (основа слова לוחדים) — через \u, чтобы не зависеть от кодировки файла
HE_STEM = u'לוחד'
_THK = re.compile(u'(?<![0-9])[0-9]{1,3} *[+] *[0-9]{1,2}(?![0-9])')
PARALLEL_SIN = 0.5           # опора под углом к пролёту меньше 30° не считается опорой сборной плиты
MARCH_MAX = 30000.0          # дальше по пролёту опору не ищем, мм


def is_precast(name, mask=u''):
    """לוחדים / толщина вида «30+5» / любое слово из mask (через запятую, без учёта регистра)."""
    s = u'{}'.format(name or u'')
    if HE_STEM in s or _THK.search(s):
        return True
    up = s.upper()
    for m in u'{}'.format(mask or u'').split(u','):
        m = m.strip().upper()
        if m and m in up:
            return True
    return False


def auto_dir(outer):
    """Направление пролёта по умолчанию: из двух главных направлений контура (самая длинная
    сторона и перпендикуляр) — то, вдоль которого плита короче (сборные плиты перекрывают
    короткий пролёт)."""
    best, L = None, -1.0
    n = len(outer)
    for i in range(n):
        a, b = outer[i], outer[(i + 1) % n]
        d = dist(a, b)
        if d > L:
            best, L = sub(b, a), d
    u = unit(best)
    v = (-u[1], u[0])
    pu = [q[0] * u[0] + q[1] * u[1] for q in outer]
    pv = [q[0] * v[0] + q[1] * v[1] for q in outer]
    du, dv = max(pu) - min(pu), max(pv) - min(pv)
    d = u if du <= dv else v
    # знак не важен; приводим к x >= 0 (а при x = 0 — к y > 0), чтобы JS и Python совпадали
    if d[0] < -1e-12 or (abs(d[0]) <= 1e-12 and d[1] < 0):
        d = (-d[0], -d[1])
    return (d[0] + 0.0, d[1] + 0.0)


def setup(slabs, p):
    """Направление пролёта для каждого куска плиты или None (плита работает в двух направлениях).
    В куске можно задать 'oneway': True/False (правка из схемы) и 'span': [ux, uy]."""
    mask = p.get('precast_mask', u'')
    out = []
    for sl in slabs:
        ow = sl.get('oneway')
        if ow is None:
            ow = is_precast(sl.get('name'), mask)
        if not ow:
            out.append(None)
            continue
        sp = sl.get('span')
        out.append(unit((float(sp[0]), float(sp[1]))) if sp else auto_dir(sl['outer']))
    return out


def kinds_two_way(grid, dirs):
    """Копия grid.kind, где ячейки сборных плит закрыты (HOLE) — по ним не идёт разбиение
    «по ближайшей опоре» двухпролётных плит."""
    if not any(d is not None for d in dirs):
        return None
    kind = list(grid.kind)
    for idx, k in enumerate(grid.slab):
        if k >= 0 and dirs[k] is not None and kind[idx] == trib.SLAB:
            kind[idx] = trib.HOLE
    return kind


def _footprints(grid, comp):
    """{ячейка: [источник, ...]} — ячейки (любого вида) не дальше s + SEED_TOL от опоры."""
    nx, ny, s = grid.nx, grid.ny, grid.s
    r = s + trib.SEED_TOL
    fp = {}
    for li, c in enumerate(comp):
        x1, y1, x2, y2 = trib._bbox(c)
        i0 = max(int(math.floor((x1 - r - grid.x0) / s)), 0)
        i1 = min(int(math.floor((x2 + r - grid.x0) / s)), nx - 1)
        j0 = max(int(math.floor((y1 - r - grid.y0) / s)), 0)
        j1 = min(int(math.floor((y2 + r - grid.y0) / s)), ny - 1)
        for j in range(j0, j1 + 1):
            y = grid.y0 + (j + 0.5) * s
            for i in range(i0, i1 + 1):
                if trib._dist(c, grid.x0 + (i + 0.5) * s, y) <= r:
                    fp.setdefault(j * nx + i, []).append(li)
    return fp


def _ok(c, d):
    """Опора годится для пролёта d: линейная — только поперёк (не параллельно)."""
    if c[0] != trib._SEG:
        return True
    return abs(cross((c[3], c[4]), d)) >= PARALLEL_SIN


def _best(comp, fp, idx, px, py, d):
    """Годная опора в ячейке idx (ближайшая к точке px, py) или -1."""
    best, bd = -1, None
    for li in fp.get(idx, ()):
        c = comp[li]
        if _ok(c, d):
            dd = trib._dist(c, px, py)
            if bd is None or dd < bd:
                best, bd = li, dd
    return best


def _hit(grid, comp, fp, x, y, d, sign):
    """(t, источник) — первая годная опора на луче от (x, y) в сторону sign·d, или (None, -1).
    Шаг — ячейка: полоса опоры (s + SEED_TOL с каждой стороны) шире шага и не проскакивается."""
    step = grid.s
    t = 0.0
    while t <= MARCH_MAX:
        px = x + sign * d[0] * t
        py = y + sign * d[1] * t
        idx = grid.index(px, py)
        if idx < 0:
            break
        best = _best(comp, fp, idx, px, py, d)
        if best >= 0:
            return t, best
        if grid.kind[idx] != trib.SLAB:
            break
        t += step
    return None, -1


def _sweep(grid, comp, fp, cells, d):
    """То же, что _hit для всех ячеек, но для пролёта вдоль X или Y: один проход по строке
    (столбцу) растра в каждую сторону вместо луча от каждой ячейки."""
    nx, ny, s = grid.nx, grid.ny, grid.s
    alongx = abs(d[1]) < 1e-12
    pos = 1 if (d[0] if alongx else d[1]) > 0 else -1
    lines = {}
    for idx in cells:
        lines.setdefault(idx // nx if alongx else idx % nx, []).append(idx)
    out = {}
    nmax = int(MARCH_MAX // s)
    for ln in lines:
        n = nx if alongx else ny
        idxs = [ln * nx + i for i in range(n)] if alongx else [j * nx + ln for j in range(n)]
        hit = [-1] * n
        for m, idx in enumerate(idxs):
            if idx in fp:
                hit[m] = _best(comp, fp, idx, grid.x0 + (idx % nx + 0.5) * s,
                               grid.y0 + (idx // nx + 0.5) * s, d)
        res = {}
        want = set(lines[ln])
        for sign in (1, -1):
            step = sign * pos                       # шаг по индексу вдоль луча
            order = range(n - 1, -1, -1) if step > 0 else range(n)
            nxt = None                              # (m опоры, источник) впереди по лучу
            for m in order:
                idx = idxs[m]
                if hit[m] >= 0:
                    nxt = (m, hit[m])
                elif grid.kind[idx] != trib.SLAB:
                    nxt = None
                if nxt is not None and idx in want:
                    k = abs(nxt[0] - m)
                    if k <= nmax:
                        res.setdefault(idx, {})[sign] = (k * s, nxt[1])
        for idx in lines[ln]:
            r = res.get(idx, {})
            a, b = r.get(1, (None, -1)), r.get(-1, (None, -1))
            out[idx] = (a[0], a[1], b[0], b[1])
    return out


def _hits(grid, comp, fp, cells, d):
    """{ячейка: (t вперёд, опора, t назад, опора)} для ячеек куска плиты при пролёте d."""
    if abs(d[0]) < 1e-12 or abs(d[1]) < 1e-12:
        return _sweep(grid, comp, fp, cells, d)
    nx, s = grid.nx, grid.s
    out = {}
    for idx in cells:
        x = grid.x0 + (idx % nx + 0.5) * s
        y = grid.y0 + (idx // nx + 0.5) * s
        ta, la = _hit(grid, comp, fp, x, y, d, 1.0)
        tb, lb = _hit(grid, comp, fp, x, y, d, -1.0)
        out[idx] = (ta, la, tb, lb)
    return out


def _score(H):
    """(ячеек без опоры, Σ расстояний до ближайшей опоры)."""
    lost, tsum = 0, 0.0
    for ta, la, tb, lb in H.values():
        if la < 0 and lb < 0:
            lost += 1
        else:
            tsum += min(t for t in (ta, tb) if t is not None)
    return lost, tsum


def _perp(d):
    v = (-d[1], d[0])
    if v[0] < -1e-12 or (abs(v[0]) <= 1e-12 and v[1] < 0):
        v = (-v[0], -v[1])
    return (v[0] + 0.0, v[1] + 0.0)


def assign(grid, sources, dirs, label, dist_arr, slabs=None):
    """Метки ячеек сборных плит: ближайшая годная опора вдоль пролёта (вперёд/назад).
    label/dist_arr — результат trib.assign, дописываются на месте. dirs меняется на месте:
    у плиты без заданного пролёта ('span') из двух главных направлений берётся то, при котором
    меньше ячеек без опоры, а при равенстве — пролёт короче (плиты лежат на балках/стенах).
    -> число ячеек без опоры."""
    if not any(d is not None for d in dirs):
        return 0
    comp = [trib._compile(s) for s in sources]
    fp = _footprints(grid, comp)
    cells = {}
    for idx, k in enumerate(grid.slab):
        if k >= 0 and dirs[k] is not None and grid.kind[idx] == trib.SLAB:
            cells.setdefault(k, []).append(idx)
    lost = 0
    for k in sorted(cells):
        d = dirs[k]
        H = _hits(grid, comp, fp, cells[k], d)
        if slabs is not None and not slabs[k].get('span'):
            v = _perp(d)
            Hv = _hits(grid, comp, fp, cells[k], v)
            la, sa = _score(H)
            lb, sb = _score(Hv)
            if lb < la or (lb == la and sb < sa):
                dirs[k], H = v, Hv
        for idx in cells[k]:
            ta, la, tb, lb = H[idx]
            if la < 0 and lb < 0:
                label[idx] = -1
                lost += 1
            elif lb < 0 or (la >= 0 and ta <= tb):
                label[idx], dist_arr[idx] = la, ta
            else:
                label[idx], dist_arr[idx] = lb, tb
    return lost
