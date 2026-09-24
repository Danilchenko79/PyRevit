# -*- coding: utf-8 -*-
__title__ = 'Create Sections'
__author__ = 'Dima'
__doc__ = u'''Version = 1.3
Date      = 2026-09-24
Description:
    Creates reinforcement sections for the beams and wall lintels of a level
    plan. Equal nodes (same b, h, adjacent slab thicknesses and slab offset)
    share one section, the other places get reference markers. A thin floor
    (poliash / insulation, <= 40 mm) never makes its own section: the group
    is cut where the poliash is, all other places get references. Sections are
    cut at mid-span with the interior on the right, 1:25, template PEER SEC,
    and placed on the target sheet in rows as "{prefix}_S{number}".
    Geometry is read from the host document AND from every loaded Revit
    link, so a documentation model whose concrete sits in a linked
    structural model is documented the same way. The views, markers and
    viewports are always made in the host document.
How-To:
    1. Open the level plan, or the sheet that holds it (one plan on the
       sheet is taken as is, otherwise a list is shown to pick from).
    2. Run, choose categories, the target sheet (when started from a plan)
       and the name prefix.
    3. Markers looking the wrong way: set MARKER_LOOK_SIGN = -1 in
       lib/kz_sections.py and rerun.
    4. The sources actually read are listed above the result table.
'''

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

from pyrevit import revit, script, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ViewPlan,
    ViewSheet, Transaction, TransactionGroup, Wall, XYZ,
    BoundingBoxIntersectsFilter,
)

from AutoSections import collect as C
from AutoSections import adjacency as A
import kz_sections as KZ
import kz_links
from peer_log import RunLog

doc = revit.doc
output = script.get_output()
log = RunLog('CreateSections')


# --- context: level plan (active, or found on the active sheet) -------------

def is_level_plan(v):
    return (isinstance(v, ViewPlan) and not v.IsTemplate
            and v.GenLevel is not None)


def plan_label(v):
    lvl = v.GenLevel.Name if v.GenLevel else u'-'
    return u'{}  |  {}  ({})'.format(lvl, v.Name, v.ViewType)


def pick_plan(candidates, message):
    """Let the user choose a level plan from candidates (sorted by level)."""
    def _key(v):
        try:
            return (v.GenLevel.Elevation, v.Name)
        except Exception:
            return (0.0, v.Name)
    candidates = sorted(candidates, key=_key)
    labels = [plan_label(v) for v in candidates]
    picked = forms.SelectFromList.show(labels, multiselect=False,
                                       title=message)
    if not picked:
        script.exit()
    return candidates[labels.index(picked)]


active_view = revit.active_view
sheet = None
plan = None

if isinstance(active_view, ViewSheet):
    # Started from a sheet: it is the target sheet. Take the plan from it
    # when it is unambiguous, otherwise ask.
    sheet = active_view
    plans_on_sheet = []
    for vp_id in sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        v = doc.GetElement(vp.ViewId) if vp is not None else None
        if is_level_plan(v):
            plans_on_sheet.append(v)
    if len(plans_on_sheet) == 1:
        plan = plans_on_sheet[0]
    elif len(plans_on_sheet) > 1:
        plan = pick_plan(plans_on_sheet,
                         u'Sheet {} holds several plans - which one to cut?'
                         .format(sheet.SheetNumber))
    else:
        all_plans = [v for v in FilteredElementCollector(doc)
                     .OfClass(ViewPlan).ToElements() if is_level_plan(v)]
        if not all_plans:
            forms.alert(u'No level plans found in the project.',
                        exitscript=True)
        plan = pick_plan(all_plans,
                         u'Sheet {} has no level plan - pick the plan to cut'
                         .format(sheet.SheetNumber))
elif is_level_plan(active_view):
    plan = active_view
else:
    forms.alert(u'Open a level plan (RE) or the sheet that holds it, '
                u'then run the tool.', exitscript=True)

level = plan.GenLevel

# --- input ------------------------------------------------------------------
choice = forms.CommandSwitchWindow.show(
    [u'Beams', u'Wall lintels', u'Beams + lintels'],
    message=u'What to cut on level "{}" (plan "{}")?'.format(level.Name,
                                                            plan.Name))
if not choice:
    script.exit()
want_beams = choice in (u'Beams', u'Beams + lintels')
want_walls = choice in (u'Wall lintels', u'Beams + lintels')

if sheet is None:
    sheets = sorted(
        FilteredElementCollector(doc).OfClass(ViewSheet).ToElements(),
        key=lambda s: s.SheetNumber)
    sheet_names = [u'{} - {}'.format(s.SheetNumber, s.Name) for s in sheets]
    picked = forms.SelectFromList.show(sheet_names, multiselect=False,
                                       title=u'Target sheet for the sections')
    if not picked:
        script.exit()
    sheet = sheets[sheet_names.index(picked)]

digits = u''.join([c for c in sheet.SheetNumber if c.isdigit()])
prefix = forms.ask_for_string(
    default=digits[:3] or sheet.SheetNumber,
    prompt=u'Section name prefix ({prefix}_S{n}):',
    title=u'Create Sections')
if not prefix:
    script.exit()

vft = C.section_view_family_type(doc)
if vft is None:
    forms.alert(u'The project has no section ViewFamilyType.', exitscript=True)

# --- collect ----------------------------------------------------------------
# Level filter: a plan (especially a ceiling plan) also shows elements of the
# neighbouring storey - keep only those whose TOP lies in the slab band of
# this level (elevation via ProjectElevation - the PBP may be offset).
LEVEL_BAND_DOWN_MM = 600.0    # element top not lower than level minus this
LEVEL_BAND_UP_MM = 2200.0     # and not higher than level plus this (parapets)
lvl_z = level.ProjectElevation
band_lo = lvl_z - LEVEL_BAND_DOWN_MM / 304.8
band_hi = lvl_z + LEVEL_BAND_UP_MM / 304.8


def in_level_band(el):
    bb = el.get_BoundingBox(None)
    return bb is not None and band_lo <= bb.Max.Z <= band_hi


def crop_bounds(view):
    """Plan extents (xmin, xmax, ymin, ymax) of an active crop, else None."""
    try:
        if not view.CropBoxActive:
            return None
        cb = view.CropBox
    except Exception:
        return None
    if cb is None:
        return None
    xs, ys = [], []
    for x in (cb.Min.X, cb.Max.X):
        for y in (cb.Min.Y, cb.Max.Y):
            for z in (cb.Min.Z, cb.Max.Z):
                q = cb.Transform.OfPoint(XYZ(x, y, z))
                xs.append(q.X)
                ys.append(q.Y)
    return (min(xs), max(xs), min(ys), max(ys))


crop = crop_bounds(plan)

# --- sources ----------------------------------------------------------------
# Only OUR structure is read: the host plus structural links (a building split
# into two models - walls of this level in one, the slab in the other).
# Architectural / MEP links are ignored even when they hold beams and slabs
# (24.09.2026: AR finish floors 350/400 went into the keys as slabs).
# A structural link with load-bearing elements at this level (above or below)
# is not taken silently - the user is asked. Discipline = file name tokens,
# see kz_links.link_discipline. view=None: probes measure geometry, they do
# not care what the plan shows.
LINK_BAND_DOWN_MM = 4000.0    # walls/columns of the storey below the slab
LINK_CATS = (BuiltInCategory.OST_Floors, BuiltInCategory.OST_StructuralFraming,
             BuiltInCategory.OST_Walls, BuiltInCategory.OST_StructuralColumns)


def near_level_count(src):
    """Load-bearing elements of a link at this level, inside the plan crop."""
    big = 1.0e5
    x0, x1, y0, y1 = crop if crop is not None else (-big, big, -big, big)
    ol = A.source_outline(src,
                          XYZ(x0, y0, lvl_z - LINK_BAND_DOWN_MM / 304.8),
                          XYZ(x1, y1, band_hi))
    n = 0
    for bic in LINK_CATS:
        try:
            n += (FilteredElementCollector(src.doc).OfCategory(bic)
                  .WhereElementIsNotElementType()
                  .WherePasses(BoundingBoxIntersectsFilter(ol))
                  .GetElementCount())
        except Exception:
            continue
    return n


class LinkItem(forms.TemplateListItem):
    @property
    def name(self):
        return self.item[1]


all_srcs = kz_links.unique_sources(kz_links.sources(doc))
srcs = [all_srcs[0]]
ignored = []
candidates = []
for src in all_srcs[1:]:
    disc = kz_links.link_discipline(src)
    if disc == u'OTHER':
        ignored.append(src)
        continue
    n = near_level_count(src)
    if n:
        candidates.append((src, u'[{}] {}  -  {} elements at this level'
                           .format(disc, src.name, n), disc))
if candidates:
    items = [LinkItem((s, lbl), checked=(d == u'ST'))
             for s, lbl, d in candidates]
    picked = forms.SelectFromList.show(
        items, multiselect=True, button_name=u'Continue',
        title=u'Level "{}": structure found in links - which to read? '
              u'(uncheck all = host only)'.format(level.Name))
    if picked is None:
        script.exit()
    for s, _lbl in picked:
        srcs.append(s)
sources_txt = kz_links.describe(srcs)
if ignored:
    sources_txt += u' | ignored (not structural): {}'.format(
        len(ignored))


def keep_linked(el, src):
    """Does this linked element belong to the plan we are cutting?

    A view id belongs to the host document, so a link cannot be filtered by
    the view at all: the whole link is collected and cut down here, in host
    coordinates - the same level band as the host, plus the plan crop.
    """
    box = kz_links.host_bbox(el, src.xform)
    if box is None:
        return False
    if not (band_lo <= box[5] <= band_hi):
        return False
    if crop is not None and (box[1] < crop[0] or box[0] > crop[1]
                             or box[3] < crop[2] or box[2] > crop[3]):
        return False
    return True


def linked(src, bic):
    return (FilteredElementCollector(src.doc).OfCategory(bic)
            .WhereElementIsNotElementType().ToElements())


# Elements are carried as (element, source) pairs: an element id alone is not
# unique, the same number exists in every document.
beams, walls, skipped_lvl = [], [], 0
host_src = srcs[0]
if want_beams:
    for b in (FilteredElementCollector(doc, plan.Id)
              .OfCategory(BuiltInCategory.OST_StructuralFraming)
              .WhereElementIsNotElementType().ToElements()):
        if in_level_band(b):
            beams.append((b, host_src))
        else:
            skipped_lvl += 1
if want_walls:
    for w in (FilteredElementCollector(doc, plan.Id)
              .OfCategory(BuiltInCategory.OST_Walls)
              .WhereElementIsNotElementType().ToElements()):
        if isinstance(w, Wall):
            if in_level_band(w):
                walls.append((w, host_src))
            else:
                skipped_lvl += 1
for src in srcs[1:]:
    if want_beams:
        for b in linked(src, BuiltInCategory.OST_StructuralFraming):
            if keep_linked(b, src):
                beams.append((b, src))
            else:
                skipped_lvl += 1
    if want_walls:
        for w in linked(src, BuiltInCategory.OST_Walls):
            if isinstance(w, Wall):
                if keep_linked(w, src):
                    walls.append((w, src))
                else:
                    skipped_lvl += 1
if not beams and not walls:
    forms.alert(u'No beams or walls found on the plan within the level band.\n'
                u'Sources read: {}'.format(sources_txt), exitscript=True)

centroid = (KZ.building_centroid(doc, level.Id, srcs)
            or KZ.building_centroid(doc, None, srcs))

groups, order, errors = KZ.build_groups(doc, beams, walls, centroid, srcs)
if not groups:
    forms.alert(u'Could not build a single node.\n' +
                u'\n'.join(errors[:5]), exitscript=True)

# --- similar groups: a real section only for the master, "(N)" for the rest
sim_plan = KZ.similarity_plan(groups, order)
order = [k for k in order if k not in sim_plan]

# --- rerun: sections with this prefix already exist -------------------------
existing = KZ.existing_kz_sections(doc, prefix)
deleted_count = 0
to_delete = []
if existing:
    mode = forms.CommandSwitchWindow.show(
        [u'Add missing', u'Recreate all', u'Cancel'],
        message=(u'Found {} sections "{}_S*". What to do?'
                 .format(len(existing), prefix)))
    if not mode or mode == u'Cancel':
        script.exit()
    if mode == u'Recreate all':
        to_delete = existing
        existing = []
    else:
        kept_order = []
        for key in order:
            cov = KZ.group_covered_by(existing, groups[key]['members'])
            if cov is not None:
                log.skipped(cov.Name, u'group already covered by an existing section')
            else:
                kept_order.append(key)
        order = kept_order
        if not order:
            forms.alert(u'All groups are already covered by existing sections - '
                        u'nothing to create.', exitscript=True)

# --- create (atomic Undo) ---------------------------------------------------
tg = TransactionGroup(doc, u'Create sections')
tg.Start()
try:
    if to_delete:
        deleted_count, e_del = KZ.delete_views(doc, to_delete, prefix)
        errors += e_del
    created, e2 = KZ.create_sections(doc, vft.Id, groups, order)
    errors += e2
    if not created:
        tg.RollBack()
        forms.alert(u'No sections were created.\n' + u'\n'.join(errors[:5]),
                    exitscript=True)
    ref_count, e3 = KZ.create_references(doc, plan, created)
    errors += e3
    placed, e4 = KZ.place_on_sheet(doc, sheet, created, prefix,
                                   datum_z=lvl_z)
    errors += e4
    # --- bracket "(N)": dummy for the master + references for all similar places
    bracket_refs = 0
    dummy_count = 0
    if sim_plan:
        import kz_refbracket as RB
        by_key = {}
        for entry in created:
            by_key[entry['desc']['key']] = entry
        by_master = {}
        for sim_k, master_k in sim_plan.items():
            by_master.setdefault(master_k, []).append(sim_k)
        num_by_view = {}
        for pl in placed:
            num_by_view[pl['view'].Id.IntegerValue] = pl['number']
        dmsgs = []
        bracket_entries = []
        td = Transaction(doc, u'Dummy (N) for similar groups')
        td.Start()
        try:
            for master_k, sim_keys in by_master.items():
                m_entry = by_key.get(master_k)
                if m_entry is None:
                    errors.append(u'similar groups: master was not created in '
                                  u'this run - use "Recreate all"')
                    continue
                dummy, _dvp = RB.create_dummy(doc, m_entry['view'], dmsgs)
                if dummy is None:
                    continue
                dummy_count += 1
                # master title "name(N)"; the difference data goes to the dummy
                # (Sections Dim reads it and writes "(22)" under the dimensions)
                num = num_by_view.get(m_entry['view'].Id.IntegerValue, u'?')
                tp = m_entry['view'].get_Parameter(
                    BuiltInParameter.VIEW_DESCRIPTION)
                if tp and not tp.IsReadOnly:
                    try:
                        tp.Set(u'{}({})'.format(m_entry['view'].Name, num))
                    except Exception as e:
                        errors.append(u'Title on Sheet: {}'.format(e))
                plate_txt, b_txt = KZ.sim_diff_data(master_k, sim_keys)
                data = []
                if plate_txt:
                    data.append(u'slab d={}'.format(plate_txt))
                if b_txt:
                    data.append(u'b={}'.format(b_txt))
                if data:
                    dp = dummy.get_Parameter(
                        BuiltInParameter.VIEW_DESCRIPTION)
                    if dp and not dp.IsReadOnly:
                        try:
                            dp.Set(u'; '.join(data))
                        except Exception as e:
                            errors.append(u'diff data on dummy: {}'.format(e))
                members = []
                for sk in sim_keys:
                    members.extend(groups[sk]['members'])
                bracket_entries.append({'view': dummy, 'desc': None,
                                        'members': members})
            td.Commit()
        except Exception:
            if td.HasStarted() and not td.HasEnded():
                td.RollBack()
            raise
        errors += dmsgs
        if bracket_entries:
            bracket_refs, e5 = KZ.create_references(doc, plan,
                                                    bracket_entries)
            errors += e5
    tg.Assimilate()
except Exception:
    if tg.HasStarted() and not tg.HasEnded():
        tg.RollBack()
    raise

# --- report -----------------------------------------------------------------
rows = []
for entry, pl in zip(created, placed):
    d = entry['desc']
    sa, sb = d.get('sides', ((), ()))
    slabs_txt = u'R:{} L:{}'.format(
        u','.join(u'{}'.format(x[0]) for x in sa) or u'-',
        u','.join(u'{}'.format(x[0]) for x in sb) or u'-')
    if not sa and not sb:
        slabs_txt = u'probes empty (key: {})'.format(d['key'][3])
    n_ins = len([m for m in entry['members'] if m.get('ins')])
    rows.append([output.linkify(entry['view'].Id), entry['view'].Name,
                 u'{:.0f}x{:.0f}'.format(d['b'], d['h']),
                 slabs_txt,
                 u'{}/{}'.format(n_ins, len(entry['members'])) if n_ins
                 else u'-',
                 len(entry['members'])])
    log.processed(entry['view'].Name,
                  u'b={:.0f} h={:.0f} slabs {} insulation={}/{} members={}'
                  .format(d['b'], d['h'], slabs_txt, n_ins,
                          len(entry['members']), len(entry['members'])))
for e in errors:
    log.error(u'-', e)
output.print_md(u'**Sources read:** {}'.format(sources_txt))
output.print_table(table_data=rows,
                   columns=[u'View', u'Name', u'Section', u'Slabs (thk)',
                            u'Insulation', u'Elements in group'])
scanned = len(beams) + len(walls)
summary = (u'Plan: {} | Sources: {} | Elements: {} (off level/crop: {}) | '
           u'Sections: {} | References: {} | '
           u'Similar groups -> (N): {} (dummy: {}, refs: {}) '
           u'| Old deleted: {} | Sheet: {}'.format(
               plan.Name, sources_txt, scanned, skipped_lvl, len(created),
               ref_count, len(sim_plan), dummy_count, bracket_refs,
               deleted_count, sheet.SheetNumber))
output.print_md(u'**{}**'.format(summary))
if errors:
    output.print_md(u'### Warnings ({})'.format(len(errors)))
    for w in errors[:15]:
        output.print_md(u'- {}'.format(w))
log.finish(summary=summary)
