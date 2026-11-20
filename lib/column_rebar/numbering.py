# -*- coding: utf-8 -*-
"""Bar numbers of ONE drafting view (Revit, IronPython 2.7), run by the new
Create Column right after drawing, inside its transaction.

Same rules as Samples/Numeration.process_drafting_view (the old button and
RebarRenumber): every PEER_Rebar_Shape* detail of the view, equal shape /
diameter / length / A,B (either order) -> one number, in that order from 1, skipping the
numbers that name bar diameters on the drawings. Values are read as numbers
(mm), not as display strings, so the project units cannot merge or split
positions. Not imported from Samples: that module opens the pyRevit output
window at import.
"""

from Autodesk.Revit.DB import BuiltInCategory, FamilyInstance, FilteredElementCollector, StorageType

FAMILY_PREFIX = u'PEER_Rebar_Shape'
SKIP = set([8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 32])
FT = 304.8


def _type_text(el, name):
    p = el.Symbol.LookupParameter(name) if el.Symbol is not None else None
    if p is None:
        return u''
    if p.StorageType == StorageType.String:
        return p.AsString() or u''
    if p.StorageType == StorageType.Integer:
        return u'%d' % p.AsInteger()
    return p.AsValueString() or u''


def _mm(el, name):
    p = el.LookupParameter(name)
    if p is None or not p.HasValue or p.StorageType != StorageType.Double:
        return 0.0
    return round(p.AsDouble() * FT, 1)


def details(doc, view):
    out = []
    for e in FilteredElementCollector(doc, view.Id).OfCategory(BuiltInCategory.OST_DetailComponents) \
            .WhereElementIsNotElementType():
        if isinstance(e, FamilyInstance) and e.Symbol is not None and \
                (e.Symbol.FamilyName or u'').startswith(FAMILY_PREFIX):
            out.append(e)
    return out


def number_view(doc, view):
    """Writes Rebar_Number; returns {'details', 'positions', 'written'}."""
    groups = {}
    for e in details(doc, view):
        # A and B together, in either order: a hoop 280x750 and the same hoop
        # turned (750x280) are one bar
        ab = tuple(sorted((_mm(e, 'Rebar_A'), _mm(e, 'Rebar_B'))))
        key = (_type_text(e, 'Rebar_Shape'), _mm(e, 'Rebar_Diameter'), _mm(e, 'Rebar_Length'), ab)
        groups.setdefault(key, []).append(e)
    n, written = 1, 0
    for key in sorted(groups):
        while n in SKIP:
            n += 1
        for e in groups[key]:
            p = e.LookupParameter('Rebar_Number')
            if p is None or p.IsReadOnly:
                continue
            if p.StorageType == StorageType.Integer:
                p.Set(n)
            elif p.StorageType == StorageType.Double:
                p.Set(float(n))
            else:
                p.Set(u'%d' % n)
            written += 1
        n += 1
    return {'details': sum(len(v) for v in groups.values()), 'positions': len(groups), 'written': written}
