# -*- coding: utf-8 -*-
__title__ = "Create Filters"
__doc__ = """
Creates/updates parametric filters and assigns them to view templates,
applying graphic overrides. For block walls, a different color is used.
Works with templates: "PEER Work" and "PEER Work SEC".
"""

__author__ = "Dima D"

import os, sys, math, datetime, time

# Revit API
from Autodesk.Revit.DB import (
    Transaction, FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    ParameterFilterRuleFactory, ElementParameterFilter, ParameterFilterElement,
    FillPatternElement, OverrideGraphicSettings, Color, View, WorksetKind,
    ElementId, FilterRule, FilteredWorksetCollector
)

from pyrevit import revit, forms

import clr
clr.AddReference("System")
from System.Collections.Generic import List

# ==================================================
# RUNTIME SHORTCUTS
# ==================================================
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

# ==================================================
# USER SETTINGS
# ==================================================
WORKSET_NAME_FOR_RULE = u"Construction"

# Target view templates where filters should be added
TARGET_VIEW_TEMPLATES = [u"PEER Work", u"PEER work SEC"]

# Filter specifications: (filter name, categories, add CON rule?, add BLK rule?)
FILTER_SPECS = [
    (u"PR_Coordination AR Walls=CON", [BuiltInCategory.OST_Walls], True,  False),
    (u"PR_Coordination AR Walls = BLK", [BuiltInCategory.OST_Walls], False, True ),
    (u"PR_Coordination AR Floor",      [BuiltInCategory.OST_Floors], False, False),
    (u"PR_Coordination AR Beam",       [BuiltInCategory.OST_StructuralFraming], False, False),
    (u"PR_Coordination AR Columns",    [BuiltInCategory.OST_StructuralColumns], False, False),
]

# Visual styles for specific filters (by filter name)
# Default — blue (0,128,192). For block walls — (200,80,80)
DEFAULT_COLOR = Color(0, 128, 192)
FILTER_VISUALS = {
    u"PR_Coordination AR Walls = BLK": Color(200, 80, 80),
}
SURFACE_TRANSPARENCY = 50  # Surface transparency (cut does not support transparency)

# ==================================================
# HELPERS — RULES & FILTERS
# ==================================================

def get_category_ids(bics):
    """Convert list[BuiltInCategory] -> List[ElementId]."""
    return List[ElementId]([ElementId(bic) for bic in bics])


def find_workset_by_name(document, ws_name):
    for w in FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset):
        if w.Name == ws_name:
            return w
    return None


def build_rule_not_equals_workset(document, workset_name):
    """Rule: workset does NOT contain the specified name (CreateNotContainsRule).
    Used to filter out elements not belonging to Workset `workset_name`.
    """
    ws = find_workset_by_name(document, workset_name)
    if ws is None:
        raise Exception(u'Workset "{}" not found'.format(workset_name))
    param_id = ElementId(BuiltInParameter.ELEM_PARTITION_PARAM)
    # Use string-based rule by workset name (same logic as original)
    return ParameterFilterRuleFactory.CreateNotContainsRule(param_id, workset_name)


def build_rule_type_name_contains(substr):
    """Rule: type name (SYMBOL_NAME_PARAM) contains substring (case-insensitive)."""
    param_id = ElementId(BuiltInParameter.SYMBOL_NAME_PARAM)
    return ParameterFilterRuleFactory.CreateContainsRule(param_id, substr, True)


def build_filter_from_rules(rules):
    return ElementParameterFilter(List[FilterRule](rules), False)


def create_or_update_filter(document, filter_name, category_ids, elem_filter):
    """Create new or update existing filter with the same name."""
    existing = next((f for f in FilteredElementCollector(document)
                     .OfClass(ParameterFilterElement) if f.Name == filter_name), None)
    if existing:
        existing.SetElementFilter(elem_filter)
        try:
            existing.SetCategories(category_ids)
        except:
            pass
        # Light trigger to force Revit to recalculate dependencies
        existing.Name = filter_name
        return existing
    else:
        return ParameterFilterElement.Create(document, filter_name, category_ids, elem_filter)

# ==================================================
# HELPERS — VIEW TEMPLATES
# ==================================================

def find_view_template_by_name(document, name):
    for v in FilteredElementCollector(document).OfClass(View):
        v = v  # type: View
        if v.IsTemplate and v.Name == name:
            return v
    return None


def get_filters_by_names(document, names):
    result = {}
    for f in FilteredElementCollector(document).OfClass(ParameterFilterElement):
        if f.Name in names:
            result[f.Name] = f
    return result


def template_reset_filters_if_needed(vt, target_filter_ids):
    """Replaces the filter set of a template with the required one if different.
    Returns (changed: bool, before_ids: list[ElementId]).
    """
    current = list(vt.GetFilters())
    curr_set = set(eid.IntegerValue for eid in current)
    tgt_set  = set(eid.IntegerValue for eid in target_filter_ids)

    if curr_set == tgt_set:
        return False, current

    for fid in list(current):
        try:
            vt.RemoveFilter(fid)
        except:
            pass

    for fid in target_filter_ids:
        if fid not in vt.GetFilters():
            vt.AddFilter(fid)
    return True, current


# ==================================================
# HELPERS — GRAPHIC OVERRIDES
# ==================================================

def get_solid_fill_id(document):
    for pat in FilteredElementCollector(document).OfClass(FillPatternElement):
        if pat.GetFillPattern().IsSolidFill:
            return pat.Id
    return None


def make_ogs(fill_id, color, transparency=SURFACE_TRANSPARENCY):
    """Build OverrideGraphicSettings with desired cut/surface settings."""
    ogs = OverrideGraphicSettings()
    # Cut — solid fill of specified color
    ogs = ogs.SetCutForegroundPatternId(fill_id)
    ogs = ogs.SetCutForegroundPatternVisible(True)
    ogs = ogs.SetCutForegroundPatternColor(color)
    # Transparency only affects surfaces
    ogs = ogs.SetSurfaceTransparency(int(transparency))
    return ogs


def apply_overrides_to_filters(vt, filter_ids, id2name, default_color=DEFAULT_COLOR):
    """Applies graphic overrides and ensures filters are enabled in the template.
    Color is selected by filter name (id2name) from FILTER_VISUALS or default.
    """
    fill_id = get_solid_fill_id(doc)
    if not fill_id:
        raise Exception(u"Solid fill pattern not found")

    for fid in filter_ids:
        fname = id2name.get(fid.IntegerValue, u"")
        color = FILTER_VISUALS.get(fname, default_color)
        ogs   = make_ogs(fill_id, color)
        try:
            vt.SetFilterOverrides(fid, ogs)
        except:
            pass
        # Enable filter and its visibility where supported by API
        try:
            if hasattr(vt, 'SetFilterVisibility'):
                vt.SetFilterVisibility(fid, True)
        except:
            pass
        try:
            if hasattr(vt, 'SetIsFilterEnabled'):
                vt.SetIsFilterEnabled(fid, True)
        except:
            pass

    # Force regeneration and quick visibility toggle
    try:
        doc.Regenerate()
        for fid in filter_ids:
            if hasattr(vt, 'GetFilterVisibility') and hasattr(vt, 'SetFilterVisibility'):
                vis = vt.GetFilterVisibility(fid)
                vt.SetFilterVisibility(fid, not vis)
                vt.SetFilterVisibility(fid, vis)
    except:
        pass

# ==================================================
# MAIN
# ==================================================
def run():
    # Input substrings for CON/BLK
    concrete_walls = forms.ask_for_string(
        default='CON',
        prompt='Enter substring for Concrete walls (type name contains):',
        title='Concrete Walls'
    )
    block_walls = forms.ask_for_string(
        default='BLK',
        prompt='Enter substring for Block walls (type name contains):',
        title='Block Walls'
    )

    # Collect target filter names (for model lookup)
    target_names = [name for name, _, _, _ in FILTER_SPECS]

    # Create/update filters
    t = Transaction(doc, u"Create/Update AR filters && push to templates")
    t.Start()

    try:
        created_filters = {}
        for fname, bics, need_con, need_blk in FILTER_SPECS:
            rules = [build_rule_not_equals_workset(doc, WORKSET_NAME_FOR_RULE)]
            if need_con:
                rules.append(build_rule_type_name_contains(concrete_walls))
            if need_blk:
                rules.append(build_rule_type_name_contains(block_walls))
            elem_param_filter = build_filter_from_rules(rules)

            cat_ids = get_category_ids(bics)
            pf = create_or_update_filter(doc, fname, cat_ids, elem_param_filter)
            created_filters[fname] = pf

        # Quick access name->Id and Id(int)->name
        name2id   = {n: f.Id for n, f in created_filters.items()}
        id2name   = {eid.IntegerValue: name for name, eid in name2id.items()}
        filter_ids = [name2id[n] for n in target_names]

        missing_templates = []
        for template_name in TARGET_VIEW_TEMPLATES:
            vt = find_view_template_by_name(doc, template_name)
            if vt is None:
                missing_templates.append(template_name)
                continue

            # Rebuild filter list for template if needed
            template_reset_filters_if_needed(vt, filter_ids)
            # Apply graphics based on filter name
            apply_overrides_to_filters(vt, filter_ids, id2name)
            # Small "nudge" to refresh UI
            vt.Name = vt.Name

        t.Commit()

    except Exception as ex:
        t.RollBack()
        forms.alert(u"Error: {}".format(ex), exitscript=True)

    # Message if some templates were not found
    if 'missing_templates' in locals() and missing_templates:
        forms.alert(
            u"The following templates were not found and were skipped: {}\nAdd them to the model if needed.".format(
                u", ".join(missing_templates)
            )
        )
