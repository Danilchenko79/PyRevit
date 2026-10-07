# -*- coding: utf-8 -*-
"""Small helpers: units, ElementId, comment tags, materials."""
from Autodesk.Revit.DB import (BuiltInParameter, Element, ElementId, StorageType)
from ramodel import TAG

FT = 0.3048


def m(v):
    """Feet -> metres."""
    return v * FT


def mm(v):
    """Feet -> mm (integer)."""
    return int(round(v * 304.8))


def fmt_pt(p):
    """Point in metres for the report."""
    return u'({:.3f}; {:.3f}; {:.3f})'.format(p.X * FT, p.Y * FT, p.Z * FT)


def eid_int(eid):
    """ElementId -> int (Revit 2024+: Value, earlier IntegerValue)."""
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def is_valid_id(eid):
    return eid is not None and eid != ElementId.InvalidElementId


def elem_name(el):
    """Element or type name (FamilySymbol .Name does not always work in IronPython)."""
    try:
        return Element.Name.GetValue(el)
    except Exception:
        try:
            return el.Name
        except Exception:
            return u''


def _comment_param(el):
    p = el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is None:
        # parameter name in English / Russian Revit UI
        for name in ('Comments', u'\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0438'):
            p = el.LookupParameter(name)
            if p is not None:
                break
    return p


def get_comment(el):
    try:
        p = _comment_param(el)
        return (p.AsString() or u'') if p else u''
    except Exception:
        return u''


def set_comment(el, text):
    try:
        p = _comment_param(el)
        if p and not p.IsReadOnly and p.StorageType == StorageType.String:
            p.Set(text)
            return True
    except Exception:
        pass
    return False


def is_tool_element(el):
    return get_comment(el).startswith(TAG)


def tag_role(el):
    """Role from tag 'RA:LINTEL b=200 h=700' -> 'LINTEL'."""
    c = get_comment(el)
    if not c.startswith(TAG):
        return u''
    return c[len(TAG):].split(u' ')[0]


def tag_values(el):
    """Numbers from tag: 'RA:LINTEL b=200 h=700' -> {'b': 200.0, 'h': 700.0}."""
    res = {}
    c = get_comment(el)
    if not c.startswith(TAG):
        return res
    for part in c.split()[1:]:
        if u'=' in part:
            k, v = part.split(u'=', 1)
            try:
                res[k] = float(v)
            except ValueError:
                pass
    return res


def material_id(el):
    """Structural material of a physical element."""
    try:
        p = el.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM)
        if p is not None:
            mid = p.AsElementId()
            if is_valid_id(mid):
                return mid
    except Exception:
        pass
    try:
        mid = el.StructuralMaterialId
        if is_valid_id(mid):
            return mid
    except Exception:
        pass
    # Walls and slabs: material is set in the type (type parameter or structural layer of the compound structure)
    try:
        et = el.Document.GetElement(el.GetTypeId())
    except Exception:
        et = None
    if et is not None:
        try:
            p = et.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM)
            if p is not None:
                mid = p.AsElementId()
                if is_valid_id(mid):
                    return mid
        except Exception:
            pass
        try:
            cs = et.GetCompoundStructure()
            if cs is not None:
                idx = cs.StructuralMaterialIndex
                if idx < 0:
                    idx = cs.GetFirstCoreLayerIndex()
                if idx >= 0:
                    mid = cs.GetLayers()[idx].MaterialId
                    if is_valid_id(mid):
                        return mid
        except Exception:
            pass
    return ElementId.InvalidElementId


def material_kind(doc, mat_id):
    """'concrete' | 'steel' | 'wood' | 'other' | None from the material's structural asset."""
    if not is_valid_id(mat_id):
        return None
    mat = doc.GetElement(mat_id)
    if mat is None:
        return None
    try:
        pse = doc.GetElement(mat.StructuralAssetId)
        cls = str(pse.GetStructuralAsset().StructuralAssetClass)
        return {'Concrete': 'concrete', 'Metal': 'steel', 'Wood': 'wood'}.get(cls, 'other')
    except Exception:
        pass
    cls = (getattr(mat, 'MaterialClass', None) or u'').lower()
    # material class names from English / Russian Revit UI ('beton', 'stal', 'metall')
    if u'\u0431\u0435\u0442\u043e\u043d' in cls or 'concrete' in cls:
        return 'concrete'
    if u'\u0441\u0442\u0430\u043b\u044c' in cls or u'\u043c\u0435\u0442\u0430\u043b\u043b' in cls or 'steel' in cls or 'metal' in cls:
        return 'steel'
    return 'other'
