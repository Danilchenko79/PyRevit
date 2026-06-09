# -*- coding: utf-8 -*-
__title__ = "Create Sheets\n& Views"
__author__ = "Dmitry D"
__doc__ = ("Level sheets + their structural plans, in one run.\n\n"
           "One window, two tabs:\n"
           "  Sheets - PR_Level per level, elevation source, title block.\n"
           "  Views  - RE/GR plan types, RE/GR templates, scope box.\n\n"
           "Per logical level it makes the sheets (formwork=base, slab=base+2,\n"
           "wall=base+5) and then two plans per sheet - Reaching (RE) and\n"
           "Growing (GR) - placed at the exact same spot (RE first, GR on top),\n"
           "crop region hidden.\n\n"
           "Shift+click: edit the custom elevation text used in sheet names.")

from pyrevit import revit, DB, script
from pyrevit.forms import alert

from PEER_Sheets import levels as L
from PEER_Sheets import slabs as S
from PEER_Sheets import naming as N
from PEER_Sheets import creation as C
from PEER_Sheets import views as V
from PEER_Sheets import store as ST
from PEER_Sheets.ui import (
    LevelToolWindow, SlabChooserWindow, ReviewWindow, LabelEditorWindow,
    OrphanWindow,
)

doc = revit.doc
output = script.get_output()

# Defaults remembered per project and pre-selected in the Views tab.
DEFAULT_VFT = {"RE": "Structural Plan RE", "GR": "Structural Plan GR"}
SCOPE_BOX_NAME = "Building"

try:
    from pyrevit import EXEC_PARAMS
    is_config = bool(EXEC_PARAMS.config_mode)
except Exception:
    is_config = False


# --- common inputs --------------------------------------------------------

all_levels = L.collect_levels(doc)
if not all_levels:
    alert("No levels found in the project.")
    script.exit()

store_data = ST.load()
slab_choices = store_data.get("slab_choices", {})
elev_labels = store_data.get("elev_labels", {})


# --- Shift mode: edit elevation labels, then exit -------------------------

if is_config:
    pr_levels = L.levels_with_pr(doc)
    if not pr_levels:
        alert("No level has a PR_Level value. Nothing to label.")
        script.exit()

    rows = []
    for lvl, base in pr_levels:
        computed = N.format_num(N.ft_to_m(lvl.Elevation))
        rows.append((lvl, base, computed, elev_labels.get(lvl.UniqueId)))

    editor = LabelEditorWindow(rows)
    editor.ShowDialog()
    if editor.result is None:
        script.exit()

    for uid, text in editor.result.items():
        text = (text or "").strip()
        if text:
            elev_labels[uid] = text
        elif uid in elev_labels:
            del elev_labels[uid]
    store_data["elev_labels"] = elev_labels
    ST.save(store_data)
    alert("Elevation labels saved.")
    script.exit()


# --- title blocks ---------------------------------------------------------

titleblocks = list(DB.FilteredElementCollector(doc)
                   .OfClass(DB.FamilySymbol)
                   .OfCategory(DB.BuiltInCategory.OST_TitleBlocks))
if not titleblocks:
    alert("No title block types found in the project.")
    script.exit()


# --- gather the Views-tab options -----------------------------------------

all_vfts = V.structural_plan_types(doc)
if not all_vfts:
    alert("No Structural Plan view family types found in the project.")
    script.exit()
vft_names = [V.vft_name(v) for v in all_vfts]

# structural plans use ViewType.EngineeringPlan templates; fall back to all
template_objs = V.view_templates(doc, DB.ViewType.EngineeringPlan)
if not template_objs:
    template_objs = V.view_templates(doc)
tpl_names = ["(none)"] + [V.view_name_of(v) for v in template_objs]

scopebox_objs = V.scope_boxes(doc)
scope_names = ["(none)"] + [V.scopebox_name(s) for s in scopebox_objs]


def _name_index(value, names, default):
    try:
        return names.index(value)
    except ValueError:
        return default


def _uid_index(uid, objs):
    """Index into a '(none)'-prefixed list (0 = none) by UniqueId."""
    if uid:
        for i, o in enumerate(objs):
            if o.UniqueId == uid:
                return i + 1
    return 0


stored_types = store_data.get("view_types", {})
stored_tpls = store_data.get("view_templates", {})
stored_scope = store_data.get("scope_box", "")

scope_uid = stored_scope
if not scope_uid:
    for s in scopebox_objs:
        if V.scopebox_name(s) == SCOPE_BOX_NAME:
            scope_uid = s.UniqueId
            break

view_presel = {
    "re_type": _name_index(stored_types.get("RE", DEFAULT_VFT["RE"]), vft_names, 0),
    "gr_type": _name_index(stored_types.get("GR", DEFAULT_VFT["GR"]), vft_names,
                           1 if len(vft_names) > 1 else 0),
    "re_tpl": _uid_index(stored_tpls.get("RE"), template_objs),
    "gr_tpl": _uid_index(stored_tpls.get("GR"), template_objs),
    "scopebox": _uid_index(scope_uid, scopebox_objs),
}


# --- one window, two tabs -------------------------------------------------

win = LevelToolWindow(all_levels, titleblocks, store_data.get("titleblock"),
                      vft_names, tpl_names, scope_names, view_presel)
win.ShowDialog()
if not win.result:
    script.exit()

sheet_in = win.result["sheets"]
view_in = win.result["views"]

elev_source = sheet_in["elev_source"]
titleblock = sheet_in["titleblock"]
pr_values = sheet_in["pr_values"]
repick_slabs = sheet_in.get("repick_slabs", False)

re_vft = all_vfts[view_in["re_type"]]
gr_vft = all_vfts[view_in["gr_type"]]
re_tpl = template_objs[view_in["re_tpl"] - 1] if view_in["re_tpl"] > 0 else None
gr_tpl = template_objs[view_in["gr_tpl"] - 1] if view_in["gr_tpl"] > 0 else None
re_tpl_id = re_tpl.Id if re_tpl else DB.ElementId.InvalidElementId
gr_tpl_id = gr_tpl.Id if gr_tpl else DB.ElementId.InvalidElementId
scope_box = scopebox_objs[view_in["scopebox"] - 1] if view_in["scopebox"] > 0 else None
scope_box_id = scope_box.Id if scope_box else None

# remember choices for next time
store_data["titleblock"] = titleblock.UniqueId
store_data["view_types"] = {"RE": V.vft_name(re_vft), "GR": V.vft_name(gr_vft)}
store_data["view_templates"] = {
    "RE": re_tpl.UniqueId if re_tpl else "",
    "GR": gr_tpl.UniqueId if gr_tpl else "",
}
store_data["scope_box"] = scope_box.UniqueId if scope_box else ""
ST.save(store_data)


# --- write back the PR_Level values the user changed ----------------------

changed = [(lvl, new) for (lvl, new, original) in pr_values.values()
           if new != original]
if changed:
    t = DB.Transaction(doc, "PEER - Update PR_Level")
    t.Start()
    try:
        for lvl, new in changed:
            L.set_pr_level(lvl, new)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise


# --- resolve which levels participate -------------------------------------

ordered_pr = L.levels_with_pr(doc)  # [(level, base)] ascending by elevation
if not ordered_pr:
    alert("No level has a PR_Level value. Nothing to create.")
    script.exit()

pr_by_id = dict((lvl.Id.IntegerValue, lvl) for lvl, _b in ordered_pr)

_prev_base = None
for _lvl, _b in ordered_pr:
    if _prev_base is not None and _b < _prev_base:
        alert("Warning: PR_Level numbers do not ascend with elevation. "
              "Wall sheets reference the level below, so check that the "
              "numbering matches the physical order of the levels.")
        break
    _prev_base = _b


# --- pick elevation per level ---------------------------------------------

chosen_internal = {}          # level.Id.IntegerValue -> elevation (ft)
no_slab_levels = []           # levels that fell back to level elevation

if elev_source == "level":
    for lvl, _base in ordered_pr:
        chosen_internal[lvl.Id.IntegerValue] = lvl.Elevation
else:  # slab / overcant
    new_choices = dict(slab_choices)
    ambiguous = []
    for lvl, base in ordered_pr:
        idint = lvl.Id.IntegerValue
        options = S.slab_options_for_level(doc, lvl)  # [(floor, top_internal)]
        if not options:
            chosen_internal[idint] = lvl.Elevation
            no_slab_levels.append(lvl)
        elif len(options) == 1:
            chosen_internal[idint] = options[0][1]
        else:
            remembered = slab_choices.get(lvl.UniqueId)
            match_top = None
            match_idx = 0
            if remembered:
                for i, (floor, top) in enumerate(options):
                    if floor.UniqueId == remembered:
                        match_top = top
                        match_idx = i
                        break
            if match_top is not None and not repick_slabs:
                chosen_internal[idint] = match_top
            else:
                ambiguous.append(
                    (lvl, base,
                     [(f, N.ft_to_m(top)) for f, top in options],
                     match_idx))

    if ambiguous:
        slab_win = SlabChooserWindow(ambiguous)
        slab_win.ShowDialog()
        if slab_win.result is None:
            script.exit()
        for lvl_idint, (floor, _top_m) in slab_win.result.items():
            chosen_internal[lvl_idint] = S.floor_top_elevation(doc, floor)
            lvl = pr_by_id.get(lvl_idint)
            if lvl is not None:
                new_choices[lvl.UniqueId] = floor.UniqueId
        store_data["slab_choices"] = new_choices
        ST.save(store_data)


# --- elevation display string per level -----------------------------------

def level_num(lvl):
    return N.ft_to_m(chosen_internal[lvl.Id.IntegerValue])


def level_str(lvl):
    override = elev_labels.get(lvl.UniqueId)
    if override and override.strip():
        num = N.parse_elev(override)
        if num is not None:
            return N.elevation_str(num)
        return override.strip()
    return N.elevation_str(level_num(lvl))


# --- build the creation plan ----------------------------------------------

groups = L.group_by_base(ordered_pr)  # [(base, [levels])] ascending by base

plan = []
prev_high_str = None
for base, lvls in groups:
    low_lvl = min(lvls, key=level_num)
    high_lvl = max(lvls, key=level_num)
    high_str = level_str(high_lvl)
    plan.append({
        "base": base,
        "low_str": level_str(low_lvl),
        "high_str": high_str,
        "is_range": len(lvls) > 1,
        "prev_str": prev_high_str,
        "level_uids": [l.UniqueId for l in lvls],
    })
    prev_high_str = high_str


# --- sheets: diff, confirm, apply (no report yet) -------------------------

tracked = store_data.get("sheets", [])
items, orphans = C.build_diff(doc, plan, tracked)
actionable = [it for it in items if it["status"] in ("new", "rename")]

if orphans:
    orphan_win = OrphanWindow(orphans)
    orphan_win.ShowDialog()
    if orphan_win.result is None:
        script.exit()

if actionable:
    review = ReviewWindow(actionable)
    review.ShowDialog()
    if not review.result:
        script.exit()

created_s, renamed_s, skipped_s, deleted_s, conflict_pairs, tracking = \
    C.apply_changes(doc, titleblock.Id, items, orphans)

store_data["sheets"] = tracking
ST.save(store_data)


# --- views: build jobs against the (just created) sheets, then place ------

sheet_track = {}
for e in tracking:
    sheet_track[(frozenset(e["level_uids"]), e["kind"])] = e["sheet_uid"]

sheets_by_number = dict((s.SheetNumber, s) for s in
                        DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet))


def resolve_sheet(level_uids, base, kind):
    uid = sheet_track.get((frozenset(level_uids), kind))
    if uid:
        s = doc.GetElement(uid)
        if isinstance(s, DB.ViewSheet):
            return s
    return sheets_by_number.get(N.sheet_number(base, kind))


view_track = {}
for e in store_data.get("views", []):
    view_track[(frozenset(e["level_uids"]), e["kind"], e["flavor"])] = e["view_uid"]

jobs = []
missing_sheets = []
for idx, (base, lvls) in enumerate(groups):
    rep_level = lvls[-1]
    level_uids = [l.UniqueId for l in lvls]
    has_walls = idx > 0
    for kind, flavor, name in N.view_defs(base, has_walls):
        sheet = resolve_sheet(level_uids, base, kind)
        if sheet is None:
            if (base, kind) not in missing_sheets:
                missing_sheets.append((base, kind))
            continue
        jobs.append({
            "level": rep_level,
            "kind": kind,
            "flavor": flavor,
            "name": name,
            "sheet": sheet,
            "view_uid": view_track.get((frozenset(level_uids), kind, flavor)),
            "level_uids": level_uids,
        })

vft_for = {"RE": re_vft, "GR": gr_vft}
tpl_for = {"RE": re_tpl_id, "GR": gr_tpl_id}

res = (V.apply_views(doc, jobs, vft_for, tpl_for, scope_box_id) if jobs else
       {"created": [], "placed": [], "realigned": [],
        "skipped": [], "conflicts": [], "errors": []})

# rebuild view tracking
view_tracking = []
for job in jobs:
    view = job.get("view")
    if view is not None:
        view_tracking.append({
            "level_uids": job["level_uids"],
            "kind": job["kind"],
            "flavor": job["flavor"],
            "view_uid": view.UniqueId,
        })
store_data["views"] = view_tracking
ST.save(store_data)


# --- one combined report --------------------------------------------------

output.print_md("# Sheets & Views by Level - done")
output.print_md(
    "**Levels with PR_Level:** {}  |  **Elevation source:** {}".format(
        len(ordered_pr),
        "top of slab" if elev_source == "slab" else "level elevation"))

# Sheets
output.print_md("## Sheets")
output.print_md(
    "**Created:** {}  |  **Renamed:** {}  |  **Deleted:** {}  |  "
    "**Skipped:** {}".format(
        len(created_s), len(renamed_s), len(deleted_s), len(skipped_s)))

if created_s:
    output.print_md("### Created sheets")
    for number, name in created_s:
        output.print_md(u"- **{}** - {}".format(number, name))
if renamed_s:
    output.print_md("### Renamed / renumbered sheets")
    for number, name in renamed_s:
        output.print_md(u"- **{}** - {}".format(number, name))
if deleted_s:
    output.print_md("### Deleted orphaned sheets")
    for number, name in deleted_s:
        output.print_md(u"- {} - {}".format(number, name))
if conflict_pairs:
    output.print_md("### Sheet number already used by another sheet")
    for number, other in conflict_pairs:
        output.print_md(u"- **{}** - existing: {}".format(number, other))
if skipped_s:
    output.print_md("### Skipped sheets (unchecked)")
    for number, name in skipped_s:
        output.print_md(u"- {} - {}".format(number, name))
if no_slab_levels:
    output.print_md("### No slab found - used level elevation instead")
    for lvl in no_slab_levels:
        output.print_md(u"- {}".format(lvl.Name))

# Views
output.print_md("## Views")
output.print_md(
    "**RE type:** {}  |  **GR type:** {}  |  **Scope box:** {}\n\n"
    "**Created:** {}  |  **Placed:** {}  |  **Re-aligned:** {}  |  "
    "**Conflicts:** {}  |  **Skipped:** {}".format(
        V.vft_name(re_vft), V.vft_name(gr_vft),
        V.scopebox_name(scope_box) if scope_box else "none",
        len(res["created"]), len(res["placed"]), len(res["realigned"]),
        len(res["conflicts"]), len(res["skipped"])))

if res["created"]:
    output.print_md("### Created views")
    for name, kind, flavor in res["created"]:
        output.print_md(u"- **{}** ({} / {})".format(name, kind, flavor))
if res["placed"]:
    output.print_md("### Placed on sheets")
    for name, sheet_no in res["placed"]:
        output.print_md(u"- {} -> sheet {}".format(name, sheet_no))
if res["realigned"]:
    output.print_md("### Re-aligned (Growing moved onto Reaching)")
    for name, sheet_no in res["realigned"]:
        output.print_md(u"- {} -> sheet {}".format(name, sheet_no))
if res["conflicts"]:
    output.print_md("### Conflicts - left untouched")
    output.print_md("A view with this name belongs to another level, or the "
                    "view is already on a different sheet:")
    for name, why in res["conflicts"]:
        output.print_md(u"- **{}** - {}".format(name, why))
if missing_sheets:
    output.print_md("### No sheet found - views skipped")
    for base, kind in missing_sheets:
        output.print_md(u"- {} ({})".format(N.sheet_number(base, kind), kind))
if res["skipped"]:
    output.print_md("### Skipped views")
    for name, why in res["skipped"]:
        output.print_md(u"- {} - {}".format(name, why))
if res["errors"]:
    output.print_md("### Errors")
    for name, msg in res["errors"]:
        output.print_md(u"- {} - {}".format(name, msg))
