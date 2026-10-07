# -*- coding: utf-8 -*-
"""Плоская геометрия на кортежах (мм). Без Revit API — IronPython 2.7 и CPython 3."""
import math


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def length(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1])


def unit(a):
    L = length(a)
    return (a[0] / L, a[1] / L) if L > 1e-9 else (1.0, 0.0)


def dist(a, b):
    return length(sub(a, b))


def seg_param(p, a, u, L):
    """(s, перпендикулярное расстояние) проекции p на отрезок a + s·u, s ∈ [0, L] без обрезки."""
    d = sub(p, a)
    s = dot(d, u)
    return s, abs(cross(u, d))


def dist_to_seg(p, a, u, L):
    d = sub(p, a)
    s = dot(d, u)
    if s < 0.0:
        s = 0.0
    elif s > L:
        s = L
    return length((d[0] - s * u[0], d[1] - s * u[1]))


def line_intersection(p1, u1, p2, u2):
    """Точка пересечения прямых p1 + t·u1 и p2 + s·u2 или None для параллельных."""
    den = cross(u1, u2)
    if abs(den) < 1e-9:
        return None
    t = cross(sub(p2, p1), u2) / den
    return (p1[0] + t * u1[0], p1[1] + t * u1[1])


def angle_deg(u1, u2):
    """Угол между направлениями 0..180."""
    c = max(-1.0, min(1.0, dot(u1, u2)))
    return math.degrees(math.acos(c))


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def point_in_poly(p, pts):
    x, y = p
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def split_loops(loops):
    """Контуры одной грани -> [(outer, [holes])]. Контур — проём, если лежит внутри нечётного
    числа других; проём относится к наименьшему наружному, в котором лежит.
    (В Revit одна плоская грань может содержать несколько несвязанных кусков.)"""
    loops = [lp for lp in loops if len(lp) >= 3]
    areas = [poly_area(lp) for lp in loops]
    order = sorted(range(len(loops)), key=lambda i: -areas[i])
    parents = {}
    for i in order:
        probe = loops[i][0]
        parents[i] = [j for j in order if j != i and areas[j] > areas[i] and point_in_poly(probe, loops[j])]
    outers = [i for i in order if len(parents[i]) % 2 == 0]
    res = dict((i, []) for i in outers)
    for i in order:
        if len(parents[i]) % 2 == 1:
            host = min((j for j in parents[i] if j in res), key=lambda j: areas[j])
            res[host].append(loops[i])
    return [(loops[i], res[i]) for i in outers]


def rect_dist(p, c, u, hx, hy):
    """Расстояние от точки до прямоугольника (центр c, ось u, полуразмеры hx по u, hy поперёк)."""
    dx, dy = p[0] - c[0], p[1] - c[1]
    a = abs(dx * u[0] + dy * u[1]) - hx
    b = abs(-dx * u[1] + dy * u[0]) - hy
    a = a if a > 0.0 else 0.0
    b = b if b > 0.0 else 0.0
    return math.sqrt(a * a + b * b)
