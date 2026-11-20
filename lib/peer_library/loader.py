# -*- coding: utf-8 -*-
"""Families in the project: status against the library, load, update, place.

A family in the project = Family whose name equals the library ID
(rebar shapes: RebarShape with that name). Its version = PEER_Version of any
of its types. Works no matter how the family got into the project.
"""

import clr
from Autodesk.Revit import DB

from peer_library import log, strings
from peer_library.revit_family import Guard, VERSION_PARAM

MISSING, CURRENT, OUTDATED, UNKNOWN, NEWER = 'missing', 'current', 'outdated', 'unknown', 'newer'


# ---- what is in the project ------------------------------------------------
def project_families(doc):
    """name.lower() -> project version (int) or None (no PEER_Version)."""
    out = {}
    for fam in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        try:
            if fam.IsInPlace:
                continue
        except Exception:
            pass
        out[fam.Name.lower()] = _family_version(doc, fam)
    try:
        from Autodesk.Revit.DB.Structure import RebarShape
        for rs in DB.FilteredElementCollector(doc).OfClass(RebarShape):
            p = rs.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
            name = p.AsString() if p is not None else None
            if name:
                out.setdefault(name.lower(), None)
    except Exception:
        pass
    return out


def project_family_list(doc):
    """[(family name, category name, PEER_Version or None)] of loadable families."""
    out = []
    for fam in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        try:
            if fam.IsInPlace:
                continue
            cat = fam.FamilyCategory
            out.append((fam.Name, cat.Name if cat else u'', _family_version(doc, fam)))
        except Exception:
            continue
    out.sort(key=lambda r: (r[1].lower(), r[0].lower()))
    return out


def _family_version(doc, fam):
    for sid in fam.GetFamilySymbolIds():
        sym = doc.GetElement(sid)
        p = sym.LookupParameter(VERSION_PARAM) if sym else None
        if p is not None and p.HasValue and p.StorageType == DB.StorageType.Integer:
            return p.AsInteger()
    return None


def status(card, in_project):
    """(code, project_version, label)."""
    key = card['id'].lower()
    if key not in in_project:
        return MISSING, None, strings.ST_MISSING
    pv = in_project[key]
    lv = card.get('version') or 0
    if pv is None:
        return UNKNOWN, None, strings.ST_UNKNOWN
    if pv == lv:
        return CURRENT, pv, u'{0} (v{1})'.format(strings.ST_CURRENT, pv)
    if pv < lv:
        return OUTDATED, pv, strings.ST_OUTDATED.format(pv, lv)
    return NEWER, pv, strings.ST_NEWER.format(pv, lv)


# ---- loading ---------------------------------------------------------------
class LoadOptions(DB.IFamilyLoadOptions):
    """Existing family: reload; parameter values kept unless overwrite=True.
    Nested shared family: the version from the loaded file wins (logged)."""

    def __init__(self, overwrite=False, family_id=u''):
        self.overwrite = bool(overwrite)
        self.family_id = family_id

    # Out-parameters: IronPython hands them in as references (StrongBox) - set
    # .Value (as pyRevit's own revit.db.create does). Some IronPython builds
    # instead expect them as extra return values - then return a tuple.
    used = None              # 'value' / 'tuple' - which convention IronPython used

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        if hasattr(overwriteParameterValues, 'Value'):
            overwriteParameterValues.Value = self.overwrite
            self.used = 'value'
            return True
        self.used = 'tuple'
        return True, self.overwrite

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        try:
            log.write(u'load {0}: nested shared family "{1}" taken from the library file'
                      .format(self.family_id, sharedFamily.Name))
        except Exception:
            pass
        if hasattr(source, 'Value'):
            source.Value = DB.FamilySource.Family
            if hasattr(overwriteParameterValues, 'Value'):
                overwriteParameterValues.Value = self.overwrite
            return True
        return True, DB.FamilySource.Family, self.overwrite


def _tx(doc, name):
    tx = DB.Transaction(doc, name)
    o = tx.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(Guard())
    o.SetClearAfterRollback(True)
    tx.SetFailureHandlingOptions(o)
    return tx


def friendly_error(ex):
    msg = u'{0}'.format(getattr(ex, 'Message', None) or ex)
    low = msg.lower()
    if 'owned by' in low or 'borrow' in low or 'relinquish' in low or 'checked out' in low:
        return strings.OWNED.format(msg.split('\n')[0])
    return msg.split('\n')[0]


def find_family(doc, family_id):
    low = family_id.lower()
    for fam in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        if fam.Name.lower() == low:
            return fam
    return None


def load_family(doc, path, family_id, overwrite=False, type_names=None):
    """Load / reload the whole family, or only type_names from its catalog.
    Returns the Family (or None for rebar shapes). Raises with a short text."""
    opts = LoadOptions(overwrite, family_id)
    tx = _tx(doc, u'PEER Library: load {0}'.format(family_id))
    tx.Start()
    try:
        if type_names:
            for name in type_names:
                ref = clr.Reference[DB.FamilySymbol]()
                doc.LoadFamilySymbol(path, name, opts, ref)
        else:
            ref = clr.Reference[DB.Family]()
            doc.LoadFamily(path, opts, ref)
        tx.Commit()
    except Exception as ex:
        log.write(u'load {0} from {1}'.format(family_id, path), exc=True)
        raise Exception(friendly_error(ex))
    finally:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
    if tx.GetStatus() != DB.TransactionStatus.Committed:
        raise Exception(u'Revit rolled the load back (see the warnings in the log).')
    global LAST_OPTIONS
    LAST_OPTIONS = opts
    return find_family(doc, family_id)


LAST_OPTIONS = None          # options of the last load (diagnostics / tests)


def family_type_names(doc, fam):
    """Names of the types of a family in the project (catalog families: these
    are the types to reload on update)."""
    if fam is None:
        return []
    names = []
    for i in fam.GetFamilySymbolIds():
        n = symbol_name(doc.GetElement(i))
        if n:
            names.append(n)
    return names


def first_symbol(doc, fam, prefer=None):
    if fam is None:
        return None
    syms = [doc.GetElement(i) for i in fam.GetFamilySymbolIds()]
    syms = [s for s in syms if s is not None]
    if prefer:
        for s in syms:
            if symbol_name(s) in prefer:
                return s
    return syms[0] if syms else None


def symbol_name(sym):
    """FamilySymbol name (ElementType.Name has no getter in IronPython)."""
    p = sym.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p is not None else u''


def request_placement(uidoc, symbol):
    """Starts Revit's own placement; call after the window is closed."""
    if symbol is None:
        return False
    try:
        uidoc.PostRequestForElementTypePlacement(symbol)
        return True
    except Exception as ex:
        log.write(u'placement {0}'.format(symbol.Id), exc=True)
        raise Exception(friendly_error(ex))
