# -*- coding: utf-8 -*-
__title__ = "Create Filters"
__doc__ = """
Creates/updates parametric coordination filters and assigns them to view
templates, applying graphic overrides. Block walls get a different color.
Default templates: "PEER Work" and "PEER Work SEC".

Can be used two ways:
  - imported and called with explicit settings:
        CreateFilters.run(concrete_keywords=["CON"], block_keywords=["BLK"],
                          target_templates=["PEER Work", "PEER Work SEC"])
  - run on its own: it then asks for the keywords via dialogs.
"""

__author__ = "Dima D"

# Revit API
from Autodesk.Revit.DB import (
    Transaction, FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    ParameterFilterRuleFactory, ElementParameterFilter, ParameterFilterElement,
    FillPatternElement, OverrideGraphicSettings, Color, View, WorksetKind,
    ElementId, FilterRule, ElementFilter, LogicalAndFilter, LogicalOrFilter,
    FilteredWorksetCollector
)

from pyrevit import forms

import clr
clr.AddReference("System")
from System.Collections.Generic import List

# ==================================================
# RUNTIME SHORTCUTS
# ==================================================
doc = __revit__.ActiveUIDocument.Document

# ==================================================
# DEFAULTS
# ==================================================
WORKSET_NAME_FOR_RULE = u"Construction"
TARGET_VIEW_TEMPLATES = [u"PEER Work", u"PEER Work SEC"]

# Filter specs: (filter name, categories, add CON rule?, add BLK rule?)
FILTER_SPECS = [
    (u"PR_Coordination AR Walls=CON",  [BuiltInCategory.OST_Walls],             True,  False),
    (u"PR_Coordination AR Walls = BLK", [BuiltInCategory.OST_Walls],            False, True),
    (u"PR_Coordination AR Floor",      [BuiltInCategory.OST_Floors],            False, False),
    (u"PR_Coordination AR Beam",       [BuiltInCategory.OST_StructuralFraming], False, False),
    (u"PR_Coordination AR Columns",    [BuiltInCategory.OST_StructuralColumns], False, False),
]

# Color by filter name; everything else uses DEFAULT_COLOR.
DEFAULT_COLOR = Color(0, 128, 192)
FILTER_VISUALS = {
    u"PR_Coordination AR Walls = BLK": Color(200, 80, 80),
}
SURFACE_TRANSPARENCY = 50

# Type-name parameter that is reliably filterable for system families (walls).
TYPE_NAME_PARAM = ElementId(BuiltInParameter.ALL_MODEL_TYPE_NAME)
WORKSET_PARAM = ElementId(BuiltInParameter.ELEM_PARTITION_PARAM)


# ==================================================
# RULES & FILTERS
# ==================================================
def get_category_ids(bics):
    return List[ElementId]([ElementId(bic) for bic in bics])


def _contains_rule(param_id, value):
    """Case-insensitive 'contains' rule, tolerant to API version differences."""
    try:
        # Revit <= 2022 signature (ElementId, str, bool caseSensitive)
        return ParameterFilterRuleFactory.CreateContainsRule(param_id, value, False)
    except TypeError:
        # Revit 2023+ signature (ElementId, str) — case-insensitive by default
        return ParameterFilterRuleFactory.CreateContainsRule(param_id, value)


def _param_filter(rule):
    return ElementParameterFilter(List[FilterRule]([rule]), False)


def build_workset_filter(document, workset_name):
    """Filter: workset name does NOT contain `workset_name`."""
    ws = next((w for w in FilteredWorksetCollector(document)
               .OfKind(WorksetKind.UserWorkset) if w.Name == workset_name), None)
    if ws is None:
        raise Exception(u'Workset "{}" not found. Create the worksets first.'
                        .format(workset_name))
    try:
        rule = ParameterFilterRuleFactory.CreateNotContainsRule(WORKSET_PARAM, workset_name, False)
    except TypeError:
        rule = ParameterFilterRuleFactory.CreateNotContainsRule(WORKSET_PARAM, workset_name)
    return _param_filter(rule)


def build_typename_filter(keywords):
    """OR-filter over several type-name substrings. Returns None if no keywords."""
    keywords = [k for k in (keywords or []) if k]
    if not keywords:
        return None
    subs = [_param_filter(_contains_rule(TYPE_NAME_PARAM, kw)) for kw in keywords]
    if len(subs) == 1:
        return subs[0]
    return LogicalOrFilter(List[ElementFilter](subs))


def combine_and(filters):
    filters = [f for f in filters if f is not None]
    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return LogicalAndFilter(List[ElementFilter](filters))


def create_or_update_filter(document, filter_name, category_ids, elem_filter):
    existing = next((f for f in FilteredElementCollector(document)
                     .OfClass(ParameterFilterElement) if f.Name == filter_name), None)
    if existing:
        existing.SetElementFilter(elem_filter)
        existing.SetCategories(category_ids)
        return existing
    return ParameterFilterElement.Create(document, filter_name, category_ids, elem_filter)


# ==================================================
# VIEW TEMPLATES
# ==================================================
def find_view_template_by_name(document, name):
    """Case-insensitive, whitespace-tolerant template lookup."""
    target = u" ".join(name.lower().split())
    for v in FilteredElementCollector(document).OfClass(View):
        if v.IsTemplate and u" ".join(v.Name.lower().split()) == target:
            return v
    return None


def template_reset_filters_if_needed(vt, target_filter_ids):
    current = list(vt.GetFilters())
    curr_set = set(eid.IntegerValue for eid in current)
    tgt_set = set(eid.IntegerValue for eid in target_filter_ids)
    if curr_set == tgt_set:
        return False
    for fid in current:
        try:
            vt.RemoveFilter(fid)
        except Exception:
            pass
    present = set(eid.IntegerValue for eid in vt.GetFilters())
    for fid in target_filter_ids:
        if fid.IntegerValue not in present:
            vt.AddFilter(fid)
    return True


# ==================================================
# GRAPHIC OVERRIDES
# ==================================================
def get_solid_fill_id(document):
    for pat in FilteredElementCollector(document).OfClass(FillPatternElement):
        if pat.GetFillPattern().IsSolidFill:
            return pat.Id
    return None


def make_ogs(fill_id, color, transparency=SURFACE_TRANSPARENCY):
    ogs = OverrideGraphicSettings()
    ogs.SetCutForegroundPatternId(fill_id)
    ogs.SetCutForegroundPatternVisible(True)
    ogs.SetCutForegroundPatternColor(color)
    # Color surfaces too, so the override is visible in non-cut views.
    ogs.SetSurfaceForegroundPatternId(fill_id)
    ogs.SetSurfaceForegroundPatternVisible(True)
    ogs.SetSurfaceForegroundPatternColor(color)
    ogs.SetSurfaceTransparency(int(transparency))
    return ogs


def apply_overrides_to_filters(document, vt, filter_ids, id2name, default_color=DEFAULT_COLOR):
    fill_id = get_solid_fill_id(document)
    if not fill_id:
        raise Exception(u"No solid fill pattern found in the project.")
    for fid in filter_ids:
        fname = id2name.get(fid.IntegerValue, u"")
        ogs = make_ogs(fill_id, FILTER_VISUALS.get(fname, default_color))
        vt.SetFilterOverrides(fid, ogs)
        if hasattr(vt, 'SetIsFilterEnabled'):
            vt.SetIsFilterEnabled(fid, True)
        if hasattr(vt, 'SetFilterVisibility'):
            vt.SetFilterVisibility(fid, True)


# ==================================================
# MAIN
# ==================================================
def run(concrete_keywords=None, block_keywords=None,
        target_templates=None, workset_name=None, use_workset_rule=True):
    """Create/update the coordination filters and push them to templates.

    concrete_keywords / block_keywords: list of type-name substrings (OR).
        If None and used standalone, the user is asked via dialogs.
    target_templates: list of view-template names. Defaults to TARGET_VIEW_TEMPLATES.
    """
    if concrete_keywords is None and block_keywords is None:
        concrete_keywords = [forms.ask_for_string(
            default=u'CON', title=u'Concrete Walls',
            prompt=u'Type-name substring for Concrete walls:') or u'']
        block_keywords = [forms.ask_for_string(
            default=u'BLK', title=u'Block Walls',
            prompt=u'Type-name substring for Block walls:') or u'']

    concrete_keywords = [k for k in (concrete_keywords or []) if k]
    block_keywords = [k for k in (block_keywords or []) if k]
    templates = target_templates or TARGET_VIEW_TEMPLATES
    ws_name = workset_name or WORKSET_NAME_FOR_RULE

    target_names = [name for name, _, _, _ in FILTER_SPECS]

    t = Transaction(doc, u"Create/Update AR coordination filters")
    t.Start()
    try:
        ws_filter = build_workset_filter(doc, ws_name) if use_workset_rule else None
        con_filter = build_typename_filter(concrete_keywords)
        blk_filter = build_typename_filter(block_keywords)

        created_filters = {}
        for fname, bics, need_con, need_blk in FILTER_SPECS:
            parts = [ws_filter]
            if need_con:
                parts.append(con_filter)
            if need_blk:
                parts.append(blk_filter)
            elem_filter = combine_and(parts)
            if elem_filter is None:
                # Nothing to filter on (e.g. CON/BLK spec with empty keywords) — skip.
                continue
            created_filters[fname] = create_or_update_filter(
                doc, fname, get_category_ids(bics), elem_filter)

        name2id = {n: f.Id for n, f in created_filters.items()}
        id2name = {eid.IntegerValue: name for name, eid in name2id.items()}
        filter_ids = [name2id[n] for n in target_names if n in name2id]

        missing = []
        for template_name in templates:
            vt = find_view_template_by_name(doc, template_name)
            if vt is None:
                missing.append(template_name)
                continue
            template_reset_filters_if_needed(vt, filter_ids)
            apply_overrides_to_filters(doc, vt, filter_ids, id2name)

        t.Commit()
    except Exception as ex:
        t.RollBack()
        raise Exception(u"Filters failed: {}".format(ex))

    if missing:
        forms.alert(u"View templates not found (skipped): {}".format(u", ".join(missing)))
