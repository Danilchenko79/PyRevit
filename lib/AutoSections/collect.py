# -*- coding: utf-8 -*-
"""Gather the input elements and the project types the tool needs.

Pure reads - no transaction here.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewFamilyType, ViewFamily,
    BuiltInCategory, ElementId,
)


def section_view_family_type(doc):
    """First ViewFamilyType of the Section family, or None."""
    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        if vft.ViewFamily == ViewFamily.Section:
            return vft
    return None


def title_block_type_id(doc):
    """First title block type id, or InvalidElementId (blank sheet)."""
    for tb in (FilteredElementCollector(doc)
               .OfCategory(BuiltInCategory.OST_TitleBlocks)
               .WhereElementIsElementType()):
        return tb.Id
    return ElementId.InvalidElementId


def element_level_id(elem):
    """Best-effort level of an element: its own LevelId, else its host's."""
    lid = getattr(elem, 'LevelId', None)
    if lid is not None and lid != ElementId.InvalidElementId:
        return lid
    host = getattr(elem, 'Host', None)
    if host is not None:
        hlid = getattr(host, 'LevelId', None)
        if hlid is not None and hlid != ElementId.InvalidElementId:
            return hlid
    return ElementId.InvalidElementId


def collect_targets(doc, want_windows, want_beams, level_id=None):
    """Return [(kind, element)] for the chosen categories.

    kind is 'WIN' for windows, 'BEAM' for structural framing. When `level_id`
    is given, keep only elements whose level matches it.
    """
    def on_level(elem):
        return level_id is None or element_level_id(elem) == level_id

    targets = []
    if want_windows:
        for w in (FilteredElementCollector(doc)
                  .OfCategory(BuiltInCategory.OST_Windows)
                  .WhereElementIsNotElementType().ToElements()):
            if on_level(w):
                targets.append(('WIN', w))
    if want_beams:
        for b in (FilteredElementCollector(doc)
                  .OfCategory(BuiltInCategory.OST_StructuralFraming)
                  .WhereElementIsNotElementType().ToElements()):
            if on_level(b):
                targets.append(('BEAM', b))
    return targets
