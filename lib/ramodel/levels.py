# -*- coding: utf-8 -*-
"""Slab axes: elevations to which walls, columns and beams are snapped."""
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory, BuiltInParameter, Floor)
from ramodel.geom import EPS


class SlabAxis(object):
    """A single flat load-bearing slab: top, bottom, axis and plan extent."""

    def __init__(self, floor, top, t, bb, mode):
        self.floor = floor
        self.id = floor.Id
        self.top = top
        self.t = t
        self.bot = top - t
        self.z = top if mode == 'top' else top - t / 2.0
        self.xmin, self.ymin = bb.Min.X, bb.Min.Y
        self.xmax, self.ymax = bb.Max.X, bb.Max.Y
        self.z0 = self.z             # own axis elevation (before merging)
        self.merged_from = None

    def covers(self, xmin, ymin, xmax, ymax, margin):
        return not (xmax < self.xmin - margin or xmin > self.xmax + margin or
                    ymax < self.ymin - margin or ymin > self.ymax + margin)

    def dist_to(self, z):
        """Distance from elevation z to the slab body (0 - within the thickness). Measured
        from the physical top and bottom, not from the axis: after merging slabs into
        one plane the axis may be hundreds of mm away from its own slab."""
        if self.bot - EPS <= z <= self.top + EPS:
            return 0.0
        return min(abs(z - self.bot), abs(z - self.top))


def is_structural_floor(f):
    """Load-bearing slab not thinner than min_slab_thickness_mm (screeds and finishes are discarded)."""
    p = f.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
    if not (p and p.AsInteger() == 1):
        return False
    from ramodel.config import RUNTIME
    return floor_thickness(f) * 304.8 >= RUNTIME['min_slab_thickness_mm'] - 0.5


def floor_thickness(f):
    p = f.get_Parameter(BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM)
    return p.AsDouble() if p else 0.0


def collect(doc, cfg):
    """(axes, sloped): axes of flat load-bearing slabs in ascending order and a list of sloped slabs."""
    axes, sloped = [], []
    floors = (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors)
              .WhereElementIsNotElementType())
    for f in floors:
        if not isinstance(f, Floor) or not is_structural_floor(f):
            continue
        bb = f.get_BoundingBox(None)
        t = floor_thickness(f)
        if bb is None or t <= 0:
            continue
        if (bb.Max.Z - bb.Min.Z) > t + 5 * EPS:
            sloped.append(f)
            continue
        axes.append(SlabAxis(f, bb.Max.Z, t, bb, cfg['slab_axis_mode']))
    axes.sort(key=lambda a: a.z)
    merge_close(axes, float(cfg.get('axis_merge_tol_mm', 0)) * EPS)
    return axes, sloped


MERGE_GAP = 1.0 / 0.3048     # slabs of one storey: plan extents closer than 1 m


def merge_close(axes, tol):
    """Slabs whose axis elevations are within tol of the storey's main slab get its elevation.

    The main slab is the largest by extent. Only slabs adjacent in plan are attached to
    it (chained through already attached ones), so another building block at a close
    elevation keeps its own elevation. This way slabs of different thickness, balconies
    and floor steps of one storey give a single row of nodes.
    """
    if tol <= 0:
        return
    done = set()
    for main in sorted(axes, key=lambda a: -(a.xmax - a.xmin) * (a.ymax - a.ymin)):
        if id(main) in done:
            continue
        done.add(id(main))
        cluster = [main]
        grown = True
        while grown:
            grown = False
            for a in axes:
                if id(a) in done or abs(a.z0 - main.z0) > tol:
                    continue
                if any(c.covers(a.xmin, a.ymin, a.xmax, a.ymax, MERGE_GAP) for c in cluster):
                    done.add(id(a))
                    cluster.append(a)
                    grown = True
        for a in cluster[1:]:
            if abs(a.z0 - main.z0) > EPS:
                a.merged_from = a.z0
                a.z = main.z0
    axes.sort(key=lambda a: a.z)


def near(axes, xmin, ymin, xmax, ymax, margin):
    """Slabs whose plan extent overlaps the rectangle."""
    return [a for a in axes if a.covers(xmin, ymin, xmax, ymax, margin)]


def snap(z, axes, tol):
    """Slab whose body is within tol of elevation z (on a tie - the one with the nearest axis).
    None - no such slab."""
    best, best_k = None, None
    for a in axes:
        d = a.dist_to(z)
        if d > tol:
            continue
        k = (d, abs(a.z - z))
        if best is None or k < best_k:
            best, best_k = a, k
    return best


def between(axes, z0, z1):
    """Axes strictly between z0 and z1, one per elevation."""
    res, seen = [], set()
    for a in axes:
        if z0 + 10 * EPS < a.z < z1 - 10 * EPS:
            key = int(round(a.z / EPS))
            if key not in seen:
                seen.add(key)
                res.append(a)
    return res


def by_floor(axes):
    d = {}
    for a in axes:
        d[a.id.ToString()] = a
    return d
