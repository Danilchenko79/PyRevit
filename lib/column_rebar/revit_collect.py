# -*- coding: utf-8 -*-
"""3D columns of the model -> plain dicts for grouping / code466 (Revit,
IronPython 2.7). Moved from the old Create Column script (read_section_size,
column_shape, the problem lists) and extended with the parameters of item 9.

Every function takes doc and reads the model at the moment it is called
(the new window asks again on Refresh / before drawing - nothing goes stale).
"""

from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter, FilteredElementCollector

from column_rebar import code466, grouping, revit_params

FT = 304.8
PARAM_LEVEL = 'PR_Level'
PARAM_MARK = 'Mark'
NO_LEVEL = u'No Level'

# width / height names of other column families, tried in this order after
# the shared parameters (instance first, then type)
SIZE_PAIRS = [
    ('PR_Dimension_Width', 'PR_Dimension_Height'),
    ('GeneralWidth', 'GeneralDepth'),       # PEER library 3D columns (shared, on the type)
    ('B', 'H'), ('b', 'h'), ('Width', 'Depth'), ('Width', 'Height'),
    ('Column_B', 'Column_H'), ('PR_B', 'PR_H'),
]
GUID_W = '8f2e4f93-9472-4941-a65d-0ac468fd6a5d'
GUID_H = 'da753fe3-ecfa-465b-9a2c-02f55d0c2ff1'


def columns(doc):
    return list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralColumns)
                .WhereElementIsNotElementType())


def level_of(col):
    p = col.LookupParameter(PARAM_LEVEL)
    return (p.AsString() or u'').strip() if p is not None and p.HasValue else u''


def levels(doc):
    return sorted(set(level_of(c) for c in columns(doc)) - set([u'']))


def column_shape(ctype):
    """RECT / ROUND2 / ROUND1 by the 3D family name (PEER-Concrete-Column-
    Rectangular [Rounded [One Side]]); '-' and '_' count as spaces."""
    try:
        n = (ctype.FamilyName or u'').lower().replace(u'-', u' ').replace(u'_', u' ')
    except Exception:
        n = u''
    if u'rounded' in n:
        return code466.ROUND1 if u'one side' in n else code466.ROUND2
    return code466.RECT


def _double(el, name):
    if el is None:
        return None
    p = el.LookupParameter(name)
    try:
        if p is not None and str(p.StorageType) == 'Double' and p.HasValue:
            return p.AsDouble()
    except Exception:
        pass
    return None


def _guid_double(els, guid):
    from System import Guid
    for el in els:
        if el is None:
            continue
        try:
            p = el.get_Parameter(Guid(guid))
            if p is not None and p.HasValue and p.AsDouble():
                return p.AsDouble()
        except Exception:
            pass
    return None


def section_size(col, ctype):
    """(b, h) in mm; (0, 0) when nothing is found."""
    w, h = _guid_double((col, ctype), GUID_W), _guid_double((col, ctype), GUID_H)
    if w and h:
        return w * FT, h * FT
    for wn, hn in SIZE_PAIRS:
        w = _double(col, wn) or _double(ctype, wn)
        h = _double(col, hn) or _double(ctype, hn)
        if w and h:
            return w * FT, h * FT
    return 0.0, 0.0


def top_level(doc, col):
    try:
        p = col.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
        if p is not None and p.HasValue:
            lv = doc.GetElement(p.AsElementId())
            if lv is not None:
                return lv.Name
    except Exception:
        pass
    return u'(no top level)'


def read(doc, col):
    """One column -> dict for grouping.make_groups + the design inputs.
    qb / qh as the families keep them (RECT: without the corners)."""
    ctype = doc.GetElement(col.GetTypeId())
    b, h = section_size(col, ctype)
    shape = column_shape(ctype)
    if shape != code466.RECT and h < b:
        b, h = h, b                      # rounded: b is the short side (diameter of the end)
    mp = col.LookupParameter(PARAM_MARK)
    qx = revit_params.param(col, 'Rebar_QuantityX')
    qy = revit_params.param(col, 'Rebar_QuantityY')
    inp = revit_params.read_column(doc, col)
    return {
        'id': col.Id, 'mark': mp.AsString() if mp is not None and mp.HasValue else None,
        'shape': shape, 'b': b, 'h': h,
        'qb': qx.AsDouble() if qx is not None and qx.HasValue else 0.0,
        'qh': qy.AsDouble() if qy is not None and qy.HasValue else 0.0,
        'dia': inp['bar_dia'] or 0.0,
        'cover': inp['cover'] or 25.0,
        'stirrup_dia': inp['stirrup_dia'], 'spacing': inp['spacing'], 'dense': inp['dense'],
        'transverse': inp['transverse'],
        'top_level': top_level(doc, col),
        'level': level_of(col),
    }


def level_columns(doc, level):
    return [read(doc, c) for c in columns(doc) if level_of(c) == level]


def no_level_columns(doc):
    return [read(doc, c) for c in columns(doc) if not level_of(c)]


def design_args(g):
    """grouping group -> code466.design keyword arguments (mm)."""
    shape = g['shape']
    if shape == code466.RECT:
        nb, nh = code466.from_old_counts(g['qb'], g['qh'])
    else:
        nb, nh = int(round(g['qb'])), int(round(g['qh']))
    return dict(shape=shape, b=g['b'], h=g['h'], cover=g.get('cover') or 25.0,
                bar_dia=g['dia'], nb=nb, nh=nh, stirrup_dia=g.get('stirrup_dia'),
                spacing=g.get('spacing'), dense=g.get('dense'),
                transverse=g.get('transverse') or code466.AUTO)


def design(g):
    a = design_args(g)
    return code466.design(a['shape'], a['b'], a['h'], a['cover'], a['bar_dia'], a['nb'], a['nh'],
                          stirrup_dia=a['stirrup_dia'], spacing=a['spacing'], dense=a['dense'],
                          transverse=a['transverse'])
