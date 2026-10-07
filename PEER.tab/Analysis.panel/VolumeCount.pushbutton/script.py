# -*- coding: utf-8 -*-
__title__  = u'Volume\nCount'
__author__ = 'Dima'
__doc__    = u'''Version = 2.0
Date      = 2026-10-07
Description: Volume of the selected elements (m3) with totals by category,
    by material (e.g. concrete grade), by type and by Mark, plus grand total.
    Groups and assemblies are expanded to their members.
    Datums, rooms/areas/spaces, links and annotations are ignored.
    Elements with zero volume are listed separately.
    The full list is always saved to CSV (Documents\\PEER_VolumeCount);
    the per-element table is shown only for up to 100 elements.
How-To:
    1) Select elements in the model beforehand, OR run and pick them.
    2) Read the report in the pyRevit window; "Select" links select elements.
'''

import os
import sys
import codecs
import datetime

from System import Environment
from Autodesk.Revit.DB import (
    BuiltInParameter, BuiltInCategory, CategoryType, Options, ViewDetailLevel,
    Solid, GeometryInstance, Group, AssemblyInstance
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms, script

# --- lib/ path bootstrap (in case the module was added in this session) ---
_p = os.path.dirname(__file__)
for _ in range(6):
    _p = os.path.dirname(_p)
    if _p.lower().endswith('.extension'):
        _libp = os.path.join(_p, 'lib')
        if os.path.isdir(_libp) and _libp not in sys.path:
            sys.path.append(_libp)
        break
from peer_log import RunLog

doc    = __revit__.ActiveUIDocument.Document
uidoc  = __revit__.ActiveUIDocument
output = script.get_output()

FT3_TO_M3 = 0.3048 ** 3     # Revit internal units = feet
MAX_TABLE_ROWS = 100        # bigger tables hang the pyRevit window -> CSV only
NO_MAT_TOL = 0.001          # m³: volume not covered by materials below this is ignored
DASH = u'—'
NO_MATERIAL = u'(no material)'

# Model categories that have no physical volume (or are not ours to count).
SKIP_BIC = set()
for _bic in ('OST_Grids', 'OST_Levels', 'OST_CLines', 'OST_Rooms',
             'OST_MEPSpaces', 'OST_Areas', 'OST_RvtLinks', 'OST_Cameras',
             'OST_SectionBox', 'OST_IOSModelGroups', 'OST_Assemblies'):
    try:
        SKIP_BIC.add(int(getattr(BuiltInCategory, _bic)))
    except Exception:
        pass

# Volume parameters, in order of preference (missing names are skipped).
VOLUME_BIPS = [getattr(BuiltInParameter, _n) for _n in
               ('HOST_VOLUME_COMPUTED', 'REINFORCEMENT_VOLUME')
               if hasattr(BuiltInParameter, _n)]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def is_container(elem):
    return isinstance(elem, (Group, AssemblyInstance))


def is_countable(elem):
    """True for physical model elements (not datums, rooms, links, annotations)."""
    if elem is None or is_container(elem):
        return False
    try:
        cat = elem.Category
        if cat is None or cat.CategoryType != CategoryType.Model:
            return False
        return cat.Id.IntegerValue not in SKIP_BIC
    except Exception:
        return False


class CountableFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return is_container(elem) or is_countable(elem)

    def AllowReference(self, ref, point):
        return False


def pick_elements():
    """Pre-selection, or ask the user to pick. Returns None if cancelled."""
    ids = list(uidoc.Selection.GetElementIds())
    if ids:
        return [doc.GetElement(i) for i in ids]
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, CountableFilter(),
            u'Select elements to count volume, then click Finish')
    except OperationCanceledException:
        return None
    return [doc.GetElement(r.ElementId) for r in refs]


def expand(elems):
    """Unpack groups/assemblies (nested too), drop non-countable, de-duplicate.
    Returns (elements, n_containers, n_ignored)."""
    result, seen = [], set()
    n_cont = n_ign = 0
    queue = list(elems)
    i = 0
    while i < len(queue):
        e = queue[i]
        i += 1
        if e is None:
            continue
        if is_container(e):
            n_cont += 1
            for mid in e.GetMemberIds():
                queue.append(doc.GetElement(mid))
            continue
        eid = e.Id.IntegerValue
        if eid in seen:
            continue
        seen.add(eid)
        if is_countable(e):
            result.append(e)
        else:
            n_ign += 1
    return result, n_cont, n_ign


# ---------------------------------------------------------------------------
# Element data
# ---------------------------------------------------------------------------
def _solid_volume(geo_elem):
    """Sum of Solid volumes, nested instances included (ft³)."""
    total = 0.0
    for g in geo_elem:
        if isinstance(g, Solid):
            try:
                if g.Volume > 0:
                    total += g.Volume
            except Exception:
                pass
        elif isinstance(g, GeometryInstance):
            try:
                total += _solid_volume(g.GetInstanceGeometry())
            except Exception:
                pass
    return total


def get_volume_ft3(elem):
    """Built-in volume parameter first, geometry as fallback (ft³)."""
    for bip in VOLUME_BIPS:
        try:
            p = elem.get_Parameter(bip)
            if p and p.HasValue:
                v = p.AsDouble()
                if v > 0:
                    return v
        except Exception:
            pass
    opt = Options()
    opt.ComputeReferences = False
    opt.DetailLevel = ViewDetailLevel.Fine
    geo = elem.get_Geometry(opt)
    return _solid_volume(geo) if geo is not None else 0.0


_mat_names = {}


def material_name(mid):
    key = mid.IntegerValue
    if key not in _mat_names:
        m = doc.GetElement(mid)
        _mat_names[key] = m.Name if m is not None else u'<{}>'.format(key)
    return _mat_names[key]


def get_material_volumes(elem, total_m3):
    """{material name: m³}; volume not covered by materials -> NO_MATERIAL."""
    res = {}
    try:
        mids = list(elem.GetMaterialIds(False))
    except Exception:
        mids = []
    for mid in mids:
        try:
            v = elem.GetMaterialVolume(mid) * FT3_TO_M3
        except Exception:
            continue
        if v > 0:
            name = material_name(mid)
            res[name] = res.get(name, 0.0) + v
    rest = total_m3 - sum(res.values())
    if rest > NO_MAT_TOL:
        res[NO_MATERIAL] = res.get(NO_MATERIAL, 0.0) + rest
    return res


def _param_str(elem, bip):
    try:
        p = elem.get_Parameter(bip)
        if p and p.HasValue:
            return p.AsString() or u''
    except Exception:
        pass
    return u''


def get_mark(elem):
    return _param_str(elem, BuiltInParameter.ALL_MODEL_MARK) or DASH


def get_type_name(elem):
    """'Family: Type' from type parameters (Element.Name is unreliable in IPy)."""
    try:
        t = doc.GetElement(elem.GetTypeId())
    except Exception:
        t = None
    if t is None:
        return DASH
    fam = _param_str(t, BuiltInParameter.ALL_MODEL_FAMILY_NAME)
    typ = _param_str(t, BuiltInParameter.SYMBOL_NAME_PARAM)
    if fam and typ:
        return u'{}: {}'.format(fam, typ)
    return typ or fam or DASH


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def fmt(v):
    return u'{:.3f}'.format(v)


def save_csv(records):
    folder = os.path.join(
        Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
        'PEER_VolumeCount')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    title = u''.join(c if (c.isalnum() or c in u'-_') else u'_'
                     for c in doc.Title)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(folder, u'VolumeCount_{}_{}.csv'.format(title, stamp))

    def cell(x):
        s = x if isinstance(x, unicode) else unicode(x)
        if any(ch in s for ch in u',"\n'):
            s = u'"' + s.replace(u'"', u'""') + u'"'
        return s

    with codecs.open(path, 'w', 'utf-8-sig') as f:   # BOM -> Excel reads UTF-8
        f.write(u'ElementId,Category,Type,Mark,Volume_m3,Materials\n')
        for r in records:
            mats = u'; '.join(u'{} = {}'.format(k, fmt(v))
                              for k, v in sorted(r['mats'].items()))
            f.write(u','.join(cell(x) for x in (
                r['id'].IntegerValue, r['cat'], r['type'], r['mark'],
                fmt(r['vol']), mats)) + u'\n')
    return path


def print_totals(title, first_col, totals, ids):
    """totals: {key: [m³, count]}, largest volume first."""
    output.print_md(u'### ' + title)
    keys = sorted(totals.keys(), key=lambda k: -totals[k][0])
    rows = [[output.linkify(ids[k], u'Select'), k, totals[k][1],
             fmt(totals[k][0])] for k in keys[:MAX_TABLE_ROWS]]
    output.print_table(table_data=rows,
                       columns=[u'Select', first_col, u'Count', u'Volume, m³'])
    if len(keys) > MAX_TABLE_ROWS:
        output.print_md(u'*{} more rows — see CSV.*'.format(
            len(keys) - MAX_TABLE_ROWS))


def add_total(totals, ids, key, vol, eid):
    t = totals.setdefault(key, [0.0, 0])
    t[0] += vol
    t[1] += 1
    ids.setdefault(key, []).append(eid)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    picked = pick_elements()
    if picked is None:
        return
    elements, n_cont, n_ign = expand(picked)
    if not elements:
        forms.alert(u'No elements with volume in the selection '
                    u'(datums, rooms, links and annotations are ignored).',
                    title=u'Volume Count')
        return

    log = RunLog('VolumeCount')
    records = []
    by_cat, cat_ids = {}, {}
    by_type, type_ids = {}, {}
    by_mark, mark_ids = {}, {}
    by_mat, mat_ids = {}, {}
    zero_ids = []
    grand = 0.0

    for elem in elements:
        eid = elem.Id
        try:
            vol = get_volume_ft3(elem) * FT3_TO_M3
        except Exception as ex:
            log.error(u'{}'.format(eid), str(ex))
            vol = 0.0
        if vol <= 0:
            zero_ids.append(eid)
            log.skipped(u'{}'.format(eid), u'volume = 0')
            continue

        r = {'id': eid, 'cat': elem.Category.Name, 'type': get_type_name(elem),
             'mark': get_mark(elem), 'vol': vol,
             'mats': get_material_volumes(elem, vol)}
        records.append(r)
        grand += vol
        add_total(by_cat, cat_ids, r['cat'], vol, eid)
        add_total(by_type, type_ids, r['type'], vol, eid)
        add_total(by_mark, mark_ids, r['mark'], vol, eid)
        for m, v in r['mats'].items():
            add_total(by_mat, mat_ids, m, v, eid)
        log.processed(u'{}'.format(eid), u'{} {} m3'.format(r['cat'], fmt(vol)))

    # --- header ---
    output.print_md(u'## Volume of selected elements — {}'.format(doc.Title))
    note = [u'{} elements with volume'.format(len(records))]
    if n_cont:
        note.append(u'{} groups/assemblies expanded'.format(n_cont))
    if n_ign:
        note.append(u'{} non-physical elements ignored'.format(n_ign))
    if zero_ids:
        note.append(u'{} with zero volume'.format(len(zero_ids)))
    output.print_md(u' · '.join(note))

    if records:
        records.sort(key=lambda r: (r['cat'], r['type'], r['mark'],
                                    r['id'].IntegerValue))
        csv_path = None
        try:
            csv_path = save_csv(records)
        except Exception as ex:
            log.error(u'CSV', str(ex))

        # --- per element (small selections only) ---
        if len(records) <= MAX_TABLE_ROWS:
            output.print_md(u'### Elements')
            output.print_table(
                table_data=[[output.linkify(r['id']), r['cat'], r['type'],
                             r['mark'], fmt(r['vol'])] for r in records],
                columns=[u'ID', u'Category', u'Type', u'Mark', u'Volume, m³'])
        else:
            output.print_md(u'*Per-element table skipped ({} > {} rows) — '
                            u'see CSV.*'.format(len(records), MAX_TABLE_ROWS))

        print_totals(u'By category', u'Category', by_cat, cat_ids)
        print_totals(u'By material', u'Material', by_mat, mat_ids)
        print_totals(u'By type', u'Type', by_type, type_ids)
        if set(by_mark.keys()) != set([DASH]):
            print_totals(u'By Mark', u'Mark', by_mark, mark_ids)

        output.print_md(u'## Total: **{} m³**  ({} elements)'.format(
            fmt(grand), len(records)))
        output.print_md(u'All counted elements: {}'.format(
            output.linkify([r['id'] for r in records], u'Select all')))
        if csv_path:
            output.print_html(u'CSV: <a href="file:///{0}">{1}</a>'.format(
                csv_path.replace(u'\\', u'/'), csv_path))

    if zero_ids:
        output.print_md(u'**Zero volume ({}):** {} — e.g. rebar without a '
                        u'solid, detail items, empty families.'
                        .format(len(zero_ids), output.linkify(zero_ids, u'Select')))

    log.finish(summary=u'Total {} m3, {} elements, {} zero'.format(
        fmt(grand), len(records), len(zero_ids)), show=False)


main()
