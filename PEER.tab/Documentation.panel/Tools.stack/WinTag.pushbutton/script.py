# -*- coding: utf-8 -*-
__title__  = 'WinTag'
__author__ = 'Dima'
__doc__    = u'''Version = 2.4
Date      = 2026-09-11
Description:
    Builds the pier tag string for every window in the project and writes it
    into two instance text parameters (shared parameter file PR_FOPv4.txt,
    group "Windows"):
      MD_TagString    - pier ABOVE the window: from the window head up
                        through the slab to the sill of the window above.
      MD_TagString_GR - pier BELOW the window: from the top of the slab
                        under the window up to its own sill. Filled only
                        when there is no window below and a slab is there,
                        cleared otherwise.
    RE string format (t = wall thickness, cm):
      t/h1+t2/h2  pier both under and over the slab
      +t2/h2      window head at the slab soffit - only the part above it
      t/h1        no window above, or it stands straight on the slab
      t/H         no slab found above - whole height as one number (flagged)
    Parameters missing from the model are bound to the Windows category from
    the shared parameter file automatically, and both are set to vary by
    group instance, so a window inside a model group keeps its own string
    without the group being opened for editing.
    Windows hosted by a slab (skylights) have no pier and are skipped.
    Excluded families (family/type name contains a keyword, "mamad" by
    default) are not filled - an old string on them is cleared - but they
    still count as windows above / below. Shift+Click edits the keywords
    (stored in the pyRevit config, same list for every project).
    The tags are placed by the next button, WinTag Place.
How-To:
   1. Run on any view.
   2. Read the report: every window with its old and new string. When
      something has to change, choose Apply (writes) or Check only (dry
      run). When nothing changes, no question is asked.
'''

import sys
from collections import Counter
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    StorageType, Element, UnitUtils, UnitTypeId,
    LocationPoint, LocationCurve, Wall, Floor, RoofBase, Transaction,
    XYZ, Line,
    ExternalDefinitionCreationOptions, SpecTypeId,
)
from pyrevit import forms, script

# peer_log lives in lib/ at the extension root - bootstrap sys.path
# (harmless once pyRevit has reloaded)
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

# Shift+Click - edit the list of excluded window families and stop
try:
    _shift = __shiftclick__
except NameError:
    _shift = False
if _shift:
    _kw = wintag_cfg.edit_exclude_keywords()
    if _kw is not None:
        forms.alert(u'Excluded: {}'.format(u', '.join(_kw) or u'(none)'),
                    title=u'WinTag')
    sys.exit()
EXCLUDE_KW = wintag_cfg.get_exclude_keywords()

doc  = __revit__.ActiveUIDocument.Document
view = doc.ActiveView
run  = RunLog('WinTag')


# =====================================================================
# 0. CONSTANTS
# =====================================================================
P_RE = 'MD_TagString'      # pier above (the main one), already in the SPF
P_GR = 'MD_TagString_GR'   # pier below (when no window sits under)

# shared parameter file the window parameters are taken from / added to
SPF_PATH  = r'F:\P-O-S-T\DIMA.D\Revit\Tamplate\Shared Parameters\PR_FOPv4.txt'
SPF_GROUP = 'Windows'

# IMPORTANT: level elevations come from Level.ProjectElevation (internal
# coordinates, same as the slab / window geometry). Level.Elevation is
# measured from the Project Base Point and shifts every height when the
# base point is moved.

XY_TOL_CM       = 5.0      # base XY tolerance, cm
XY_TOL_FT       = XY_TOL_CM / 30.48
DEFAULT_WALL_CM = 20.0     # fallback wall thickness for non-Wall hosts
MIN_OVERLAP_CM  = 10.0     # min. opening overlap along the wall for two
                           # windows to count as stacked
STOREY_MIN_CM   = 100.0    # a slab at least this far above the one found
                           # counts as another storey (window a storey away)
SLAB_PACK_GAP_CM = 20.0    # floors stacked with a gap up to this are one
                           # slab (d=15 + 10 cm + d=20 -> one 45 cm pack)
CEIL_TOL_CM     = 1.0      # a slab top may stand this much above the sill
                           # of the window above (modelling slack)


# =====================================================================
# 1. UNITS
# =====================================================================
def cm_to_ft(cm):
    return UnitUtils.ConvertToInternalUnits(float(cm), UnitTypeId.Centimeters)

def ft_to_cm(ft):
    return UnitUtils.ConvertFromInternalUnits(float(ft), UnitTypeId.Centimeters)

def cm_int(ft):
    return int(round(ft_to_cm(ft), 0))


# =====================================================================
# 2. PARAMETERS
# =====================================================================
def _double_bip(elem, bip):
    try:
        p = elem.get_Parameter(bip)
        if p and p.StorageType == StorageType.Double:
            return p.AsDouble()
    except Exception:
        pass
    return None

def _norm(s):
    return ' '.join(str(s or '').strip().split()).lower()

def find_param(elem, name):
    """Find a parameter, ignoring case."""
    if not elem:
        return None
    p = elem.LookupParameter(name)
    if p:
        return p
    target = _norm(name)
    for pp in elem.Parameters:
        try:
            if _norm(pp.Definition.Name) == target:
                return pp
        except Exception:
            pass
    return None

def set_string(elem, name, txt):
    p = find_param(elem, name)
    if p and not p.IsReadOnly and p.StorageType == StorageType.String:
        p.Set(u'' if txt is None else txt)
        return True
    return False

def read_string(elem, name):
    """Parameter string: '' when empty, None when there is no such parameter."""
    p = find_param(elem, name)
    if p and p.StorageType == StorageType.String:
        return p.AsString() or ''
    return None


# =====================================================================
# 2b. PROJECT PARAMETERS: check / add to the Windows category
# =====================================================================
def _windows_category():
    return doc.Settings.Categories.get_Item(BuiltInCategory.OST_Windows)

def _binding_for(name):
    """(definition, binding) of the project parameter `name`, or (None, None)."""
    target = _norm(name)
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        try:
            if _norm(it.Key.Name) == target:
                return it.Key, it.Current
        except Exception:
            pass
    return None, None

def _bound_to_windows(name):
    """True when `name` is already bound to the Windows category."""
    cat = _windows_category()
    if cat is None:
        return False
    _defn, binding = _binding_for(name)
    if binding is None:
        return False
    try:
        for c in binding.Categories:
            if c.Id.IntegerValue == cat.Id.IntegerValue:
                return True
    except Exception:
        pass
    return False

def _insert_binding(ext, binding):
    """Insert a binding, compatible across API versions."""
    pb = doc.ParameterBindings
    try:
        from Autodesk.Revit.DB import GroupTypeId
        return pb.Insert(ext, binding, GroupTypeId.Text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import BuiltInParameterGroup
        return pb.Insert(ext, binding, BuiltInParameterGroup.PG_TEXT)
    except Exception:
        pass
    return pb.Insert(ext, binding)

def ensure_window_params(names):
    """Make sure `names` are bound to the Windows category (instance).
    Missing ones come from the shared parameter file SPF_PATH (group
    SPF_GROUP); a definition absent there is created with the user's consent.
    -> list of (name, status): 'present' | 'added' | 'added (created in the
       SPF)' | 'error: ...'"""
    results = []
    todo = []
    for n in names:
        if _bound_to_windows(n):
            results.append((n, u'present'))
        else:
            todo.append(n)
    if not todo:
        return results

    # the configured file may sit on a drive this machine cannot see -
    # fall back to whatever shared parameter file Revit already points at
    spf_path = SPF_PATH
    if not _os.path.isfile(spf_path):
        try:
            _cur = doc.Application.SharedParametersFilename
        except Exception:
            _cur = None
        if _cur and _os.path.isfile(_cur):
            spf_path = _cur
        else:
            for n in todo:
                results.append((n, u'error: shared parameter file not found '
                                   u'{}'.format(SPF_PATH)))
            return results

    cat = _windows_category()
    if cat is None:
        for n in todo:
            results.append((n, u'error: no Windows category'))
        return results

    app = doc.Application
    old_spf = app.SharedParametersFilename
    try:
        app.SharedParametersFilename = spf_path
        spf = app.OpenSharedParameterFile()
        if spf is None:
            for n in todo:
                results.append((n, u'error: cannot open the shared parameter file'))
            return results

        grp = None
        for g in spf.Groups:
            if g.Name == SPF_GROUP:
                grp = g
                break
        if grp is None:
            for n in todo:
                results.append((n, u'error: no group {} in the shared parameter file'.format(SPF_GROUP)))
            return results

        spf_defs = {}
        for d in grp.Definitions:
            spf_defs[_norm(d.Name)] = d

        # definitions absent from the SPF are created only with consent
        to_create = [n for n in todo if _norm(n) not in spf_defs]
        allow_create = False
        if to_create:
            allow_create = forms.alert(
                u'The shared parameter file\n{}\ngroup "{}" does not '
                u'contain:\n  {}\n\nCreate them there (Text) and bind them '
                u'to the windows?'
                .format(spf_path, SPF_GROUP, u'\n  '.join(to_create)),
                title=u'WinTag - shared parameters', yes=True, no=True)

        cat_set = app.Create.NewCategorySet()
        cat_set.Insert(cat)

        tx = Transaction(doc, u'WinTag: window parameters')
        tx.Start()
        try:
            for n in todo:
                ext = spf_defs.get(_norm(n))
                created = False
                if ext is None:
                    if not allow_create:
                        results.append((n, u'error: not in the shared parameter file, creation declined'))
                        continue
                    try:
                        opt = ExternalDefinitionCreationOptions(
                            n, SpecTypeId.String.Text)
                        ext = grp.Definitions.Create(opt)
                        created = True
                    except Exception as e:
                        results.append((n, u'error: creating it in the shared parameter file - {}'.format(e)))
                        continue
                try:
                    _defn, existing = _binding_for(n)
                    if existing is not None:
                        # already a project parameter, just not on windows - add the category
                        existing.Categories.Insert(cat)
                        ok = doc.ParameterBindings.ReInsert(_defn, existing)
                    else:
                        ok = _insert_binding(ext, app.Create.NewInstanceBinding(cat_set))
                        if not ok:
                            ok = doc.ParameterBindings.ReInsert(
                                ext, app.Create.NewInstanceBinding(cat_set))
                    if ok:
                        results.append((n, u'added (created in the SPF)' if created
                                        else u'added'))
                    else:
                        results.append((n, u'error: Insert returned False'))
                except Exception as e:
                    results.append((n, u'error: binding - {}'.format(e)))
            tx.Commit()
        except Exception as e:
            if tx.HasStarted() and not tx.HasEnded():
                tx.RollBack()
            results.append((u'*', u'error: transaction - {}'.format(e)))
    finally:
        try:
            app.SharedParametersFilename = old_spf
        except Exception:
            pass
    return results


def ensure_vary_between_groups(names):
    """Let every group instance keep its own value.

    Windows are normally inside a model group, one per flat. A project
    parameter that is not allowed to vary holds a SINGLE value for the whole
    group type, so writing a tag would either push the first flat's string
    onto every other flat or be refused until the group is opened for
    editing. This is the switch the UI calls "Values can vary by group
    instance"; it only exists on instance parameters.
    -> list of (name, status): 'varies by group' | 'set to vary by group'
       | 'error: ...'"""
    out = []
    todo = []
    for n in names:
        defn, _b = _binding_for(n)
        if defn is None:
            out.append((n, u'error: not a project parameter, cannot vary'))
            continue
        try:
            if defn.VariesAcrossGroups:
                out.append((n, u'varies by group'))
                continue
        except Exception:
            pass                      # older API: just try to set it
        todo.append((n, defn))
    if not todo:
        return out

    tx = Transaction(doc, u'WinTag: values vary by group instance')
    tx.Start()
    try:
        for n, defn in todo:
            try:
                defn.SetAllowVaryBetweenGroups(doc, True)
                out.append((n, u'set to vary by group'))
            except Exception as e:
                out.append((n, u'error: vary by group - {}'.format(e)))
        tx.Commit()
    except Exception as e:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
        out.append((u'*', u'error: transaction - {}'.format(e)))
    return out


# =====================================================================
# 3. WINDOWS
# =====================================================================
def window_center(win):
    loc = win.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    return None

def window_sill_ft(win):
    return _double_bip(win, BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)

def window_height_ft(win):
    sym = win.Symbol
    if not sym:
        return None
    return _double_bip(sym, BuiltInParameter.FAMILY_HEIGHT_PARAM)

def host_wall_width_ft(win):
    host = getattr(win, 'Host', None)
    if isinstance(host, Wall):
        return host.WallType.Width
    return 0.0

def host_is_slab(win):
    """Is this window cut into a floor or a roof instead of a wall?

    A skylight has no pier above it and none below it, so every number the
    tag is made of is meaningless. Such windows are reported and left
    exactly as they are - their old strings, if any, are not touched.
    """
    host = getattr(win, 'Host', None)
    if host is None or isinstance(host, Wall):
        return False
    return isinstance(host, (Floor, RoofBase))


def wall_thk_cm_eff(win):
    w_ft = host_wall_width_ft(win)
    return cm_int(w_ft) if w_ft > 0 else int(DEFAULT_WALL_CM)

_WIDTH_BIPS = [b for b in (
    getattr(BuiltInParameter, 'FAMILY_WIDTH_PARAM', None),
    getattr(BuiltInParameter, 'WINDOW_WIDTH', None),
    getattr(BuiltInParameter, 'FAMILY_ROUGH_WIDTH_PARAM', None),
) if b is not None]

def window_along_dir(win):
    """Unit XY vector along the window's wall (family X axis), or None."""
    try:
        h = win.HandOrientation
        d = XYZ(h.X, h.Y, 0.0)
        if d.GetLength() > 1e-6:
            return d.Normalize()
    except Exception:
        pass
    try:
        host = getattr(win, 'Host', None)
        loc = host.Location if host is not None else None
        if isinstance(loc, LocationCurve) and isinstance(loc.Curve, Line):
            d = loc.Curve.Direction
            d = XYZ(d.X, d.Y, 0.0)
            if d.GetLength() > 1e-6:
                return d.Normalize()
    except Exception:
        pass
    return None

def window_width_ft(win):
    """Opening width: type -> instance -> bbox along the wall; None if unknown."""
    for elem in (win.Symbol, win):
        if elem is None:
            continue
        for bip in _WIDTH_BIPS:
            v = _double_bip(elem, bip)
            if v and v > 1e-6:
                return v
    try:
        d = window_along_dir(win)
        bb = win.get_BoundingBox(None)
        if d is not None and bb is not None:
            ext = (abs(d.X) * (bb.Max.X - bb.Min.X) +
                   abs(d.Y) * (bb.Max.Y - bb.Min.Y))
            if ext > 1e-6:
                return ext
    except Exception:
        pass
    return None


# =====================================================================
# 4. SLABS (Floors + Roofs)
# =====================================================================
def slab_z_range(slab):
    bb = slab.get_BoundingBox(None)
    return (bb.Min.Z, bb.Max.Z) if bb else (None, None)

def slab_xy_covers(slab, x, y, tol_ft):
    bb = slab.get_BoundingBox(None)
    if not bb:
        return False
    return (bb.Min.X - tol_ft <= x <= bb.Max.X + tol_ft and
            bb.Min.Y - tol_ft <= y <= bb.Max.Y + tol_ft)


# =====================================================================
# 5. COLLECTING ELEMENTS
# =====================================================================
_found_windows = list(FilteredElementCollector(doc)
                      .OfCategory(BuiltInCategory.OST_Windows)
                      .WhereElementIsNotElementType().ToElements())

# A window hosted by a slab is not a window in a pier - skip it outright.
all_windows = []
slab_windows = []
for _w in _found_windows:
    if host_is_slab(_w):
        slab_windows.append(_w)
        run.skipped(u'Window {}'.format(_w.Id.IntegerValue),
                    u'hosted by a slab, not by a wall')
    else:
        all_windows.append(_w)

# windows of the active view - only for an informational report column
try:
    view_ids = set(w.Id.IntegerValue for w in
                   FilteredElementCollector(doc, view.Id)
                   .OfCategory(BuiltInCategory.OST_Windows)
                   .WhereElementIsNotElementType().ToElements())
except Exception:
    view_ids = set()

all_slabs = []
for _cat in (BuiltInCategory.OST_Floors, BuiltInCategory.OST_Roofs):
    all_slabs.extend(FilteredElementCollector(doc)
                     .OfCategory(_cat)
                     .WhereElementIsNotElementType().ToElements())


# =====================================================================
# 6. FINDING THE WINDOWS OF A STACK
#    A window counts as standing above / below this one when:
#      * it is on another level (higher / lower), nearest level wins;
#      * it lies in the same wall plane (lateral offset <= wall thickness);
#      * its opening OVERLAPS ours along the wall by at least MIN_OVERLAP_CM
#        (widths and offsets may differ - the centres need not coincide).
#    When the wall direction or the width cannot be found, the old test is
#    used: centres matching within XY_TOL_CM.
# =====================================================================
def _stacked(win, direction):
    win_pt = window_center(win)
    base   = doc.GetElement(win.LevelId) if win.LevelId else None
    if win_pt is None or base is None:
        return None
    base_elev = base.ProjectElevation

    d      = window_along_dir(win)
    w_wid  = window_width_ft(win)
    n      = XYZ(-d.Y, d.X, 0.0) if d is not None else None
    thk    = host_wall_width_ft(win)
    lat_tol = max(XY_TOL_FT, thk if thk > 0 else cm_to_ft(DEFAULT_WALL_CM))
    min_ov  = cm_to_ft(MIN_OVERLAP_CM)
    tol_sq  = XY_TOL_FT * XY_TOL_FT

    best, best_elev, best_ov = None, None, None
    for w in all_windows:
        if w.Id == win.Id or w.LevelId is None:
            continue
        lvl = doc.GetElement(w.LevelId)
        if lvl is None:
            continue
        if direction > 0 and lvl.ProjectElevation <= base_elev + 1e-6:
            continue
        if direction < 0 and lvl.ProjectElevation >= base_elev - 1e-6:
            continue
        pt = window_center(w)
        if pt is None:
            continue
        v = XYZ(pt.X - win_pt.X, pt.Y - win_pt.Y, 0.0)

        if d is not None and w_wid is not None:
            if abs(v.DotProduct(n)) > lat_tol:        # a different wall plane
                continue
            along = abs(v.DotProduct(d))
            o_wid = window_width_ft(w)
            if o_wid is None:
                if along > XY_TOL_FT:
                    continue
                ov = 0.0
            else:
                ov = 0.5 * (w_wid + o_wid) - along    # length of the opening overlap
                if ov < min_ov:
                    continue
        else:
            if v.X * v.X + v.Y * v.Y > tol_sq:
                continue
            ov = 0.0

        # nearest level; within one level the larger overlap wins
        if (best_elev is None
                or (direction > 0 and lvl.ProjectElevation < best_elev - 1e-6)
                or (direction < 0 and lvl.ProjectElevation > best_elev + 1e-6)
                or (abs(lvl.ProjectElevation - best_elev) <= 1e-6 and ov > best_ov)):
            best, best_elev, best_ov = w, lvl.ProjectElevation, ov
    return best

def find_above_window(win): return _stacked(win,  1)
def find_below_window(win): return _stacked(win, -1)


# =====================================================================
# 7. THE SLAB ABOVE THE WINDOW
#    * slab soffit >= window head (contact tolerance 1e-3 ft)
#    * when the ceiling is known (sill of the window above), slab top <= it
#    * window XY inside the slab bbox plus tolerance
# =====================================================================
def find_slab_above(win_pt, win_top_z, ceiling_z, xy_tol_ft):
    if win_pt is None:
        return None
    ceil_tol = cm_to_ft(CEIL_TOL_CM)
    best, best_bot = None, None
    for s in all_slabs:
        bot, top = slab_z_range(s)
        if bot is None:
            continue
        if bot < win_top_z - 1e-3:
            continue
        if ceiling_z is not None and top > ceiling_z + ceil_tol:
            continue
        if not slab_xy_covers(s, win_pt.X, win_pt.Y, xy_tol_ft):
            continue
        if best_bot is None or bot < best_bot:
            best_bot = bot
            best = s
    return best


def slab_pack_range(first, win_pt, ceiling_z, xy_tol_ft):
    """(bottom, top) of the slab pack that starts with `first`.

    A slab is often modelled as several floors one over another (a lowered
    d=15 under the d=20 with a 10 cm gap, a 2 cm screed on top). The pier
    goes through all of them, so they count as ONE slab: every slab over
    the same point whose bottom is within SLAB_PACK_GAP_CM of the pack top
    (and that stays under the window above) joins the pack."""
    bot, top = slab_z_range(first)
    if bot is None:
        return None, None
    gap_ft   = cm_to_ft(SLAB_PACK_GAP_CM)
    ceil_tol = cm_to_ft(CEIL_TOL_CM)
    cands = []
    for s in all_slabs:
        if s.Id == first.Id:
            continue
        b, t = slab_z_range(s)
        if b is None or b < bot - 1e-3:
            continue
        if ceiling_z is not None and t > ceiling_z + ceil_tol:
            continue
        if not slab_xy_covers(s, win_pt.X, win_pt.Y, xy_tol_ft):
            continue
        cands.append((b, t))
    cands.sort()
    for b, t in cands:
        if b > top + gap_ft:
            break
        top = max(top, t)
    return bot, top


# =====================================================================
# 8. THE SLAB BELOW THE WINDOW (for GR - the pier downwards)
#    * slab top <= window sill (contact tolerance 1e-3 ft)
#    * window XY inside the slab bbox plus tolerance
#    * the nearest one below wins (the highest top)
# =====================================================================
def find_slab_below(win_pt, win_bot_z, xy_tol_ft):
    if win_pt is None:
        return None
    best, best_top = None, None
    for s in all_slabs:
        bot, top = slab_z_range(s)
        if top is None:
            continue
        if top > win_bot_z + 1e-3:
            continue
        if not slab_xy_covers(s, win_pt.X, win_pt.Y, xy_tol_ft):
            continue
        if best_top is None or top > best_top:
            best_top = top
            best = s
    return best


# =====================================================================
# 9. PROJECT PARAMETERS - check and add the missing ones
#    (needed either way: without them there is nothing to read or write)
# =====================================================================
param_status = ensure_window_params([P_RE, P_GR])
# Without this the tag of a window inside a group cannot be written per
# instance, which is the normal case: one group per flat.
param_status.extend(ensure_vary_between_groups([P_RE, P_GR]))
for _n, _st in param_status:
    if _st.startswith(u'added') or _st.startswith(u'set to'):
        run.processed(u'Parameter {}'.format(_n), _st)
    elif _st.startswith(u'error'):
        run.error(u'Parameter {}'.format(_n), _st)


# =====================================================================
# 10. CALCULATION FOR ONE WINDOW (RE + GR)
# =====================================================================
def compute_for_window(w):
    base = doc.GetElement(w.LevelId) if w.LevelId else None
    if base is None:
        return None
    sill_ft   = window_sill_ft(w)
    height_ft = window_height_ft(w)
    win_pt    = window_center(w)
    if sill_ft is None or height_ft is None or win_pt is None:
        return None

    win_bot_z = base.ProjectElevation + sill_ft               # window bottom (the sill)
    win_top_z = win_bot_z + height_ft                  # window head

    wall_cm     = wall_thk_cm_eff(w)
    wall_thk_ft = host_wall_width_ft(w)
    xy_tol_ft   = max(XY_TOL_FT,
                      wall_thk_ft if wall_thk_ft > 0
                      else cm_to_ft(DEFAULT_WALL_CM))

    # ---- windows above / below
    note = []
    above_win    = find_above_window(w)
    above_sill_z = None
    above_lvl    = None
    above_wall   = wall_cm
    if above_win is not None:
        s = window_sill_ft(above_win)
        ab_base = (doc.GetElement(above_win.LevelId)
                   if above_win.LevelId else None)
        if s is not None and ab_base is not None:
            above_sill_z = ab_base.ProjectElevation + s
            above_lvl    = ab_base.Name
        above_wall = wall_thk_cm_eff(above_win)

    below_win = find_below_window(w)
    below_lvl = None
    if below_win is not None:
        bl = doc.GetElement(below_win.LevelId) if below_win.LevelId else None
        if bl is not None:
            below_lvl = bl.Name

    # ====================================================
    # 10a. RE - the pier ABOVE the window
    # ====================================================
    slab = find_slab_above(win_pt, win_top_z, above_sill_z, xy_tol_ft)

    # a window above "a storey away": another slab sits between our slab and
    # its sill -> treat it as no window above (only the part up to the slab)
    if slab is not None and above_win is not None and above_sill_z is not None:
        s_top = slab_pack_range(slab, win_pt, above_sill_z, xy_tol_ft)[1]
        storey_ft = cm_to_ft(STOREY_MIN_CM)
        for s2 in all_slabs:
            if s2.Id == slab.Id:
                continue
            b2, t2 = slab_z_range(s2)
            if b2 is None:
                continue
            if (b2 >= s_top + storey_ft and t2 <= above_sill_z + 1e-3
                    and slab_xy_covers(s2, win_pt.X, win_pt.Y, xy_tol_ft)):
                note.append(u'window above is a storey away ({}) - ignored'
                            .format(above_win.Id.IntegerValue))
                above_win, above_sill_z, above_lvl, above_wall = None, None, None, wall_cm
                slab = find_slab_above(win_pt, win_top_z, None, xy_tol_ft)
                break

    if slab is None:
        note.append(u'⚠ no slab found above the window'
                    + (u' - height as a single number' if above_sill_z is not None else u''))
    if above_win is None and not note:
        note.append(u'no window above')

    slab_cm  = 0
    slab_lvl = None
    pack_bot = pack_top = None
    if slab is not None:
        # the whole pack of floors stacked here, not just the lowest one
        pack_bot, pack_top = slab_pack_range(slab, win_pt, above_sill_z,
                                             xy_tol_ft)
        slab_cm = cm_int(pack_top - pack_bot)
        try:
            sl = doc.GetElement(slab.LevelId) if slab.LevelId else None
            slab_lvl = sl.Name if sl else None
        except Exception:
            pass

    if slab is not None:
        top_gap = max(0, cm_int(pack_bot - win_top_z))
    elif above_sill_z is not None:
        top_gap = max(0, cm_int(above_sill_z - win_top_z))
    else:
        top_gap = 0

    above_sill = None
    if above_sill_z is not None and slab is not None:
        above_sill = max(0, cm_int(above_sill_z - pack_top))

    if above_sill is not None and slab is not None:
        if top_gap > 0:
            seg1, seg2 = top_gap + slab_cm, above_sill
        else:
            seg1, seg2 = 0, above_sill
    elif slab is not None:
        seg1, seg2 = top_gap + slab_cm, 0
    else:
        seg1, seg2 = top_gap, 0

    if seg1 > 0 and seg2 > 0:
        re_tag = u'{}/{}+{}/{}'.format(wall_cm, seg1, above_wall, seg2)
    elif seg2 > 0:
        re_tag = u'+{}/{}'.format(above_wall, seg2)
    elif seg1 > 0:
        re_tag = u'{}/{}'.format(wall_cm, seg1)
    else:
        re_tag = u''

    # pier type (for the report)
    has_lower = top_gap > 0
    has_upper = (above_sill is not None and above_sill > 0)
    if slab is None:
        beam_type = u'No slab'
    elif has_lower and has_upper:
        beam_type = u'Regular'
    elif has_lower and not has_upper:
        beam_type = u'Beam below'
    elif (not has_lower) and has_upper:
        beam_type = u'Beam above'
    else:
        beam_type = u'No beam'

    # ====================================================
    # 10b. GR - the pier BELOW the window (only when no window is under it)
    # ====================================================
    gr_tag     = u''
    gr_reason  = u''
    bottom_gap = None
    slab_below_top = None
    slab_below = find_slab_below(win_pt, win_bot_z, xy_tol_ft)

    # a window below "a storey away": another slab sits between its head and
    # our slab -> treat it as no window below (GR is needed)
    if below_win is not None and slab_below is not None:
        try:
            bw_base = doc.GetElement(below_win.LevelId)
            bw_top  = (bw_base.ProjectElevation + window_sill_ft(below_win)
                       + window_height_ft(below_win))
            sb_bot  = slab_z_range(slab_below)[0]
            storey_ft = cm_to_ft(STOREY_MIN_CM)
            for s2 in all_slabs:
                if s2.Id == slab_below.Id:
                    continue
                b2, t2 = slab_z_range(s2)
                if b2 is None:
                    continue
                if (b2 >= bw_top - 1e-3 and t2 <= sb_bot - storey_ft
                        and slab_xy_covers(s2, win_pt.X, win_pt.Y, xy_tol_ft)):
                    note.append(u'window below is a storey away ({}) - ignored'
                                .format(below_win.Id.IntegerValue))
                    below_win, below_lvl = None, None
                    break
        except Exception:
            pass

    if below_win is not None:
        gr_reason = u'window below exists'
    else:
        if slab_below is None:
            gr_reason = u'no slab below'
        else:
            _b, sb_top = slab_z_range(slab_below)
            slab_below_top = cm_int(sb_top)
            bottom_gap = max(0, cm_int(win_bot_z - sb_top))
            if bottom_gap > 0:
                # the part ABOVE the slab (slab top -> sill), without the
                # slab thickness - same format as the second part of RE
                gr_tag    = u'+{}/{}'.format(wall_cm, bottom_gap)
                gr_reason = u'slab top -> sill'
            else:
                gr_reason = u'window sits on the slab (gap 0)'

    return {
        'window':     w,
        're_tag':     re_tag,
        'gr_tag':     gr_tag,
        'note':       u'; '.join(note),
        'no_slab':    slab is None,
        # context for the report
        'level_name': base.Name,
        'level_elev': cm_int(base.ProjectElevation),
        'win_sill':   cm_int(win_bot_z),
        'win_top':    cm_int(win_top_z),
        'wall_cm':    wall_cm,
        'above_lvl':  above_lvl,
        'above_sill': above_sill,
        'below_lvl':  below_lvl,
        'has_slab':   slab is not None,
        'slab_lvl':   slab_lvl,
        'slab_thk':   slab_cm if slab is not None else None,
        'top_gap':    top_gap,
        'beam_type':  beam_type,
        'bottom_gap': bottom_gap,
        'slab_below': slab_below_top,
        'gr_reason':  gr_reason,
    }


# =====================================================================
# 11. PHASE 1 - calculation + reading current values (no transaction)
# =====================================================================
window_data = {}
errors      = []
no_data     = []
# excluded families (mamad by default): not filled; a string left by an
# earlier run is cleared. They still act as windows above / below above.
excluded    = []            # (window, keyword, cur_re, cur_gr)

for w in all_windows:
    _kw = wintag_cfg.excluded_reason(w, EXCLUDE_KW)
    if _kw is not None:
        excluded.append((w, _kw, read_string(w, P_RE) or u'',
                         read_string(w, P_GR) or u''))
        run.skipped(u'Window {}'.format(w.Id.IntegerValue),
                    u'excluded family ({})'.format(_kw))
        continue
    try:
        d = compute_for_window(w)
        if d is None:
            no_data.append(w)
            run.skipped(u'Window {}'.format(w.Id.IntegerValue),
                        u'no sill/height/level/point')
            continue
        d['current'] = {
            're': read_string(w, P_RE),
            'gr': read_string(w, P_GR),
        }
        d['changed'] = (
            (d['current']['re'] or '') != (d['re_tag'] or '') or
            (d['current']['gr'] or '') != (d['gr_tag'] or '')
        )
        window_data[w.Id.IntegerValue] = d
    except Exception as e:
        errors.append(u'Compute {}: {}'.format(w.Id.IntegerValue, str(e)))
        run.error(u'Window {}'.format(w.Id.IntegerValue), str(e))

to_clear      = [e for e in excluded if e[2] or e[3]]
changed_count = (sum(1 for d in window_data.values() if d['changed'])
                 + len(to_clear))

# are the parameters in the model at all (probed on the first window)
missing_params = []
if all_windows:
    _probe = all_windows[0]
    if find_param(_probe, P_RE) is None:
        missing_params.append(P_RE)
    if find_param(_probe, P_GR) is None:
        missing_params.append(P_GR)


# =====================================================================
# 11b. RUN MODE - asked only when there is an actual decision to make
# =====================================================================
if missing_params:
    DRY_RUN = True          # nothing can be written until they are bound
elif changed_count == 0:
    DRY_RUN = True          # every string is already up to date
else:
    _mode = forms.alert(
        u'{} of {} windows need a new tag string.\n\n'
        u'Apply - writes {} / {} into the windows.\n'
        u'Check only - shows what would change, writes nothing.'
        .format(changed_count, len(window_data), P_RE, P_GR),
        options=[u'Apply', u'Check only (dry run)'],
        title=u'WinTag - run mode',
    )
    if _mode is None:
        sys.exit()
    DRY_RUN = _mode.startswith(u'Check')


# =====================================================================
# 12. PHASE 2 - writing (Apply only)
# =====================================================================
updated = 0

if not DRY_RUN and not missing_params:
    with Transaction(doc, u'WinTag: window tag strings') as tx:
        tx.Start()
        for w in all_windows:
            d = window_data.get(w.Id.IntegerValue)
            if d is None:
                continue
            try:
                ok_re = set_string(w, P_RE, d['re_tag'])
                ok_gr = set_string(w, P_GR, d['gr_tag'])
                if ok_re or ok_gr:
                    updated += 1
                    if d['changed']:
                        run.processed(
                            u'Window {}'.format(w.Id.IntegerValue),
                            u'RE="{}" GR="{}"'.format(d['re_tag'], d['gr_tag']))
            except Exception as e:
                errors.append(u'Write {}: {}'.format(w.Id.IntegerValue, str(e)))
                run.error(u'Window {}'.format(w.Id.IntegerValue), str(e))
        for w, _kw, _re, _gr in to_clear:
            try:
                if _re:
                    set_string(w, P_RE, u'')
                if _gr:
                    set_string(w, P_GR, u'')
                updated += 1
                run.processed(u'Window {}'.format(w.Id.IntegerValue),
                              u'cleared - excluded family ({})'.format(_kw))
            except Exception as e:
                errors.append(u'Clear {}: {}'.format(w.Id.IntegerValue, str(e)))
                run.error(u'Window {}'.format(w.Id.IntegerValue), str(e))
        tx.Commit()


# =====================================================================
# 13. REPORT
# =====================================================================
output = script.get_output()
output.set_title(u'WinTag - check' if DRY_RUN else u'WinTag')

# the mode was not always chosen by hand - say what actually happened
if missing_params:
    mode_label = u'⛔ BLOCKED - parameters missing'
elif changed_count == 0:
    mode_label = u'✅ NOTHING TO DO'
elif DRY_RUN:
    mode_label = u'🔍 DRY RUN - nothing written'
else:
    mode_label = u'✏️ APPLY'
output.print_md(u'# WinTag - {}'.format(mode_label))

# anything that is not simply "already there and already varying"
_notable = [n for n, s in param_status
            if not s.startswith(u'present') and not s.startswith(u'varies')]
if _notable:
    output.print_md(u'### Project parameters (Windows category)')
    for n, s in param_status:
        output.print_md(u'- `{}` — {}'.format(n, s))

if missing_params:
    output.print_md(
        u'## ⛔ These parameters are not in the model: {}\n'
        u'Adding them from the shared parameter file `{}` failed (see '
        u'above). Bind them to the Windows category by hand, then run '
        u'again. Only the calculation is shown.'.format(
            u', '.join(missing_params), SPF_PATH))

if changed_count == 0:
    output.print_md(u'## ✅ Every window is up to date - no string would change')
else:
    verb = u'need updating' if (DRY_RUN or missing_params) else u'updated'
    output.print_md(u'## ⚠️ {} of {} windows {}'.format(
        changed_count, len(window_data), verb))

output.print_md(
    u'**View:** {}   **Windows handled:** {}   **Written:** {}'
    .format(view.Name, len(all_windows), updated))

if slab_windows:
    output.print_md(
        u'### Skipped: **{}** windows sit in a slab, not in a wall\n'
        u'They have no pier above or below, so nothing was calculated and '
        u'nothing was written - any string they already carry is left as it '
        u'is: {}'.format(
            len(slab_windows),
            u', '.join(output.linkify(w.Id) for w in slab_windows[:40])
            + (u' ...' if len(slab_windows) > 40 else u'')))

if excluded:
    output.print_md(
        u'### Excluded families (not filled): **{}** windows - keywords: {}\n'
        u'_Shift+Click on WinTag to change the list._'.format(
            len(excluded), u', '.join(EXCLUDE_KW)))
    _fams = Counter(w.Symbol.Family.Name for w, _k, _r, _g in excluded)
    for f, n in sorted(_fams.items()):
        output.print_md(u'- {}: {}'.format(f, n))
    if to_clear:
        output.print_md(u'{} {} old strings: {}'.format(
            u'Would clear' if DRY_RUN else u'Cleared', len(to_clear),
            u', '.join(output.linkify(e[0].Id) for e in to_clear[:40])
            + (u' ...' if len(to_clear) > 40 else u'')))

# pier type summary
counts = Counter(d['beam_type'] for d in window_data.values())
if counts:
    output.print_md(u'### Pier types (RE)')
    for bt, n in sorted(counts.items(), key=lambda x: -x[1]):
        output.print_md(u'- **{}**: {}'.format(bt, n))

gr_count = sum(1 for d in window_data.values() if d['gr_tag'])
output.print_md(u'### Pier below (GR): filled on **{}** windows'.format(gr_count))

# windows with no slab found above - tag written as a single number
no_slab = [w for w in all_windows
           if w.Id.IntegerValue in window_data
           and window_data[w.Id.IntegerValue]['no_slab']]
if no_slab:
    output.print_md(
        u'### ⚠ No slab found above **{}** windows - RE written as '
        u'a single number, without the split at the slab: {}'.format(
            len(no_slab),
            u', '.join(output.linkify(w.Id) for w in no_slab[:40])
            + (u' …' if len(no_slab) > 40 else u'')))

# the main table
def _fmt(v):
    return '-' if v in (None, '') else v

rows_keyed = []
for w in all_windows:
    d = window_data.get(w.Id.IntegerValue)
    if d is None:
        continue
    rows_keyed.append(((d['level_elev'], d['win_top'], w.Id.IntegerValue), w, d))
rows_keyed.sort(key=lambda r: r[0])

table_rows = []
for _key, w, d in rows_keyed:
    cur = d['current']
    status = u'⚠ Changed' if d['changed'] else u'✓ Up to date'
    table_rows.append([
        output.linkify(w.Id),
        u'✓' if w.Id.IntegerValue in view_ids else '',
        d['level_name'], d['level_elev'], d['win_sill'], d['win_top'],
        d['wall_cm'],
        _fmt(d['below_lvl']), _fmt(d['above_lvl']),
        u'✓' if d['has_slab'] else u'—',
        d['top_gap'], _fmt(d['above_sill']),
        _fmt(d['slab_below']), _fmt(d['bottom_gap']),
        d['beam_type'],
        _fmt(cur['re']), d['re_tag'] or '-',
        _fmt(cur['gr']), d['gr_tag'] or '-', d['gr_reason'],
        status, d['note'] or '',
    ])

if table_rows:
    output.print_table(
        table_data=table_rows,
        columns=[u'Window', u'View',
                 u'Level', u'Lvl Z', u'Sill', u'Head',
                 u'Wall',
                 u'↓below', u'↑above',
                 u'Slab↑', u'top_gap', u'↑sill',
                 u'Slab↓ top', u'bottom_gap',
                 u'Type (RE)',
                 u'RE (was)', u'RE (new)',
                 u'GR (was)', u'GR (new)', u'GR why',
                 u'Changed?', u'Note'],
        title=u'All project windows, sorted by level')

# the changes as a list
changed_list = [(w, d) for (_k, w, d) in rows_keyed if d['changed']]
if changed_list:
    output.print_md(u'### Windows with changes ({})'.format(len(changed_list)))
    for w, d in changed_list[:50]:
        output.print_md(
            u'- {} | RE: `{}`→`{}` | GR: `{}`→`{}`'.format(
                output.linkify(w.Id),
                d['current']['re'] or u'(empty)', d['re_tag'] or u'(empty)',
                d['current']['gr'] or u'(empty)', d['gr_tag'] or u'(empty)'))
    if len(changed_list) > 50:
        output.print_md(u'_... and {} more windows_'.format(len(changed_list) - 50))

if errors:
    output.print_md(u'### Errors ({})'.format(len(errors)))
    for e in errors[:30]:
        output.print_md(u'- ' + e)


# =====================================================================
# 14. RUN LOG
# =====================================================================
if missing_params:
    _summary = u'MISSING parameters: {} - nothing was written'.format(
        u', '.join(missing_params))
elif DRY_RUN:
    _summary = u'DRY RUN: {} of {} windows would change'.format(
        changed_count, len(window_data))
else:
    _summary = u'Wrote {} windows, GR filled on {}'.format(updated, gr_count)
if slab_windows:
    _summary += u' | skipped {} in slabs'.format(len(slab_windows))
run.finish(summary=_summary)
