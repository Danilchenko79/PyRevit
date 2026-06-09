# -*- coding: utf-8 -*-
"""Floor (slab) helpers for the 'top of slab' (overcant) elevation mode.

A floor is linked to a level through its reference level. The user maps that
Revit level to a PR_Level number elsewhere; here we only need the geometric
top elevation of the slab.

Top-of-slab elevation = Level.Elevation + 'Height Offset From Level'.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, Floor, BuiltInCategory,
    BuiltInParameter, ElementId,
)


def _floor_level_id(floor):
    p = floor.get_Parameter(BuiltInParameter.LEVEL_PARAM)
    if p:
        return p.AsElementId()
    try:
        return floor.LevelId
    except Exception:
        return ElementId.InvalidElementId


def _floor_height_offset(floor):
    p = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
    return p.AsDouble() if p else 0.0


def get_floors_on_level(doc, level):
    """All Floor elements whose reference level is `level`."""
    floors = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_Floors)
              .WhereElementIsNotElementType()
              .ToElements())
    return [f for f in floors
            if isinstance(f, Floor) and _floor_level_id(f) == level.Id]


def floor_top_elevation(doc, floor):
    """Top-of-slab elevation (internal feet) = level elevation + height offset."""
    level = doc.GetElement(_floor_level_id(floor))
    base = level.Elevation if level else 0.0
    return base + _floor_height_offset(floor)


def slab_options_for_level(doc, level):
    """Floors on a level as (floor, top_elev_internal) sorted by elevation desc.

    Used to let the user pick the right slab when a level carries several.
    """
    opts = [(f, floor_top_elevation(doc, f)) for f in get_floors_on_level(doc, level)]
    return sorted(opts, key=lambda o: o[1], reverse=True)
