# -*- coding: utf-8 -*-
"""Column reinforcement parameters on the 3D column (Revit, IronPython 2.7).

Decided with the user 2026-11-20 (docs/COLUMNS.md, item 9):
    cover          Revit's own 'Rebar Cover - Other Faces' (cover to the stirrup)
    new shared instance parameters on Structural Columns, file column_params.txt
    (GUIDs fixed there; empty / 0 = the program decides by SI 466):
        Rebar_Stirrup Diameter       bar diameter
        Rebar_Stirrup Spacing        main spacing S
        Rebar_Stirrup Spacing Dense  spacing at joints and laps S1
        Rebar_Transverse             Auto / Ties / Hoops
        Rebar_Stirrup Label          written by the program (D8@250/100; ...)
Existing ones read as before: Rebar_Diameter, Rebar_QuantityX / Y (bars without
the 4 corners, old legend). The section size is read by the button.
"""

import os

from System import Guid
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, GroupTypeId,
                               UnitTypeId, UnitUtils)

from column_rebar import code466

PARAM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'column_params.txt')

STIRRUP_DIA = 'Rebar_Stirrup Diameter'
SPACING = 'Rebar_Stirrup Spacing'
SPACING_DENSE = 'Rebar_Stirrup Spacing Dense'
TRANSVERSE = 'Rebar_Transverse'
LABEL = 'Rebar_Stirrup Label'
NEW = (STIRRUP_DIA, SPACING, SPACING_DENSE, TRANSVERSE, LABEL)

GUIDS = {
    STIRRUP_DIA: 'eabbe27a-6c9b-4568-abce-26ebfa280a92',
    SPACING: 'f5a2ac2a-0bc5-4fe8-b5bf-a546cdcd84bd',
    SPACING_DENSE: '5242800f-7b14-44da-a656-3d6e2a183a5c',
    TRANSVERSE: 'c957aee7-2732-4d5a-9bf4-bbe0c56b9518',
    LABEL: '7e4d7dc1-43ad-4fca-afd0-318c4ff320ea',
    # existing shared parameters
    'Rebar_Diameter': '5498ba20-78b8-42d5-a4bf-f4ba6f5c16dd',
    'Rebar_QuantityX': 'de7637e2-5111-4f6b-ba9d-b8394ea5d7c3',
    'Rebar_QuantityY': '79cc3e37-3043-4df5-8f0d-fc304127fc48',
}


def _mm(ft):
    return UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Millimeters)


def _ft(mm):
    return UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters)


def param(el, name):
    """By GUID first (names differ in old projects), then by name."""
    g = GUIDS.get(name)
    if g:
        try:
            p = el.get_Parameter(Guid(g))
            if p is not None:
                return p
        except Exception:
            pass
    return el.LookupParameter(name)


def missing_params(doc):
    """New parameters not yet bound in the project."""
    have = set()
    it = doc.ParameterBindings.ForwardIterator()
    while it.MoveNext():
        have.add(it.Key.Name)
    return [n for n in NEW if n not in have]


def ensure_params(doc):
    """Binds the new parameters to Structural Columns (instance). Call inside a
    transaction. Returns the names added. The user's shared parameter file
    setting is restored."""
    need = missing_params(doc)
    if not need:
        return []
    app = doc.Application
    old = app.SharedParametersFilename
    added = []
    try:
        app.SharedParametersFilename = PARAM_FILE
        defs = app.OpenSharedParameterFile()
        cats = app.Create.NewCategorySet()
        cats.Insert(doc.Settings.Categories.get_Item(BuiltInCategory.OST_StructuralColumns))
        binding = app.Create.NewInstanceBinding(cats)
        for g in defs.Groups:
            for d in g.Definitions:
                if d.Name in need and doc.ParameterBindings.Insert(d, binding, GroupTypeId.Structural):
                    added.append(d.Name)
    finally:
        app.SharedParametersFilename = old
    return added


def _num(el, name, length=True):
    p = param(el, name)
    if p is None or not p.HasValue:
        return None
    try:
        v = p.AsDouble()
    except Exception:
        return None
    if length:
        v = _mm(v)
    return v if v > 1e-6 else None


def cover_mm(doc, col):
    """'Rebar Cover - Other Faces' of the column, mm (None if not set)."""
    p = col.get_Parameter(BuiltInParameter.CLEAR_COVER_OTHER)
    if p is None:
        return None
    ct = doc.GetElement(p.AsElementId())
    return _mm(ct.CoverDistance) if ct is not None else None


def read_column(doc, col):
    """Input of code466.design for one 3D column, mm. Keys with None are
    left for the program (or reported as missing by the caller)."""
    qx = param(col, 'Rebar_QuantityX')
    qy = param(col, 'Rebar_QuantityY')
    tr = param(col, TRANSVERSE)
    nb = nh = None
    if qx is not None and qx.HasValue and qy is not None and qy.HasValue:
        nb, nh = code466.from_old_counts(int(round(qx.AsDouble())), int(round(qy.AsDouble())))
    return {
        # section size: the caller (read_section_size of the button handles B/H, b/h, ...)
        'cover': cover_mm(doc, col),
        'bar_dia': _num(col, 'Rebar_Diameter'),
        'nb': nb, 'nh': nh,
        'stirrup_dia': _num(col, STIRRUP_DIA),
        'spacing': _num(col, SPACING),
        'dense': _num(col, SPACING_DENSE),
        'transverse': code466.mode_from_text(tr.AsString() if tr is not None else None),
    }


def write_label(col, result):
    """Rebar_Stirrup Label from the design result. Inside a transaction."""
    p = param(col, LABEL)
    if p is not None and not p.IsReadOnly:
        p.Set(code466.summary(result))
        return True
    return False
