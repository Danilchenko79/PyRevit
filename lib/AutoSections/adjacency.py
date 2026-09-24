# -*- coding: utf-8 -*-
"""Classify nearby slabs onto the two sides of the cut, mirror-invariant.

Redesigned from the original (which split slabs by the sign of the dot product
between `bbox_center - origin` and a sideways axis, inside a tiny 600 mm cube):

    * Side is decided from the slab's NEAREST point to the section origin, not
      its bounding-box centre. A single large slab spanning the whole building
      no longer lands entirely on one side because of where its centre happens
      to be.
    * The search box is ANISOTROPIC - shallow horizontally but tall vertically -
      so the slab above/below the element (the one a section actually shows) is
      reached, instead of almost always coming back empty.
    * A slab straddling the cut (the element sits on top of it) counts on BOTH
      sides.

`side_axis` is supplied by geometry.side_axis (facing for windows, the in-plan
perpendicular for beams).

Links: the concrete is often a linked structural model, so the slabs are read
from a list of SOURCES (kz_links) - the host first, then every loaded link.
Every function here speaks HOST coordinates on the way in and on the way out;
the conversion happens at the source boundary. Passing no source list keeps
the old host-only behaviour.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Outline, BoundingBoxIntersectsFilter, XYZ,
)

from AutoSections.convert import mm, to_ft, round_to
import kz_links

ADJ_H = 800.0        # mm horizontal half-size of the slab search box
ADJ_V = 2000.0       # mm vertical half-size (reach the slab above / below)
_SIDE_TOL = 50.0     # mm dead-zone: within this the slab counts on both sides

_COL_HALF = 300.0    # mm half-size of the vertical search column (in plan)


def _floor_thickness_mm(floor):
    for bip in (BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM,
                BuiltInParameter.FLOOR_ATTR_DEFAULT_THICKNESS_PARAM):
        p = floor.get_Parameter(bip)
        if p and p.HasValue:
            v = p.AsDouble()
            if v and v > 1e-6:
                return mm(v)
    return 0.0


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _nearest_point(box, p):
    """Closest point to `p` on an axis-aligned box (xmin, xmax, ... zmax)."""
    return XYZ(_clamp(p.X, box[0], box[1]),
               _clamp(p.Y, box[2], box[3]),
               _clamp(p.Z, box[4], box[5]))


# ------------------------------------------------------------------- sources
# A source is (document, transform to host space, link instance); see
# lib/kz_links.py. Host coordinates are the common language: a query box goes
# down into the source's own system, whatever comes back goes up into host
# space before it is measured.

def sources_of(doc, srcs=None):
    """The given source list, or "the host plus every loaded link"."""
    if srcs:
        return srcs
    return kz_links.sources(doc)


def host_box(el, src):
    """(xmin, xmax, ymin, ymax, zmin, zmax) of an element, in host coordinates."""
    if src.is_link:
        return kz_links.host_bbox(el, src.xform)
    try:
        bb = el.get_BoundingBox(None)
    except Exception:
        return None
    if bb is None:
        return None
    return (bb.Min.X, bb.Max.X, bb.Min.Y, bb.Max.Y, bb.Min.Z, bb.Max.Z)


def source_outline(src, lo, hi):
    """The host box [lo, hi] as an Outline of the SOURCE's own coordinates.

    An Outline is axis-aligned in the document it queries, so a rotated link
    needs all eight corners transformed, not just the two given ones. The
    host gets the very same box it would have got before.
    """
    if not src.is_link:
        return Outline(lo, hi)
    xs, ys, zs = [], [], []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                q = src.to_source(XYZ(x, y, z))
                xs.append(q.X)
                ys.append(q.Y)
                zs.append(q.Z)
    return Outline(XYZ(min(xs), min(ys), min(zs)),
                   XYZ(max(xs), max(ys), max(zs)))


def _floors_near(src, lo, hi):
    """Floors of one source whose bounds meet the host box [lo, hi]."""
    return (FilteredElementCollector(src.doc)
            .OfCategory(BuiltInCategory.OST_Floors)
            .WhereElementIsNotElementType()
            .WherePasses(BoundingBoxIntersectsFilter(source_outline(src, lo, hi)))
            .ToElements())


def slab_context(doc, origin, side_axis, srcs=None):
    """Return (side_pos, side_neg): two sorted tuples of rounded slab thicknesses.

    A side is the sign of (nearest_point - origin) . side_axis; a slab inside the
    dead-zone is added to both sides. `origin` and `side_axis` are in host
    coordinates, and so is every slab box the sources give back.
    """
    h, v = to_ft(ADJ_H), to_ft(ADJ_V)
    lo = XYZ(origin.X - h, origin.Y - h, origin.Z - v)
    hi = XYZ(origin.X + h, origin.Y + h, origin.Z + v)

    tol = to_ft(_SIDE_TOL)
    axis = side_axis.Normalize()
    pos, neg = [], []
    for src in sources_of(doc, srcs):
        for fl in _floors_near(src, lo, hi):
            thk = _floor_thickness_mm(fl)
            if thk <= 0:
                continue
            box = host_box(fl, src)
            if box is None:
                continue
            side = (_nearest_point(box, origin) - origin).DotProduct(axis)
            bucket = round_to(thk)
            if side > tol:
                pos.append(bucket)
            elif side < -tol:
                neg.append(bucket)
            else:                   # straddles the cut -> belongs to both
                pos.append(bucket)
                neg.append(bucket)

    return tuple(sorted(pos)), tuple(sorted(neg))


def slab_vertical_offset(doc, origin, srcs=None):
    """Vertical offset (mm) from `origin` to the nearest slab's TOP face.

    Searches the same anisotropic box as `slab_context`; of the floors found,
    picks the one whose top face is vertically closest to `origin` and returns
    mm(slab_top_z - origin.Z). Positive = the slab top is above the origin.
    Returns None when no slab is found.

    Part of a beam's uniqueness key: two beams with the same cross-section and
    the same side context but sitting at a different height relative to their
    slab are different details and must each keep their own real section.
    """
    h, v = to_ft(ADJ_H), to_ft(ADJ_V)
    lo = XYZ(origin.X - h, origin.Y - h, origin.Z - v)
    hi = XYZ(origin.X + h, origin.Y + h, origin.Z + v)
    best_top = None
    for src in sources_of(doc, srcs):
        for fl in _floors_near(src, lo, hi):
            if _floor_thickness_mm(fl) <= 0:
                continue
            box = host_box(fl, src)
            if box is None:
                continue
            top = box[5]
            if best_top is None or abs(top - origin.Z) < abs(best_top - origin.Z):
                best_top = top
    if best_top is None:
        return None
    return mm(best_top - origin.Z)


def slab_in_band(doc, origin, top_z, bottom_z, axis, srcs=None):
    """Floor slab crossing the vertical band near `origin`.

    Returns (thickness_mm, side) for the first floor whose bounding box
    intersects the thin column [bottom_z, top_z] around origin, where `side` is
    the signed dot of (slab_centre - origin) with `axis` (so the caller knows
    which way the slab extends). Returns (0.0, 0.0) when none is found.
    """
    h = to_ft(_COL_HALF)
    z_lo, z_hi = (bottom_z, top_z) if bottom_z <= top_z else (top_z, bottom_z)
    lo = XYZ(origin.X - h, origin.Y - h, z_lo)
    hi = XYZ(origin.X + h, origin.Y + h, z_hi)
    axis = axis.Normalize()
    for src in sources_of(doc, srcs):
        for fl in _floors_near(src, lo, hi):
            thk = _floor_thickness_mm(fl)
            if thk <= 0:
                continue
            box = host_box(fl, src)
            if box is None:
                continue
            center = XYZ((box[0] + box[1]) * 0.5, (box[2] + box[3]) * 0.5,
                         (box[4] + box[5]) * 0.5)
            return thk, (center - origin).DotProduct(axis)
    return 0.0, 0.0


def canonical_context(side_a, side_b):
    """Mirror-invariant key: viewing from the other side swaps the two sides, so
    pick the smaller (sorted) ordering. (a, b) and (b, a) -> same result."""
    return min((side_a, side_b), (side_b, side_a))
