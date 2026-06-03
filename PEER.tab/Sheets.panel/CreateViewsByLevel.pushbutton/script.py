# -*- coding: utf-8 -*-
__title__ = "Create Views\nby Level"
__author__ = "Dmitry D"
__doc__ = ("Stage 2: create the structural plans for the level sheets and place\n"
           "them on the sheets made by 'Create Sheets by Level'.\n\n"
           "Per logical level, each sheet (formwork / slab / walls) gets two\n"
           "plans - Reaching (RE) and Growing (GR) - so 6 views per level\n"
           "(4 for the foundation, which has no wall sheet). Both plans go at\n"
           "the exact same spot - RE placed first, GR on top - so they are\n"
           "perfectly co-located.\n\n"
           "One dialog lets you pick the RE/GR plan types, the RE/GR view\n"
           "templates and the scope box used to crop the plans.")

from pyrevit import revit, DB, script
from pyrevit.forms import alert

from PEER_Sheets import levels as L
from PEER_Sheets import naming as N
from PEER_Sheets import views as V
from PEER_Sheets import store as ST
from PEER_Sheets.ui import ViewOptionsWindow

doc = revit.doc
output = script.get_output()

# Defaults for the RE / GR structural-plan view family types (overridable via
# the picker below and remembered per project).
DEFAULT_VFT = {"RE": "Structural Plan RE", "GR": "Structural Plan GR"}

# Scope box used to crop every plan to the building footprint (optional).
SCOPE_BOX_NAME = "Building"


# --- levels ----------------------------------------------------------------

ordered_pr = L.levels_with_pr(doc)  # [(level, base)] ascending by elevation
if not ordered_pr:
    alert("No level has a PR_Level value. Run 'Create Sheets by Level' first.")
    script.exit()

groups = L.group_by_base(ordered_pr)  # [(base, [levels])] ascending by base

store_data = ST.load()


# --- gather options for the dialog -----------------------------------------

all_vfts = V.structural_plan_types(doc)
if not all_vfts:
    alert("No Structural Plan view family types found in the project.")
    script.exit()
vft_names = [V.vft_name(v) for v in all_vfts]

# Structural plans use ViewType.EngineeringPlan templates; fall back to all.
template_objs = V.view_templates(doc, DB.ViewType.EngineeringPlan)
if not template_objs:
    template_objs = V.view_templates(doc)
tpl_names = ["(none)"] + [V.view_name_of(v) for v in template_objs]

scopebox_objs = V.scope_boxes(doc)
scope_names = ["(none)"] + [V.scopebox_name(s) for s in scopebox_objs]


# --- preselect from saved choices / defaults -------------------------------

stored_types = store_data.get("view_types", {})
stored_tpls = store_data.get("view_templates", {})
stored_scope = store_data.get("scope_box", "")


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


# default scope box: saved one, else a scope box named SCOPE_BOX_NAME
scope_uid = stored_scope
if not scope_uid:
    for s in scopebox_objs:
        if V.scopebox_name(s) == SCOPE_BOX_NAME:
            scope_uid = s.UniqueId
            break

presel = {
    "re_type": _name_index(stored_types.get("RE", DEFAULT_VFT["RE"]), vft_names, 0),
    "gr_type": _name_index(stored_types.get("GR", DEFAULT_VFT["GR"]), vft_names,
                           1 if len(vft_names) > 1 else 0),
    "re_tpl": _uid_index(stored_tpls.get("RE"), template_objs),
    "gr_tpl": _uid_index(stored_tpls.get("GR"), template_objs),
    "scopebox": _uid_index(scope_uid, scopebox_objs),
}


# --- single dialog ---------------------------------------------------------

win = ViewOptionsWindow(vft_names, tpl_names, scope_names, presel)
win.ShowDialog()
if not win.result:
    script.exit()

r = win.result
re_vft = all_vfts[r["re_type"]]
gr_vft = all_vfts[r["gr_type"]]
re_tpl = template_objs[r["re_tpl"] - 1] if r["re_tpl"] > 0 else None
gr_tpl = template_objs[r["gr_tpl"] - 1] if r["gr_tpl"] > 0 else None
re_tpl_id = re_tpl.Id if re_tpl else DB.ElementId.InvalidElementId
gr_tpl_id = gr_tpl.Id if gr_tpl else DB.ElementId.InvalidElementId
scope_box = scopebox_objs[r["scopebox"] - 1] if r["scopebox"] > 0 else None
scope_box_id = scope_box.Id if scope_box else None


# --- persist the choices ---------------------------------------------------

store_data["view_types"] = {"RE": V.vft_name(re_vft), "GR": V.vft_name(gr_vft)}
store_data["view_templates"] = {
    "RE": re_tpl.UniqueId if re_tpl else "",
    "GR": gr_tpl.UniqueId if gr_tpl else "",
}
store_data["scope_box"] = scope_box.UniqueId if scope_box else ""
ST.save(store_data)


# --- resolve sheets (tracked first, then by number) ------------------------

sheet_track = {}
for e in store_data.get("sheets", []):
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


# --- existing view tracking (avoid duplicates) -----------------------------

view_track = {}
for e in store_data.get("views", []):
    view_track[(frozenset(e["level_uids"]), e["kind"], e["flavor"])] = e["view_uid"]


# --- build the jobs --------------------------------------------------------

jobs = []
missing_sheets = []  # (base, kind) we could not find a sheet for

for idx, (base, lvls) in enumerate(groups):
    rep_level = lvls[-1]                 # highest Revit level of the logical level
    level_uids = [l.UniqueId for l in lvls]
    has_walls = idx > 0                  # foundation (first group) has no walls

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

if not jobs:
    alert("No matching sheets found. Run 'Create Sheets by Level' first.")
    script.exit()


# --- create + place --------------------------------------------------------

vft_for = {"RE": re_vft, "GR": gr_vft}
tpl_for = {"RE": re_tpl_id, "GR": gr_tpl_id}

res = V.apply_views(doc, jobs, vft_for, tpl_for, scope_box_id)


# --- rebuild view tracking and persist -------------------------------------

tracking = []
for job in jobs:
    view = job.get("view")
    if view is not None:
        tracking.append({
            "level_uids": job["level_uids"],
            "kind": job["kind"],
            "flavor": job["flavor"],
            "view_uid": view.UniqueId,
        })
store_data["views"] = tracking
ST.save(store_data)


# --- report ----------------------------------------------------------------

output.print_md("## Create Views by Level - done")
output.print_md(
    "**Levels:** {}  |  **RE type:** {}  |  **GR type:** {}  |  "
    "**Scope box:** {}\n\n"
    "**Created:** {}  |  **Placed:** {}  |  **Re-aligned:** {}  |  "
    "**Conflicts:** {}  |  **Skipped:** {}".format(
        len(groups), V.vft_name(re_vft), V.vft_name(gr_vft),
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
    output.print_md("### Re-aligned (already placed, moved to anchor)")
    for name, sheet_no in res["realigned"]:
        output.print_md(u"- {} -> sheet {}".format(name, sheet_no))

if res["conflicts"]:
    output.print_md("### Conflicts - left untouched")
    output.print_md("A view with this name belongs to another level, or the "
                    "view is already on a different sheet:")
    for name, why in res["conflicts"]:
        output.print_md(u"- **{}** - {}".format(name, why))

if missing_sheets:
    output.print_md("### No sheet found - skipped")
    output.print_md("These sheets do not exist yet (run 'Create Sheets by "
                    "Level'):")
    for base, kind in missing_sheets:
        output.print_md(u"- {} ({})".format(N.sheet_number(base, kind), kind))

if res["skipped"]:
    output.print_md("### Skipped")
    for name, why in res["skipped"]:
        output.print_md(u"- {} - {}".format(name, why))

if res["errors"]:
    output.print_md("### Errors")
    for name, msg in res["errors"]:
        output.print_md(u"- {} - {}".format(name, msg))
