# -*- coding: utf-8 -*-
"""Small parameter reads shared by the node builders."""

from Autodesk.Revit.DB import Element

from AutoSections.convert import mm


def dim_mm(elem, bips):
    """First non-zero value (mm) among a list of BuiltInParameters."""
    for bip in bips:
        p = elem.get_Parameter(bip)
        if p and p.HasValue:
            v = p.AsDouble()
            if v and v > 1e-6:
                return mm(v)
    return 0.0


def type_name(doc, elem):
    sym = doc.GetElement(elem.GetTypeId())
    try:
        return Element.Name.__get__(sym)
    except Exception:
        return str(elem.GetTypeId().IntegerValue)
