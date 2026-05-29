# -*- coding: utf-8 -*-
__title__ = "Create Sheets\nby Level"
__author__ = "Dmitry D"
__doc__ = ("Stage 1: create sheets for levels that carry a PR_Level value.\n"
           "Per logical level: formwork (base), slab reinforcement (base+2),\n"
           "wall reinforcement (base+5, from the previous level).\n\n"
           "Shift+click: edit the custom elevation text used in sheet names.")

from pyrevit import revit, DB, script
from pyrevit.forms import alert

from PEER_Sheets import levels as L
from PEER_Sheets import slabs as S
from PEER_Sheets import naming as N
from PEER_Sheets import creation as C
from PEER_Sheets import store as ST
from PEER_Sheets.ui import (
    MainWindow, SlabChooserWindow, ReviewWindow, LabelEditorWindow, OrphanWindow,
)

doc = revit.doc
output = script.get_output()

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


# --- normal mode: title block + main window -------------------------------

titleblocks = list(DB.FilteredElementCollector(doc)
                   .OfClass(DB.FamilySymbol)
                   .OfCategory(DB.BuiltInCategory.OST_TitleBlocks))
if not titleblocks:
    alert("No title block types found in the project.")
    script.exit()

win = MainWindow(all_levels, titleblocks, store_data.get("titleblock"))
win.ShowDialog()
if not win.result:
    script.exit()

elev_source = win.result["elev_source"]
titleblock = win.result["titleblock"]
pr_values = win.result["pr_values"]
repick_slabs = win.result.get("repick_slabs", False)

# remember the chosen title block for next time
store_data["titleblock"] = titleblock.UniqueId
ST.save(store_data)

# write back only the PR_Level values the user changed
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

# warn (only) when PR_Level numbers don't ascend with elevation - walls
# reference the level below, so the numbering must match the physical order
_prev_base = None
for _lvl, _b in ordered_pr:  # ordered_pr is ascending by elevation
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


# --- elevation display string per level (custom label or computed) --------

def level_num(lvl):
    return N.ft_to_m(chosen_internal[lvl.Id.IntegerValue])


def level_str(lvl):
    override = elev_labels.get(lvl.UniqueId)
    if override and override.strip():
        num = N.parse_elev(override)
        if num is not None:
            return N.elevation_str(num)
        return override.strip()  # legacy non-numeric label, kept verbatim
    return N.elevation_str(level_num(lvl))


# --- build the creation plan ----------------------------------------------
# Levels sharing a PR_Level value form one logical level: one set of sheets,
# formwork/slab named with a range when it spans several Revit levels. Walls
# reference the previous logical level's top (X = current top, Y = previous).

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


# --- diff against the model -----------------------------------------------

tracked = store_data.get("sheets", [])
items, orphans = C.build_diff(doc, plan, tracked)
actionable = [it for it in items if it["status"] in ("new", "rename")]
conflicts = [it for it in items if it["status"] == "conflict"]

if not actionable and not orphans and not conflicts:
    alert("All sheets already exist with the correct names. Nothing to do.")
    script.exit()


# --- confirm orphan deletion, then per-sheet create/rename -----------------

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

created, renamed, skipped, deleted, conflict_pairs, tracking = \
    C.apply_changes(doc, titleblock.Id, items, orphans)

store_data["sheets"] = tracking
ST.save(store_data)


# --- report ----------------------------------------------------------------

output.print_md("## Create Sheets by Level - done")
output.print_md(
    "**Levels with PR_Level:** {}  |  **Elevation source:** {}  |  "
    "**Created:** {}  |  **Renamed:** {}  |  **Deleted:** {}  |  "
    "**Skipped:** {}".format(
        len(ordered_pr),
        "top of slab" if elev_source == "slab" else "level elevation",
        len(created), len(renamed), len(deleted), len(skipped)))

if created:
    output.print_md("### Created sheets")
    for number, name in created:
        output.print_md(u"- **{}** - {}".format(number, name))

if renamed:
    output.print_md("### Renamed / renumbered sheets")
    for number, name in renamed:
        output.print_md(u"- **{}** - {}".format(number, name))

if deleted:
    output.print_md("### Deleted orphaned sheets")
    for number, name in deleted:
        output.print_md(u"- {} - {}".format(number, name))

if conflict_pairs:
    output.print_md("### Skipped - number already used by another sheet")
    output.print_md("These numbers belong to sheets this tool did not create, "
                    "so they were left untouched:")
    for number, other in conflict_pairs:
        output.print_md(u"- **{}** - existing: {}".format(number, other))

if skipped:
    output.print_md("### Skipped (unchecked)")
    for number, name in skipped:
        output.print_md(u"- {} - {}".format(number, name))

if no_slab_levels:
    output.print_md("### No slab found - used level elevation instead")
    for lvl in no_slab_levels:
        output.print_md(u"- {}".format(lvl.Name))
