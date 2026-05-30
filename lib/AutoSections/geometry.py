# -*- coding: utf-8 -*-
"""Where a section sits and which way it looks, plus the oriented box and crop.

Conventions (BoundingBoxXYZ transform of a ViewSection):
    BasisX = right   (horizontal width of the view)
    BasisY = up      (global Z)
    BasisZ = view_dir (the look direction; the cut plane is perpendicular to it)

Both kinds produce a true CROSS-section: the cut plane is perpendicular to the
"long axis" of the situation, and we look ALONG that axis.

Window: look ALONG the wall -> the plane cuts across the wall, so the view shows
        wall thickness x height with the window in section (head / sill / lintel)
        and the slabs above / below. (The previous version looked through the
        wall along facing, i.e. an elevation OF the window.)
Beam:   look ALONG the beam axis -> the plane cuts the beam transversally.

`side_axis` is the in-plane axis used to split adjacent slabs into two sides:
window -> facing (inside vs outside), beam -> perpendicular to the beam in plan
(left vs right).
"""

from Autodesk.Revit.DB import (
    XYZ, Transform, BoundingBoxXYZ, LocationCurve, LocationPoint,
)

from AutoSections.convert import to_ft


def section_frame(elem, kind):
    """Return (origin, view_dir, side_axis), or (None, None, None) if unusable.

    view_dir - the look direction; the cut plane is perpendicular to it.
    side_axis - in-plane axis that classifies adjacent slabs (see module doc).
    """
    loc = elem.Location

    if kind == 'BEAM' and isinstance(loc, LocationCurve):
        crv = loc.Curve
        p0, p1 = crv.GetEndPoint(0), crv.GetEndPoint(1)
        axis = (p1 - p0)
        if axis.GetLength() < 1e-9:
            return None, None, None
        axis = axis.Normalize()
        side = XYZ.BasisZ.CrossProduct(axis)
        if side.GetLength() < 1e-9:
            side = XYZ.BasisX
        return (p0 + p1) * 0.5, axis, side.Normalize()

    if kind == 'WIN' and isinstance(loc, LocationPoint):
        try:
            facing = elem.FacingOrientation.Normalize()
        except Exception:
            facing = XYZ.BasisX
        flat = XYZ(facing.X, facing.Y, 0.0)        # facing, flattened to plan
        if flat.GetLength() < 1e-9:
            flat = XYZ.BasisX
        facing = flat.Normalize()
        wall_dir = XYZ.BasisZ.CrossProduct(facing)  # along the wall = view dir
        if wall_dir.GetLength() < 1e-9:
            wall_dir = XYZ.BasisY
        return loc.Point, wall_dir.Normalize(), facing

    return None, None, None


def make_section_box(origin, view_dir, x_neg_mm, x_pos_mm, y_down_mm, y_up_mm,
                     z_half_mm):
    """Oriented section box from explicit local extents (mm).

    X and Y are each given as two separate extents so the cut need not sit at
    the centre of the frame - a window section is widened toward the slab on one
    side, and its vertical band is set by the windows above / below. CreateSection
    crops the view to this box, so no extra crop pass is needed.

        BasisX = right (across)   x_neg_mm to the left, x_pos_mm to the right
        BasisY = up (global Z)    y_down_mm below origin, y_up_mm above
        BasisZ = view_dir         half-extent z_half_mm (slice depth)
    """
    xn = to_ft(x_neg_mm)
    xp = to_ft(x_pos_mm)
    yd = to_ft(y_down_mm)
    yu = to_ft(y_up_mm)
    z = to_ft(z_half_mm)

    vdir = view_dir.Normalize()
    up = XYZ.BasisZ
    right = up.CrossProduct(vdir)
    if right.GetLength() < 1e-9:        # vdir parallel to Z (e.g. vertical beam)
        right = XYZ.BasisX
    right = right.Normalize()
    up = vdir.CrossProduct(right).Normalize()

    t = Transform.Identity
    t.Origin = origin
    t.BasisX = right
    t.BasisY = up
    t.BasisZ = vdir

    box = BoundingBoxXYZ()
    box.Transform = t
    box.Min = XYZ(-xn, -yd, -z)
    box.Max = XYZ(xp, yu, z)
    return box
