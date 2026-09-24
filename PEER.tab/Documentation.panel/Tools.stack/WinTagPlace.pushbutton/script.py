# -*- coding: utf-8 -*-
__title__  = 'WinTag\nPlace'
__author__ = 'Dima'
__doc__    = u'''Version = 1.0
Date      = 2026-09-24
Description:
    Places / updates the pier tags written by WinTag. Unlike Revit "Tag All"
    it tags ONLY windows whose string is filled, and never adds a second tag
    to a window that already has a window tag in the view.
      RE view (name ...RE, or a ceiling plan):
         tag "Windows tag RE", windows whose head is below the view level
         (the pier goes up through this slab), MD_TagString not empty.
      GR view (name ...GR, or a structural plan):
         tag "Windows tag GR", windows of this level (sill at/above the
         view level), MD_TagString_GR not empty.
    Tag position: text along the wall, no leader, centred inside the
    opening (on the wall axis). When the tag is wider than the opening it
    goes above the wall (reading direction), 1 mm on paper off the wall
    face, never overlapping the wall.
    Excluded families (mamad by default, see lib/wintag_cfg.py) never get
    a tag. Shift+Click edits the keyword list (shared with WinTag).
    Update: RE/GR tags standing on windows whose string became empty, or
    on excluded windows, are listed and removed only after confirmation.
    Other projects: when the tag types "Windows tag RE/GR" are not found,
    the tag type for each mode is chosen from the loaded window tags.
How-To:
   1. Run WinTag first (fills the strings).
   2. On a sheet - tags its RE/GR views, no question. On an RE/GR plan -
      tags that view only. Anywhere else - choose the sheets; only the
      RE/GR views placed on them are tagged.
   3. Read the report: added / already tagged / removed.
'''

import re
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, StorageType,
    IndependentTag, Reference, TagOrientation, Transaction, ViewPlan,
    ViewType, ViewSheet, Wall, LocationPoint, LocationCurve, XYZ, ElementId,
)
from pyrevit import revit, forms, script

import os as _os, sys as _sys
_ext = _os.path.dirname(_os.path.abspath(__file__))
while _ext and not _ext.endswith('.extension'):
    _parent = _os.path.dirname(_ext)
    if _parent == _ext:
        break
    _ext = _parent
_lib = _os.path.join(_ext, 'lib')
if _os.path.isdir(_lib) and _lib not in _sys.path:
    _sys.path.append(_lib)
from peer_log import RunLog
import wintag_cfg

doc = revit.doc
EXCLUDE_KW = wintag_cfg.get_exclude_keywords()


# =====================================================================
# 0. CONSTANTS
# =====================================================================
P_RE = 'MD_TagString'
P_GR = 'MD_TagString_GR'
TAG_TYPE = {'RE': 'Windows tag RE', 'GR': 'Windows tag GR'}
PARAM    = {'RE': P_RE, 'GR': P_GR}
DEFAULT_WALL_FT = 20.0 / 30.48
LEVEL_TOL_FT    = 1.0 / 30.48       # 1 cm
TAG_GAP_MM      = 1.0               # paper gap between the wall face and a
                                    # tag that does not fit the opening
TEXT_SHIFT_MM   = 1.5               # paper mm the text sits ABOVE the
                                    # centre of the tag's box (the label is
                                    # top-aligned in a taller box); the tag
                                    # is moved down by it so the TEXT is
                                    # centred. Tune here if the family changes.
_VIEW_RX = re.compile(r'(RE|GR)(\b|_|$)')


# =====================================================================
# 1. HELPERS
# =====================================================================
def type_name(elem):
    p = elem.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else u''

def read_string(elem, name):
    p = elem.LookupParameter(name)
    if p and p.StorageType == StorageType.String:
        return (p.AsString() or u'').strip()
    return None

def view_mode(v):
    """'RE' | 'GR' | None - by the name suffix, then by the plan type."""
    if not isinstance(v, ViewPlan) or v.IsTemplate or v.GenLevel is None:
        return None
    m = None
    for m in _VIEW_RX.finditer(v.Name.upper()):
        pass
    if m is not None:
        return m.group(1)
    if v.ViewType == ViewType.CeilingPlan:
        return 'RE'
    if v.ViewType == ViewType.EngineeringPlan:
        return 'GR'
    return None

def tag_symbols():
    """{'RE': symbol, 'GR': symbol} of the window tags, by type name."""
    out = {}
    for s in (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_WindowTags)
              .WhereElementIsElementType().ToElements()):
        n = type_name(s).strip().lower()
        for k, want in TAG_TYPE.items():
            if n == want.lower():
                out[k] = s
    return out

def window_point(w):
    loc = w.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    return None

def window_z(w):
    """(sill_z, head_z) in project coordinates, or (None, None)."""
    lvl = doc.GetElement(w.LevelId) if w.LevelId else None
    if lvl is None:
        return None, None
    p = w.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
    sill = p.AsDouble() if p else 0.0
    h = None
    if w.Symbol:
        hp = w.Symbol.get_Parameter(BuiltInParameter.FAMILY_HEIGHT_PARAM)
        h = hp.AsDouble() if hp else None
    z0 = lvl.ProjectElevation + sill
    return z0, (z0 + h if h is not None else None)

def belongs(w, mode, lvl_z):
    """Does window w get its tag on a view of `mode` at level elevation lvl_z."""
    sill_z, head_z = window_z(w)
    if sill_z is None:
        return False
    if mode == 'RE':
        return head_z is not None and head_z <= lvl_z + LEVEL_TOL_FT
    return sill_z >= lvl_z - LEVEL_TOL_FT

_WIDTH_BIPS = [b for b in (
    getattr(BuiltInParameter, 'FAMILY_WIDTH_PARAM', None),
    getattr(BuiltInParameter, 'WINDOW_WIDTH', None),
    getattr(BuiltInParameter, 'FAMILY_ROUGH_WIDTH_PARAM', None),
) if b is not None]

def _xy_unit(v):
    v = XYZ(v.X, v.Y, 0.0)
    return v.Normalize() if v.GetLength() > 1e-6 else None

def wall_dir(w):
    """Unit XY vector along the window's wall, or None."""
    try:
        d = _xy_unit(w.HandOrientation)
        if d is not None:
            return d
    except Exception:
        pass
    host = getattr(w, 'Host', None)
    loc = host.Location if host is not None else None
    if isinstance(loc, LocationCurve):
        return _xy_unit(loc.Curve.GetEndPoint(1) - loc.Curve.GetEndPoint(0))
    return None

def wall_thk(w):
    host = getattr(w, 'Host', None)
    return host.WallType.Width if isinstance(host, Wall) else DEFAULT_WALL_FT

def opening_width(w, d):
    """Opening width along the wall: type -> instance -> bbox."""
    for elem in (w.Symbol, w):
        if elem is None:
            continue
        for bip in _WIDTH_BIPS:
            try:
                p = elem.get_Parameter(bip)
                if p and p.StorageType == StorageType.Double and p.AsDouble() > 1e-6:
                    return p.AsDouble()
            except Exception:
                pass
    bb = w.get_BoundingBox(None)
    if bb is not None and d is not None:
        return (abs(d.X) * (bb.Max.X - bb.Min.X) +
                abs(d.Y) * (bb.Max.Y - bb.Min.Y))
    return 0.0

def tag_orientation(view, d):
    """Text along the wall: horizontal for walls closer to the view X axis."""
    if d is None:
        return TagOrientation.Horizontal
    r, u = view.RightDirection, view.UpDirection
    if abs(d.DotProduct(r)) >= abs(d.DotProduct(u)):
        return TagOrientation.Horizontal
    return TagOrientation.Vertical

def place_tag(view, t, w):
    """Move a freshly created tag (document regenerated) to its place.

    Inside the opening: the tag centre on the window point (wall axis).
    When the tag is wider than the opening: beside the wall on the side
    that is "above" for the reading direction of the text, with a gap, so
    that the tag does not overlap the wall. -> 'inside' | 'above' | None"""
    pt = window_point(w)
    d = wall_dir(w)
    bb = t.get_BoundingBox(view)
    if pt is None or d is None or bb is None:
        return None
    n = XYZ(-d.Y, d.X, 0.0)
    ext_along = abs(d.X) * (bb.Max.X - bb.Min.X) + abs(d.Y) * (bb.Max.Y - bb.Min.Y)
    ext_perp  = abs(n.X) * (bb.Max.X - bb.Min.X) + abs(n.Y) * (bb.Max.Y - bb.Min.Y)
    center = XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, pt.Z)

    # only the width decides: a tag that fits the opening goes inside it,
    # centred, even when the text is taller than the wall is thick
    # "up" of the text: view Up for horizontal text, view Left for vertical
    up = view.UpDirection if t.TagOrientation == TagOrientation.Horizontal \
        else view.RightDirection.Negate()
    up = XYZ(up.X, up.Y, 0.0)
    if n.DotProduct(up) < 0:
        n = n.Negate()
    # box centre -> text centre: the text sits TEXT_SHIFT_MM above the box
    shift = TEXT_SHIFT_MM * view.Scale / 304.8
    if ext_along <= opening_width(w, d):
        # text centred on the opening (wall axis and window middle)
        target, where = pt - up * shift, 'inside'
    else:
        # box bottom a gap off the wall face (the text is higher still)
        gap = TAG_GAP_MM * view.Scale / 304.8
        target = pt + n * (wall_thk(w) / 2.0 + gap + ext_perp / 2.0)
        where = 'above'
    delta = XYZ(target.X - center.X, target.Y - center.Y, 0.0)
    if delta.GetLength() > 1e-9:
        t.TagHeadPosition = t.TagHeadPosition + delta
    return where

def sheet_views(sheet, syms):
    """RE/GR plan views placed on the sheet (those with a known tag type)."""
    out = []
    for vid in sheet.GetAllPlacedViews():
        v = doc.GetElement(vid)
        if view_mode(v) in syms:
            out.append(v)
    return sorted(out, key=lambda v: v.Name)

def tags_in_view(v):
    """{window id int: [tag, ...]} for every window tag in view v."""
    res = {}
    for t in (FilteredElementCollector(doc, v.Id)
              .OfCategory(BuiltInCategory.OST_WindowTags)
              .WhereElementIsNotElementType().ToElements()):
        if not isinstance(t, IndependentTag):
            continue
        try:
            ids = list(t.GetTaggedLocalElementIds())
        except Exception:
            ids = [t.TaggedLocalElementId]
        for i in ids:
            if i != ElementId.InvalidElementId:
                res.setdefault(i.IntegerValue, []).append(t)
    return res


# =====================================================================
# 2. PLAN FOR ONE VIEW (no transaction)
# =====================================================================
def plan_view(v, mode, syms):
    """-> dict: to_add [window], already [window], empty [window],
       to_remove [(tag, window)]"""
    lvl_z = v.GenLevel.ProjectElevation
    pname = PARAM[mode]
    type_mode = dict((s.Id.IntegerValue, k) for k, s in syms.items())
    existing = tags_in_view(v)

    plan = {'view': v, 'mode': mode, 'to_add': [], 'already': [],
            'empty': [], 'excluded': [], 'to_remove': []}
    for w in (FilteredElementCollector(doc, v.Id)
              .OfCategory(BuiltInCategory.OST_Windows)
              .WhereElementIsNotElementType().ToElements()):
        wid = w.Id.IntegerValue
        val = read_string(w, pname)
        excl = wintag_cfg.excluded_reason(w, EXCLUDE_KW)
        if wid in existing:
            # update: our RE/GR tag on an excluded window (mamad) or on a
            # window whose own string is empty now
            for t in existing[wid]:
                t_mode = type_mode.get(t.GetTypeId().IntegerValue)
                if t_mode is None:
                    continue
                if excl is not None or not read_string(w, PARAM[t_mode]):
                    plan['to_remove'].append((t, w))
            if val and excl is None:
                plan['already'].append(w)
            continue
        if not belongs(w, mode, lvl_z):
            continue
        if excl is not None:
            plan['excluded'].append(w)
            continue
        if not val:
            plan['empty'].append(w)
            continue
        plan['to_add'].append(w)
    return plan


# =====================================================================
# 3. MAIN
# =====================================================================
def main():
    run = RunLog('WinTagPlace')
    output = script.get_output()

    syms = tag_symbols()
    # another project may name its tag types differently - let the user pick
    if len(syms) < 2:
        all_types = sorted(
            FilteredElementCollector(doc)
            .OfCategory(BuiltInCategory.OST_WindowTags)
            .WhereElementIsElementType().ToElements(),
            key=lambda s: (s.Family.Name, type_name(s)))
        if not all_types:
            forms.alert(u'No window tag family is loaded in this model.',
                        exitscript=True)
        names = dict((u'{} : {}'.format(s.Family.Name, type_name(s)), s)
                     for s in all_types)
        for k in ('RE', 'GR'):
            if k in syms:
                continue
            pick = forms.SelectFromList.show(
                sorted(names.keys()), multiselect=False,
                title=u'Tag type for {} views ({}) - Cancel = skip'
                      .format(k, PARAM[k]),
                button_name=u'Use')
            if pick:
                syms[k] = names[pick]
        if not syms:
            return
    missing = [k for k in ('RE', 'GR') if k not in syms]

    # ---- views: only those on the chosen sheets
    #   active view is a sheet      -> its RE/GR views, no question
    #   active view is an RE/GR plan -> this view only, no question
    #   anything else               -> choose sheets
    av = doc.ActiveView
    if isinstance(av, ViewSheet):
        sheets = [av]
    elif view_mode(av) in syms:
        sheets = None
    else:
        all_sheets = sorted(
            [s for s in FilteredElementCollector(doc).OfClass(ViewSheet)
             .ToElements() if not s.IsPlaceholder and sheet_views(s, syms)],
            key=lambda s: (s.SheetNumber, s.Name))
        if not all_sheets:
            forms.alert(u'No sheets with RE/GR plan views.', exitscript=True)
        sheets = forms.SelectFromList.show(
            all_sheets, name_attr='Title', multiselect=True,
            title=u'WinTag Place - sheets', button_name=u'Select')
        if not sheets:
            return

    if sheets is None:
        views = [av]
    else:
        views, seen = [], set()
        for s in sheets:
            for v in sheet_views(s, syms):
                if v.Id.IntegerValue not in seen:
                    seen.add(v.Id.IntegerValue)
                    views.append(v)
        if not views:
            forms.alert(u'No RE/GR plan views on sheet {} - {}.'.format(
                av.SheetNumber, av.Name) if isinstance(av, ViewSheet)
                else u'No RE/GR plan views on the chosen sheets.',
                exitscript=True)

    plans = [plan_view(v, view_mode(v), syms) for v in views]
    n_add = sum(len(p['to_add']) for p in plans)
    n_rem = sum(len(p['to_remove']) for p in plans)

    do_remove = False
    if n_rem:
        do_remove = forms.alert(
            u'{} RE/GR tags stand on windows whose string is empty now\n'
            u'or on excluded families ({}).\n'
            u'Delete them?'.format(n_rem, u', '.join(EXCLUDE_KW)),
            title=u'WinTag Place - update', yes=True, no=True)

    if n_add == 0 and not do_remove:
        mode_label = u'NOTHING TO DO'
    else:
        mode_label = u'APPLIED'
        with revit.Transaction(u'WinTag Place: tags'):
            for p in plans:
                sym = syms[p['mode']]
                p['added'] = []
                p['above'] = 0
                v = p['view']
                created = []
                for w in p['to_add']:
                    try:
                        t = IndependentTag.Create(
                            doc, sym.Id, v.Id, Reference(w), False,
                            tag_orientation(v, wall_dir(w)), window_point(w))
                        created.append((t, w))
                    except Exception as e:
                        run.error(u'Window {}'.format(w.Id.IntegerValue), str(e))
                # tag sizes are known only after a regeneration - one per view
                doc.Regenerate()
                for t, w in created:
                    try:
                        where = place_tag(v, t, w)
                    except Exception as e:
                        where = None
                        run.error(u'Tag {}'.format(t.Id.IntegerValue),
                                  u'placing: {}'.format(e))
                    if where == 'above':
                        p['above'] += 1
                    p['added'].append(t)
                    run.processed(u'Window {}'.format(w.Id.IntegerValue),
                                  u'{} tag in {} ({})'.format(p['mode'], v.Name,
                                                             where or u'centre'))
                p['removed'] = 0
                if do_remove:
                    for t, w in p['to_remove']:
                        try:
                            doc.Delete(t.Id)
                            p['removed'] += 1
                            run.processed(u'Tag {}'.format(t.Id.IntegerValue),
                                          u'removed - window {} empty'.format(w.Id.IntegerValue))
                        except Exception as e:
                            run.error(u'Tag {}'.format(t.Id.IntegerValue), str(e))

    # ---- report
    output.set_title(u'WinTag Place')
    output.print_md(u'# WinTag Place - {}'.format(mode_label))
    if missing:
        output.print_md(u'No tag type for **{}** views - they are skipped'
                        .format(u', '.join(missing)))
    rows = []
    for p in plans:
        rows.append([p['view'].Name, p['mode'],
                     len(p.get('added', [])), p.get('above', 0), len(p['already']),
                     len(p['empty']), len(p['excluded']), p.get('removed', 0),
                     len(p['to_remove']) - p.get('removed', 0)])
    output.print_table(rows, columns=[u'View', u'Mode', u'Added',
                                      u'of them above the wall',
                                      u'Already tagged', u'Empty (skipped)',
                                      u'Excluded family',
                                      u'Removed', u'Empty-tag kept'])
    for p in plans:
        if p.get('added'):
            output.print_md(u'**{}** added: {}'.format(
                p['view'].Name,
                u', '.join(output.linkify(t.Id) for t in p['added'][:60])))
        if p['to_remove'] and not p.get('removed'):
            output.print_md(u'**{}** tags on empty windows (kept): {}'.format(
                p['view'].Name,
                u', '.join(output.linkify(t.Id) for t, _w in p['to_remove'][:60])))

    run.finish(summary=u'Added {}, removed {} in {} views'.format(
        sum(len(p.get('added', [])) for p in plans),
        sum(p.get('removed', 0) for p in plans), len(plans)))


if __name__ == '__main__':
    try:
        _shift = __shiftclick__
    except NameError:
        _shift = False
    if _shift:
        _kw = wintag_cfg.edit_exclude_keywords()
        if _kw is not None:
            forms.alert(u'Excluded: {}'.format(u', '.join(_kw) or u'(none)'),
                        title=u'WinTag Place')
    else:
        main()
