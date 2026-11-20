# -*- coding: utf-8 -*-
"""What a family consists of, as plain data (Revit only).

signature(fd)                  - of an open family document
project_signature(doc, fam)    - of a family in a project (EditFamily, closed again)
file_signature(app, path)      - of an .rfa (opened in the background, closed again)
project_shared(doc)            - {guid: name} of the project's shared parameters
The comparison itself is in family_diff (plain Python, tested).
"""

import re

from Autodesk.Revit import DB

from peer_library import log


def _eid(element_id):
    v = getattr(element_id, 'Value', None)          # Revit 2024+: Int64
    return int(v) if v is not None else element_id.IntegerValue


def _spec(definition):
    try:
        return definition.GetDataType().TypeId or u''
    except Exception:
        return u''


def _labels(fd):
    """Ids of family parameters that label a dimension."""
    out = set()
    for d in DB.FilteredElementCollector(fd).OfClass(DB.Dimension):
        try:
            lab = d.FamilyLabel
            if lab is not None:
                out.add(_eid(lab.Id))
        except Exception:
            pass
    return out


def _in_formula(name, formulas):
    pat = re.compile(u'(?<![\\w]){0}(?![\\w])'.format(re.escape(name)), re.UNICODE)
    return any(pat.search(f) for f in formulas)


def signature(fd):
    fm = fd.FamilyManager
    owner = fd.OwnerFamily
    cat = owner.FamilyCategory if owner is not None else None
    # "nothing uses it" only means something for model / detail families:
    # annotation labels and rebar shapes use parameters the API does not show
    usage = cat is not None and cat.CategoryType != DB.CategoryType.Annotation \
        and cat.Name != u'Rebar Shape'
    fparams = [p for p in fm.GetParameters() if _eid(p.Id) >= 0]   # skip built-ins
    labels = _labels(fd) if usage else set()
    formulas = [p.Formula for p in fparams if p.Formula]
    params = []
    for p in fparams:
        try:
            name = p.Definition.Name
            guid = u''
            if p.IsShared:
                try:
                    guid = u'{0}'.format(p.GUID).lower()
                except Exception:
                    pass
            unused = False
            if usage and not p.IsShared and not p.IsReporting and not p.Formula:
                try:
                    assoc = p.AssociatedParameters.Size
                except Exception:
                    assoc = 1
                unused = (assoc == 0 and _eid(p.Id) not in labels
                          and not _in_formula(name, [f for f in formulas if f != p.Formula]))
            params.append({'name': name, 'shared': bool(p.IsShared), 'guid': guid,
                           'instance': bool(p.IsInstance), 'spec': _spec(p.Definition),
                           'formula': p.Formula or u'', 'reporting': bool(p.IsReporting),
                           'unused': unused})
        except Exception:
            log.write(u'signature parameter', exc=True)
    types = []
    for t in fm.Types:
        try:
            if t.Name and t.Name.strip():
                types.append(t.Name)
        except Exception:
            pass
    nested = []
    for f in DB.FilteredElementCollector(fd).OfClass(DB.Family):
        try:
            if owner is not None and f.Id == owner.Id:
                continue
            shared = None
            p = f.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED)
            if p is not None and p.HasValue:
                shared = p.AsInteger() == 1
            fc = f.FamilyCategory
            nested.append({'name': f.Name, 'category': fc.Name if fc else u'', 'shared': shared})
        except Exception:
            pass
    return {'name': owner.Name if owner is not None else u'', 'category': cat.Name if cat else u'',
            'params': params, 'types': types, 'nested': nested}


def project_signature(doc, fam, preview_png=None):
    """None when the family cannot be opened (in-place, not editable).
    preview_png: also draw a picture of it there (sig['preview'] = path or None)."""
    if fam is None or not fam.IsEditable:
        return None
    fd = None
    try:
        fd = doc.EditFamily(fam)
        sig = signature(fd)
        if preview_png:
            from peer_library import revit_family
            sig['preview'] = revit_family.make_preview(fd, preview_png, fam.Name)[0]
        return sig
    except Exception:
        log.write(u'project signature {0}'.format(fam.Name), exc=True)
        return None
    finally:
        if fd is not None:
            try:
                fd.Close(False)
            except Exception:
                log.write(u'close family {0}'.format(fam.Name), exc=True)


def file_signature(app, path):
    """An .rfa that is already open in Revit is read and left open."""
    for d in app.Documents:
        try:
            if d.IsFamilyDocument and d.PathName and d.PathName.lower() == path.lower():
                return signature(d)
        except Exception:
            pass
    from peer_library.revit_family import open_quiet
    fd = open_quiet(app, path)
    try:
        return signature(fd)
    finally:
        try:
            fd.Close(False)
        except Exception:
            log.write(u'close {0}'.format(path), exc=True)


def project_shared(doc):
    out = {}
    for e in DB.FilteredElementCollector(doc).OfClass(DB.SharedParameterElement):
        try:
            out[u'{0}'.format(e.GuidValue).lower()] = e.Name
        except Exception:
            pass
    return out
