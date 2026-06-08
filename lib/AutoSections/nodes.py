# -*- coding: utf-8 -*-
"""Turn one element into a section 'node': the geometry to draw + a uniqueness key.

Window node (the detail the user wants): a thin vertical slice at the window's
plan position, cropped to the spandrel between two STACKED windows so that
neither window appears - only the floor slab and the concrete wall between them.

    top crop    = sill of THIS floor's window   (bottom of the current opening)
    bottom crop = head of the window BELOW       (top of the opening one floor down)

Uniqueness = wall thickness + slab thickness + spandrel height. The window size
and family are deliberately NOT part of the key: the windows are cropped out, so
two different windows over the same concrete detail share one real section and
get reference markers instead.

Beam node: the transverse cross-section (perpendicular to the axis). Uniqueness =
cross-section (b x h) + which side(s) carry a slab (+ slab thickness, mirror-
invariant) + the beam's vertical offset to its slab. The family/type name is NOT
part of the key, so two look-alike beams collapse onto one real section.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, Wall,
    Outline, BoundingBoxIntersectsFilter, XYZ,
)

from AutoSections.convert import mm, to_ft, round_to
from AutoSections import geometry as G
from AutoSections import adjacency as A
from AutoSections import params as P

WIN_COLUMN_TOL = 400.0    # mm XY proximity to count as the same window stack
FALLBACK_BAND = 1500.0    # mm spandrel height used when there is no window below
DEFAULT_WALL = 250.0      # mm wall thickness fallback when host is not a wall
WIN_REVEAL = 500.0        # mm extend up / down past the openings so a bit of
                          # each window shows for context


# ---------------------------------------------------------------- window node

def _opening_z(elem):
    bb = elem.get_BoundingBox(None)
    if bb is None:
        return None
    return bb.Min.Z, bb.Max.Z


def _wall_thickness_mm(win):
    host = getattr(win, 'Host', None)
    if isinstance(host, Wall):
        try:
            return mm(host.Width)
        except Exception:
            pass
    return 0.0


def _window_below_head_z(doc, win, origin, sill_z):
    """Top Z (feet) of the nearest window stacked under this one, else None."""
    r = to_ft(WIN_COLUMN_TOL)
    deep = to_ft(20000.0)
    outline = Outline(XYZ(origin.X - r, origin.Y - r, sill_z - deep),
                      XYZ(origin.X + r, origin.Y + r, sill_z - to_ft(1.0)))
    wins = (FilteredElementCollector(doc)
            .OfCategory(BuiltInCategory.OST_Windows)
            .WhereElementIsNotElementType()
            .WherePasses(BoundingBoxIntersectsFilter(outline)).ToElements())
    best = None
    for w in wins:
        if w.Id == win.Id:
            continue
        oz = _opening_z(w)
        if oz is None:
            continue
        head = oz[1]
        if head < sill_z and (best is None or head > best):
            best = head
    return best


def window_node(doc, win):
    origin, view_dir, facing = G.section_frame(win, 'WIN')
    if origin is None:
        return None

    oz = _opening_z(win)
    sill_z = oz[0] if oz is not None else origin.Z
    head_lower = _window_below_head_z(doc, win, origin, sill_z)

    reveal = to_ft(WIN_REVEAL)
    top_z = sill_z + reveal                          # past this floor's sill
    bottom_z = ((head_lower - reveal) if head_lower is not None
                else sill_z - to_ft(FALLBACK_BAND))  # past the lower head
    if bottom_z >= top_z:                            # guard a degenerate band
        bottom_z = top_z - to_ft(FALLBACK_BAND)

    wall_thk = _wall_thickness_mm(win) or DEFAULT_WALL
    slab_thk, slab_side = A.slab_in_band(doc, origin, top_z, bottom_z, facing)
    band = mm(top_z - bottom_z)

    # which way to widen at the slab: view +X = -facing, so a slab on the
    # -facing side widens +X ('pos'); on the +facing side widens -X ('neg').
    widen = None
    if slab_thk > 0:
        widen = 'neg' if slab_side > 0 else 'pos'

    key = ('WIN', round_to(wall_thk), round_to(slab_thk), round_to(band))
    desc = {'kind': 'WIN', 'prefix': 'W_SEC',
            'origin': origin, 'view_dir': view_dir,
            'top_z': top_z, 'bottom_z': bottom_z, 'wall_thk': wall_thk,
            'widen': widen,
            'name_w': round_to(wall_thk), 'name_h': round_to(band), 'key': key}
    return key, desc


# ---------------------------------------------------------------- beam node

def beam_node(doc, beam):
    origin, view_dir, side = G.section_frame(beam, 'BEAM')
    if origin is None:
        return None
    b = P.dim_mm(beam, [BuiltInParameter.FAMILY_WIDTH_PARAM]) or 300.0
    h = P.dim_mm(beam, [BuiltInParameter.FAMILY_HEIGHT_PARAM]) or 600.0

    # which side(s) carry a slab. side = +X of the cut (geometry.make_section_box
    # right axis), so sa -> +X (widen_pos), sb -> -X (widen_neg).
    sa, sb = A.slab_context(doc, origin, side)
    ctx = A.canonical_context(sa, sb)

    # vertical position of the beam relative to its slab (floor-to-beam): two
    # beams at different heights under the same slab are different details.
    v_off = A.slab_vertical_offset(doc, origin)
    v_key = round_to(v_off) if v_off is not None else None

    # uniqueness = pure geometry (cross-section + slab side context + vertical
    # drop), NOT the family/type name: two look-alike beams share one real
    # section and the rest get reference markers.
    key = ('BEAM', round_to(b), round_to(h), ctx, v_key)
    desc = {'kind': 'BEAM', 'prefix': 'B_SEC',
            'origin': origin, 'view_dir': view_dir,
            'b': b, 'h': h,
            'widen_pos': bool(sa), 'widen_neg': bool(sb),
            'name_w': round_to(b), 'name_h': round_to(h), 'key': key}
    return key, desc


def analyze(doc, kind, elem):
    """Return (key, desc) for the element, or None if it has no usable location."""
    return window_node(doc, elem) if kind == 'WIN' else beam_node(doc, elem)
