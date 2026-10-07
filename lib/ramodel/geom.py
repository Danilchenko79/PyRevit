# -*- coding: utf-8 -*-
"""Geometry. All values in feet, as inside Revit."""
import math
from Autodesk.Revit.DB import XYZ, Line, CurveLoop

EPS = 1.0 / 304.8   # 1 mm


def xyz(x, y, z):
    return XYZ(float(x), float(y), float(z))


def flat(p, z=0.0):
    return XYZ(p.X, p.Y, z)


def dist2d(a, b):
    return math.hypot(a.X - b.X, a.Y - b.Y)


def lerp(a, b, t):
    return XYZ(a.X + (b.X - a.X) * t, a.Y + (b.Y - a.Y) * t, a.Z + (b.Z - a.Z) * t)


def closest_on_segment(p, a, b):
    """Point of segment ab nearest to p and its parameter t in [0, 1]."""
    ab = b.Subtract(a)
    l2 = ab.DotProduct(ab)
    if l2 < 1e-12:
        return a, 0.0
    t = p.Subtract(a).DotProduct(ab) / l2
    t = max(0.0, min(1.0, t))
    return lerp(a, b, t), t


def on_segment(p, a, b, tol):
    q, _ = closest_on_segment(p, a, b)
    return q.DistanceTo(p) <= tol


def on_segment_interior(p, a, b, tol):
    """p on the segment but not at its ends."""
    if p.DistanceTo(a) <= tol or p.DistanceTo(b) <= tol:
        return False
    return on_segment(p, a, b, tol)


def line_line_2d(p1, d1, p2, d2):
    """Intersection of infinite lines in plan (z taken from p1). None if parallel."""
    cross = d1.X * d2.Y - d1.Y * d2.X
    if abs(cross) < 1e-9:
        return None
    t = ((p2.X - p1.X) * d2.Y - (p2.Y - p1.Y) * d2.X) / cross
    return XYZ(p1.X + d1.X * t, p1.Y + d1.Y * t, p1.Z)


def project_to_line_2d(p, origin, d):
    s = (p.X - origin.X) * d.X + (p.Y - origin.Y) * d.Y
    return XYZ(origin.X + d.X * s, origin.Y + d.Y * s, p.Z)


def clean_polygon(pts):
    """Remove coincident vertices and "back-tracks" along one line (collapsed strips)."""
    pts = list(pts)
    changed = True
    while changed and len(pts) >= 3:
        changed = False
        n = len(pts)
        for i in range(n):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            if a.DistanceTo(b) <= EPS:
                pts.pop(i)
                changed = True
                break
            v1, v2 = b.Subtract(a), c.Subtract(b)
            l1, l2 = v1.GetLength(), v2.GetLength()
            if l2 <= EPS:
                continue
            h = abs(v1.X * v2.Y - v1.Y * v2.X) / max(l1, l2)   # deviation from a straight line
            dot = v1.X * v2.X + v1.Y * v2.Y
            if h <= EPS and dot < 0:               # forward and back almost along one line
                pts.pop(i)
                changed = True
                break
    return pts


def self_intersecting(pts):
    """Whether a closed plan polygon has intersecting or overlapping edges."""
    n = len(pts)
    segs = [(pts[i], pts[(i + 1) % n]) for i in range(n)]

    def cross(o, a, b):
        return (a.X - o.X) * (b.Y - o.Y) - (a.Y - o.Y) * (b.X - o.X)

    def on_seg(p, a, b):
        return (min(a.X, b.X) - EPS <= p.X <= max(a.X, b.X) + EPS and
                min(a.Y, b.Y) - EPS <= p.Y <= max(a.Y, b.Y) + EPS)
    tol = EPS * EPS
    for i in range(n):                 # adjacent edges overlapping each other
        a, b = segs[i]
        c = segs[(i + 1) % n][1]
        ab = XYZ(b.X - a.X, b.Y - a.Y, 0.0)
        bc = XYZ(c.X - b.X, c.Y - b.Y, 0.0)
        if abs(cross(a, b, c)) <= EPS * max(ab.GetLength(), EPS) and                 ab.X * bc.X + ab.Y * bc.Y < 0:
            return True
    for i in range(n):
        a, b = segs[i]
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            c, d = segs[j]
            d1, d2 = cross(c, d, a), cross(c, d, b)
            d3, d4 = cross(a, b, c), cross(a, b, d)
            if ((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol)) and                ((d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol)):
                return True
            for p, s0, s1, v in ((a, c, d, d1), (b, c, d, d2), (c, a, b, d3), (d, a, b, d4)):
                if abs(v) <= tol * 1e3 and on_seg(p, s0, s1):
                    return True
    return False


def point_in_polygon_2d(p, pts):
    """Point inside a plan polygon (ray casting)."""
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        a, b = pts[i], pts[j]
        if (a.Y > p.Y) != (b.Y > p.Y):
            x = (b.X - a.X) * (p.Y - a.Y) / (b.Y - a.Y) + a.X
            if p.X < x:
                inside = not inside
        j = i
    return inside


def loop_from_points(pts):
    """Closed CurveLoop from points. None if fewer than three points."""
    clean = []
    for p in pts:
        if not clean or clean[-1].DistanceTo(p) > EPS:
            clean.append(p)
    if len(clean) > 1 and clean[0].DistanceTo(clean[-1]) <= EPS:
        clean.pop()
    if len(clean) < 3:
        return None
    loop = CurveLoop()
    n = len(clean)
    for i in range(n):
        loop.Append(Line.CreateBound(clean[i], clean[(i + 1) % n]))
    return loop


def rect_loop(pa, pb, z0, z1):
    """Vertical rectangle above segment pa-pb from z0 to z1."""
    return loop_from_points([XYZ(pa.X, pa.Y, z0), XYZ(pb.X, pb.Y, z0),
                             XYZ(pb.X, pb.Y, z1), XYZ(pa.X, pa.Y, z1)])


def order_curves(curves):
    """Order sketch outline curves into a chain (reversing when needed)."""
    rest = list(curves)
    if not rest:
        return []
    chain = [rest.pop(0)]
    while rest:
        end = chain[-1].GetEndPoint(1)
        found = False
        for i, c in enumerate(rest):
            if c.GetEndPoint(0).DistanceTo(end) <= EPS * 2:
                chain.append(rest.pop(i))
                found = True
                break
            if c.GetEndPoint(1).DistanceTo(end) <= EPS * 2:
                chain.append(rest.pop(i).CreateReversed())
                found = True
                break
        if not found:
            chain.extend(rest)   # outline gap: leave as is
            break
    return chain


def curve_points(c, nseg):
    """Start point of a line, or arc points without the last one."""
    if isinstance(c, Line):
        return [c.GetEndPoint(0)]
    return [c.Evaluate(float(i) / nseg, True) for i in range(nseg)]


def loop_points(curves, nseg=8):
    pts = []
    for c in curves:
        pts.extend(curve_points(c, nseg))
    return pts


def all_lines(curves):
    for c in curves:
        if not isinstance(c, Line):
            return False
    return True


def area2d(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        s += a.X * b.Y - b.X * a.Y
    return abs(s) / 2.0


def polygon_area_3d(pts):
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        nx += a.Y * b.Z - a.Z * b.Y
        ny += a.Z * b.X - a.X * b.Z
        nz += a.X * b.Y - a.Y * b.X
    return math.sqrt(nx * nx + ny * ny + nz * nz) / 2.0


def newell_normal(pts):
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        nx += (a.Y - b.Y) * (a.Z + b.Z)
        ny += (a.Z - b.Z) * (a.X + b.X)
        nz += (a.X - b.X) * (a.Y + b.Y)
    v = XYZ(nx, ny, nz)
    ln = v.GetLength()
    return v.Divide(ln) if ln > 1e-12 else None


def project_to_plane(p, origin, n):
    d = p.Subtract(origin).DotProduct(n)
    return p.Subtract(n.Multiply(d)), abs(d)


def point_in_polygon_3d(p, pts, n, tol):
    """p in a planar polygon (within tol of the plane), including the boundary."""
    if n is None or len(pts) < 3:
        return False
    if abs(p.Subtract(pts[0]).DotProduct(n)) > tol:
        return False
    ax = max(range(3), key=lambda i: abs((n.X, n.Y, n.Z)[i]))

    def uv(q):
        c = (q.X, q.Y, q.Z)
        return [c[i] for i in range(3) if i != ax]

    u, v = uv(p)
    inside = False
    k = len(pts)
    for i in range(k):
        a = pts[i]
        b = pts[(i + 1) % k]
        if on_segment(p, a, b, tol):
            return True
        ua, va = uv(a)
        ub, vb = uv(b)
        if (va > v) != (vb > v):
            x = ua + (v - va) * (ub - ua) / (vb - va)
            if u < x:
                inside = not inside
    return inside


class Grid(object):
    """Spatial index: cubic cells of size cell (ft)."""

    def __init__(self, cell=3.0):
        self.cell = cell
        self.cells = {}

    def _rng(self, lo, hi):
        c = self.cell
        return range(int(math.floor(lo / c)), int(math.floor(hi / c)) + 1)

    def add_box(self, mn, mx, item):
        for i in self._rng(mn.X, mx.X):
            for j in self._rng(mn.Y, mx.Y):
                for k in self._rng(mn.Z, mx.Z):
                    self.cells.setdefault((i, j, k), []).append(item)

    def add_point(self, p, item):
        self.add_box(p, p, item)

    def add_points_box(self, pts, item, pad=0.0):
        mn = XYZ(min(p.X for p in pts) - pad, min(p.Y for p in pts) - pad, min(p.Z for p in pts) - pad)
        mx = XYZ(max(p.X for p in pts) + pad, max(p.Y for p in pts) + pad, max(p.Z for p in pts) + pad)
        self.add_box(mn, mx, item)

    def near(self, p, r):
        seen = set()
        res = []
        for i in self._rng(p.X - r, p.X + r):
            for j in self._rng(p.Y - r, p.Y + r):
                for k in self._rng(p.Z - r, p.Z + r):
                    for item in self.cells.get((i, j, k), ()):
                        if id(item) not in seen:
                            seen.add(id(item))
                            res.append(item)
        return res
