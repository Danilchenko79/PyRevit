# -*- coding: utf-8 -*-
"""Create the per-sheet structural plans and place them on their sheets.

Builds on the sheets created by CreateSheetsByLevel. For each logical level and
each sheet role (formwork / slab / walls) two structural plans are created -
Reaching (RE) and Growing (GR) - and dropped on the matching sheet, RE on the
left, GR on the right.

A view lives on exactly one sheet, so every (level, kind, flavor) gets its own
ViewPlan. Views are tracked in the project JSON (store.py, key "views") so a
re-run reuses them instead of creating duplicates.

This module is model-side only: it opens its own transaction and never touches
UI. The caller (the pushbutton) assembles the job list and picks the view
templates / view family types.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewPlan, ViewFamily, ViewFamilyType,
    ViewType, Viewport, Transaction, XYZ, ElementId, ElementType,
    ElementTypeGroup, BuiltInParameter, BuiltInCategory, IFailuresPreprocessor,
    FailureProcessingResult, FailureSeverity,
)

SCALE = 50  # 1:50

# Growing viewports get a title-less viewport type (created once by duplicating
# the project's default). VIEWPORT_SHOW_TITLE_NO is the 'Show Title' value that
# hides the title; flip to 1 if titles still show in your Revit build.
NO_TITLE_TYPE_NAME = u"PEER No Title"
VIEWPORT_SHOW_TITLE_NO = 0

# The two plans go at the EXACT same spot (one directly over the other) so the
# model geometry registers precisely. RE is placed first, GR on top of it. The
# shared centre sits at these fractions of the title block.
PAIR_CENTER_X = 0.5
PAIR_CENTER_Y = 0.5

# Order the flavours are processed / drawn in: RE first (bottom), GR last (top).
FLAVOR_ORDER = ("RE", "GR")


class _SwallowWarnings(IFailuresPreprocessor):
    """Deletes warnings (e.g. 'viewports overlap', which is expected here),
    leaving errors to surface normally."""

    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
        return FailureProcessingResult.Continue


# --- names ----------------------------------------------------------------
# Element.Name is ambiguous for several Revit types in IronPython (View,
# ViewFamilyType ...) and raises MissingMemberException. Read names from a
# built-in parameter instead, which always works.

def _name_via_param(elem, bip):
    try:
        p = elem.get_Parameter(bip)
        if p:
            s = p.AsString()
            if s:
                return s
    except Exception:
        pass
    return None


def vft_name(vft):
    """Name of a ViewFamilyType (via SYMBOL_NAME_PARAM)."""
    return (_name_via_param(vft, BuiltInParameter.SYMBOL_NAME_PARAM)
            or u"VFT {}".format(vft.Id.IntegerValue))


def view_name_of(view):
    """Name of a View / view template (via VIEW_NAME)."""
    return (_name_via_param(view, BuiltInParameter.VIEW_NAME)
            or u"View {}".format(view.Id.IntegerValue))


# --- lookups --------------------------------------------------------------

def structural_plan_types(doc):
    """All Structural Plan view family types (for default match / manual pick)."""
    return [vft for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType)
            if vft.ViewFamily == ViewFamily.StructuralPlan]


def find_structural_plan_types(doc, re_name, gr_name):
    """Return (re_vft, gr_vft) matched by type name, each None if not found."""
    re_vft = gr_vft = None
    for vft in structural_plan_types(doc):
        name = vft_name(vft)
        if name == re_name:
            re_vft = vft
        elif name == gr_name:
            gr_vft = vft
    return re_vft, gr_vft


def view_templates(doc, view_type=None):
    """View templates in the project (View elements with IsTemplate).

    `view_type` (a ViewType) restricts to compatible templates - a template can
    only be applied to a view of the same ViewType, so structural plans want
    ViewType.EngineeringPlan templates.
    """
    out = []
    for v in FilteredElementCollector(doc).OfClass(View):
        if not v.IsTemplate:
            continue
        if view_type is not None and v.ViewType != view_type:
            continue
        out.append(v)
    return out


def scope_boxes(doc):
    """All scope box (volume of interest) elements in the project."""
    return list(FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_VolumeOfInterest)
                .WhereElementIsNotElementType())


def scopebox_name(sb):
    """Name of a scope box (guarded against the IronPython .Name quirk)."""
    try:
        n = sb.Name
        if n:
            return n
    except Exception:
        pass
    return u"Scope box {}".format(sb.Id.IntegerValue)


def scope_box_by_name(doc, name):
    """The scope box element with this name, or None."""
    if not name:
        return None
    for sb in scope_boxes(doc):
        if scopebox_name(sb) == name:
            return sb
    return None


def existing_views_by_name(doc):
    """Map view name -> view, for all non-template views."""
    out = {}
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate:
            continue
        out[view_name_of(v)] = v
    return out


# --- placement helpers ----------------------------------------------------

def _titleblock_bbox(doc, sheet):
    tbs = list(FilteredElementCollector(doc, sheet.Id)
               .OfCategory(BuiltInCategory.OST_TitleBlocks)
               .WhereElementIsNotElementType())
    if not tbs:
        return None
    return tbs[0].get_BoundingBox(sheet)


def _viewport_of(doc, view_id):
    """The single viewport hosting a view (a view lives on one sheet), or None."""
    for vp in (FilteredElementCollector(doc).OfClass(Viewport)
               .WhereElementIsNotElementType()):
        if vp.ViewId == view_id:
            return vp
    return None


def _view_level_id(view):
    """The level a plan view is associated with, or InvalidElementId."""
    try:
        lvl = view.GenLevel
        if lvl is not None:
            return lvl.Id
    except Exception:
        pass
    return ElementId.InvalidElementId


def _same_xy(a, b, eps=1e-4):
    """True if two points share the same X/Y (sheet space, feet)."""
    return abs(a.X - b.X) < eps and abs(a.Y - b.Y) < eps


# --- view configuration ---------------------------------------------------

def _apply_template_and_scale(view, tpl_id):
    """Set 1:50 and the view template. If the template controls Scale it wins."""
    try:
        view.Scale = SCALE
    except Exception:
        pass
    if tpl_id and tpl_id != ElementId.InvalidElementId:
        try:
            view.ViewTemplateId = tpl_id
        except Exception:
            pass


def _set_scope_box(view, scope_box_id):
    """Assign the scope box, unless the view template has locked the field."""
    p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
    if p and not p.IsReadOnly:
        try:
            p.Set(scope_box_id)
        except Exception:
            pass


def _hide_crop(view):
    """Hide the crop region boundary (the crop stays active to limit extents).

    If the view template controls 'Crop Region Visible', the property is
    read-only and the template's value wins.
    """
    try:
        view.CropBoxVisible = False
    except Exception:
        pass


def _sheet_name(sheet):
    """Sheet name, read via SHEET_NAME (guarded against the .Name quirk)."""
    p = sheet.get_Parameter(BuiltInParameter.SHEET_NAME)
    if p:
        s = p.AsString()
        if s:
            return s
    try:
        return sheet.Name
    except Exception:
        return u""


def _set_title_on_sheet(view, text):
    """Set the view's 'Title on Sheet' (VIEW_DESCRIPTION) to `text`."""
    p = view.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
    if p and not p.IsReadOnly:
        try:
            p.Set(text or u"")
        except Exception:
            pass


def _type_name(et):
    try:
        n = et.Name
        if n:
            return n
    except Exception:
        pass
    return _name_via_param(et, BuiltInParameter.SYMBOL_NAME_PARAM) or u""


def ensure_no_title_viewport_type(doc):
    """Id of a viewport type whose title is hidden, creating it once if needed.

    Reuses an existing NO_TITLE_TYPE_NAME type, otherwise duplicates the default
    viewport type and turns 'Show Title' off. Returns InvalidElementId on
    failure (then the title just isn't hidden).
    """
    default_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewportType)
    base = doc.GetElement(default_id) if default_id else None
    if base is None:
        return ElementId.InvalidElementId
    cat_id = base.Category.Id if base.Category else None

    for et in FilteredElementCollector(doc).OfClass(ElementType):
        if cat_id and et.Category and et.Category.Id == cat_id:
            if _type_name(et) == NO_TITLE_TYPE_NAME:
                return et.Id

    try:
        new_type = base.Duplicate(NO_TITLE_TYPE_NAME)
    except Exception:
        return ElementId.InvalidElementId
    p = new_type.get_Parameter(BuiltInParameter.VIEWPORT_ATTR_SHOW_LABEL)
    if p and not p.IsReadOnly:
        try:
            p.Set(VIEWPORT_SHOW_TITLE_NO)
        except Exception:
            pass
    return new_type.Id


def _apply_no_title_type(vp, type_id):
    """Switch a viewport to the title-less type (no-op if unavailable)."""
    if not type_id or type_id == ElementId.InvalidElementId:
        return
    try:
        if vp.GetTypeId() != type_id:
            vp.ChangeTypeId(type_id)
    except Exception:
        pass


def _unique_name(base, by_name):
    name = base
    i = 1
    while name in by_name:
        name = u"{}_{}".format(base, i)
        i += 1
    return name


# --- main -----------------------------------------------------------------

def apply_views(doc, jobs, vft_for, tpl_for, scope_box_id=None):
    """Create, place and stack the view jobs. Returns a result dict of lists:

        created   [(name, kind, flavor)]  - new views made
        placed    [(name, sheet_number)]  - viewports newly added to a sheet
        realigned [(name, sheet_number)]  - GR moved onto RE (had drifted)
        skipped   [(name, reason)]
        conflicts [(name, reason)]         - a foreign view blocks the name, or
                                             the view sits on another sheet
        errors    [(name, message)]

    Each job is a mutable dict:
        {"level": Level, "kind": str, "flavor": "RE"|"GR",
         "name": str, "sheet": ViewSheet, "view_uid": str|None}
    Jobs sharing a sheet (the RE/GR pair of one level+kind) are handled
    together. Reaching is the anchor: a NEW RE viewport is placed at the title
    block anchor, an existing one is left exactly where the user put it. Growing
    is co-located with Reaching - a new GR viewport is created on RE, an
    existing GR is moved onto RE only if it has drifted (already matching = left
    alone). So a manual layout is preserved; the tool only fixes a GR that no
    longer sits on its RE. Each job gets job["view"] set for the caller's
    tracking.

    `vft_for` maps flavor -> ViewFamilyType, `tpl_for` maps flavor -> template
    ElementId (or InvalidElementId for none).

    Idempotent: an existing view is reused only when it is a plan of the job's
    level (else conflict).
    """
    result = {"created": [], "placed": [], "realigned": [],
              "skipped": [], "conflicts": [], "errors": []}
    by_name = existing_views_by_name(doc)

    # group jobs by sheet - a sheet hosts the RE/GR pair of one level+kind
    groups, order = {}, []
    for job in jobs:
        key = job["sheet"].Id.IntegerValue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(job)

    t = Transaction(doc, "PEER - Create / place level views")
    t.Start()
    # expected 'viewports overlap' warnings shouldn't pop a dialog
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(_SwallowWarnings())
    t.SetFailureHandlingOptions(opts)
    try:
        no_title_type_id = ensure_no_title_viewport_type(doc)
        for key in order:
            pair = groups[key]
            try:
                _process_pair(doc, pair, by_name, vft_for, tpl_for,
                              scope_box_id, no_title_type_id, result)
            except Exception as e:
                names = u", ".join(j.get("name", u"") for j in pair)
                result["errors"].append((names, str(e)))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return result


def _resolve_view(doc, job, by_name):
    """Find the view for a job, verifying it belongs to the job's level.

    Returns (view, status):
        "ok"       - an existing plan of the right level to reuse
        "create"   - nothing matches; create a new view
        "conflict" - the name is taken by a view of another level / type
    """
    level_id = job["level"].Id

    uid = job.get("view_uid")
    if uid:
        el = doc.GetElement(uid)
        if isinstance(el, ViewPlan) and _view_level_id(el) == level_id:
            return el, "ok"
        # stale or wrong tracked view -> fall through to name / create

    existing = by_name.get(job["name"])
    if existing is not None:
        if isinstance(existing, ViewPlan) and _view_level_id(existing) == level_id:
            return existing, "ok"
        return existing, "conflict"

    return None, "create"


def _ordered(pair_jobs):
    """Pair jobs in draw order: RE first (bottom), GR last (top)."""
    return sorted(pair_jobs,
                  key=lambda j: FLAVOR_ORDER.index(j["flavor"])
                  if j["flavor"] in FLAVOR_ORDER else 99)


def _process_pair(doc, pair_jobs, by_name, vft_for, tpl_for, scope_box_id,
                  no_title_type_id, result):
    pair_jobs = _ordered(pair_jobs)
    sheet = pair_jobs[0]["sheet"]
    sheet_name = _sheet_name(sheet)
    name_by_flavor = dict((j["flavor"], j["name"]) for j in pair_jobs)

    # 1) resolve or create each view (level-checked), RE before GR
    resolved = []  # [(flavor, view)] in draw order
    for job in pair_jobs:
        flavor, name = job["flavor"], job["name"]
        view, status = _resolve_view(doc, job, by_name)

        if status == "conflict":
            result["conflicts"].append(
                (name, "name used by a view of another level"))
            job["view"] = None
            continue

        if status == "create":
            vft = vft_for.get(flavor)
            if vft is None:
                result["skipped"].append((name, "no view family type"))
                job["view"] = None
                continue
            view = ViewPlan.Create(doc, vft.Id, job["level"].Id)
            final_name = _unique_name(name, by_name)
            view.Name = final_name
            by_name[final_name] = view
            _apply_template_and_scale(
                view, tpl_for.get(flavor, ElementId.InvalidElementId))
            if scope_box_id and scope_box_id != ElementId.InvalidElementId:
                _set_scope_box(view, scope_box_id)
            result["created"].append((final_name, job["kind"], flavor))

        _hide_crop(view)  # keep crop active, hide its boundary line
        # Title on Sheet: the sheet name on Reaching only; Growing carries none
        _set_title_on_sheet(view, sheet_name if flavor == "RE" else u"")
        job["view"] = view
        resolved.append((flavor, view))

    if not resolved:
        return

    # commit the crop / scope box changes before measuring / placing
    doc.Regenerate()

    bb = _titleblock_bbox(doc, sheet)
    if bb is None:
        for flavor, _v in resolved:
            result["skipped"].append(
                (name_by_flavor[flavor], "no title block on sheet"))
        return
    w = bb.Max.X - bb.Min.X
    h_tb = bb.Max.Y - bb.Min.Y
    anchor = XYZ(bb.Min.X + PAIR_CENTER_X * w,
                 bb.Min.Y + PAIR_CENTER_Y * h_tb, 0)

    view_by_flavor = dict(resolved)

    # --- Reaching is the anchor: never move it if it's already placed ---
    # A new RE viewport is created at the title-block anchor; an existing one
    # keeps wherever the user put it. re_center is the point GR aligns to.
    re_center = None
    re_view = view_by_flavor.get("RE")
    if re_view is not None:
        re_name = name_by_flavor["RE"]
        vp = _viewport_of(doc, re_view.Id)
        if vp is not None and vp.SheetId != sheet.Id:
            result["conflicts"].append(
                (re_name, "view already placed on another sheet"))
        elif vp is not None:
            re_center = vp.GetBoxCenter()            # existing -> left untouched
        elif Viewport.CanAddViewToSheet(doc, sheet.Id, re_view.Id):
            vp = Viewport.Create(doc, sheet.Id, re_view.Id, anchor)
            vp.SetBoxCenter(anchor)
            re_center = vp.GetBoxCenter()
            result["placed"].append((re_name, sheet.SheetNumber))
        else:
            result["skipped"].append((re_name, "cannot add to sheet"))

    # --- Growing follows Reaching: move it only when they differ, no title ---
    target = re_center if re_center is not None else anchor
    gr_view = view_by_flavor.get("GR")
    if gr_view is not None:
        gr_name = name_by_flavor["GR"]
        vp = _viewport_of(doc, gr_view.Id)
        if vp is not None and vp.SheetId != sheet.Id:
            result["conflicts"].append(
                (gr_name, "view already placed on another sheet"))
        else:
            if vp is None:
                if Viewport.CanAddViewToSheet(doc, sheet.Id, gr_view.Id):
                    vp = Viewport.Create(doc, sheet.Id, gr_view.Id, target)
                    vp.SetBoxCenter(target)
                    result["placed"].append((gr_name, sheet.SheetNumber))
                else:
                    result["skipped"].append((gr_name, "cannot add to sheet"))
                    vp = None
            else:
                # already placed: realign to RE only if it has drifted
                if re_center is not None and not _same_xy(vp.GetBoxCenter(),
                                                          re_center):
                    vp.SetBoxCenter(re_center)
                    result["realigned"].append((gr_name, sheet.SheetNumber))
            if vp is not None:
                _apply_no_title_type(vp, no_title_type_id)  # Growing: no title
