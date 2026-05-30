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
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Outline, BoundingBoxIntersectsFilter, XYZ,
)

from AutoSections.convert import mm, to_ft, round_to

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


def _nearest_point(bb, p):
    """Closest point to `p` on an axis-aligned bounding box."""
    return XYZ(_clamp(p.X, bb.Min.X, bb.Max.X),
               _clamp(p.Y, bb.Min.Y, bb.Max.Y),
               _clamp(p.Z, bb.Min.Z, bb.Max.Z))


def slab_context(doc, origin, side_axis):
    """Return (side_pos, side_neg): two sorted tuples of rounded slab thicknesses.

    A side is the sign of (nearest_point - origin) . side_axis; a slab inside the
    dead-zone is added to both sides.
    """
    h, v = to_ft(ADJ_H), to_ft(ADJ_V)
    outline = Outline(XYZ(origin.X - h, origin.Y - h, origin.Z - v),
                      XYZ(origin.X + h, origin.Y + h, origin.Z + v))
    bbfilter = BoundingBoxIntersectsFilter(outline)

    floors = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_Floors)
              .WhereElementIsNotElementType()
              .WherePasses(bbfilter).ToElements())

    tol = to_ft(_SIDE_TOL)
    axis = side_axis.Normalize()
    pos, neg = [], []
    for fl in floors:
        thk = _floor_thickness_mm(fl)
        if thk <= 0:
            continue
        bb = fl.get_BoundingBox(None)
        if bb is None:
            continue
        side = (_nearest_point(bb, origin) - origin).DotProduct(axis)
        bucket = round_to(thk)
        if side > tol:
            pos.append(bucket)
        elif side < -tol:
            neg.append(bucket)
        else:                       # straddles the cut -> belongs to both
            pos.append(bucket)
            neg.append(bucket)

    return tuple(sorted(pos)), tuple(sorted(neg))


def slab_in_band(doc, origin, top_z, bottom_z, axis):
    """Floor slab crossing the vertical band near `origin`.

    Returns (thickness_mm, side) for the first floor whose bounding box
    intersects the thin column [bottom_z, top_z] around origin, where `side` is
    the signed dot of (slab_centre - origin) with `axis` (so the caller knows
    which way the slab extends). Returns (0.0, 0.0) when none is found.
    """
    h = to_ft(_COL_HALF)
    lo, hi = (bottom_z, top_z) if bottom_z <= top_z else (top_z, bottom_z)
    outline = Outline(XYZ(origin.X - h, origin.Y - h, lo),
                      XYZ(origin.X + h, origin.Y + h, hi))
    floors = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_Floors)
              .WhereElementIsNotElementType()
              .WherePasses(BoundingBoxIntersectsFilter(outline)).ToElements())
    axis = axis.Normalize()
    for fl in floors:
        thk = _floor_thickness_mm(fl)
        if thk <= 0:
            continue
        bb = fl.get_BoundingBox(None)
        if bb is None:
            continue
        center = (bb.Min + bb.Max) * 0.5
        return thk, (center - origin).DotProduct(axis)
    return 0.0, 0.0


def canonical_context(side_a, side_b):
    """Mirror-invariant key: viewing from the other side swaps the two sides, so
    pick the smaller (sorted) ordering. (a, b) and (b, a) -> same result."""
    return min((side_a, side_b), (side_b, side_a))
