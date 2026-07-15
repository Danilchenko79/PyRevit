# -*- coding: utf-8 -*-
__title__ = "Create\nWorksets"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Creates the project worksets and (optionally) the AR coordination filters,
then pushes those filters to the chosen view templates.

ONE WINDOW, IN ORDER:
1. Worksets - edit the list (one per line). Existing ones are skipped.
2. Concrete walls - type the text found in the CONCRETE wall type names
   (comma-separated for several variants). The read-only list on the right
   shows the wall types present in the LINKED models for reference only.
   Every other wall is treated as a partition and recoloured separately.
3. View templates - tick the templates that should get the filters.
   "PEER Work" and "PEER Work SEC" are pre-selected.

RULES OF USE
- Run in a PROJECT file (not a family).
- If worksharing is OFF it is enabled automatically (can be unticked).
- Worksets are created first; filters run only if that succeeds.
- NOTE: view filters affect linked (architectural) walls only when the
  link visibility in the template is set to Custom / By linked view.
"""

import re

from pyrevit import forms, script

from Autodesk.Revit.DB import (
    Transaction, Workset, WorksetKind, FilteredWorksetCollector,
    FilteredElementCollector, View, BuiltInCategory, RevitLinkInstance
)

from System.Windows.Controls import CheckBox
from System.Windows import Thickness

# Shared logic for the coordination filters (also callable on its own).
from Samples import CreateFilters

doc = __revit__.ActiveUIDocument.Document   # type: Document

logger = script.get_logger()
output = script.get_output()

# ============================================================
# DEFAULTS (pre-filled into the window, fully editable)
# ============================================================
DEFAULT_WORKSETS = [
    u"+AR Link",
    u"+ST Link",
    u"+ME Link",
    u"+EL Link",
    u"+PL Link",
    u"+LS Link",
    u"+CO Link",
    u"Construction",
]
DEFAULT_CONCRETE_KEYWORDS = u"CON"
# These templates are always ticked by default (if they exist in the model).
DEFAULT_TEMPLATE_NAMES = [u"PEER Work", u"PEER Work SEC"]

# Default worksets created when worksharing is enabled automatically.
DEFAULT_WS_LEVELS_GRIDS = u"Shared Levels and Grids"
DEFAULT_WS_WORKSET1 = u"Workset1"


# ============================================================
# WORKSET HELPERS
# ============================================================
def sanitize_name(name):
    """Strip invalid characters and collapse repeated underscores."""
    if name is None:
        return u""
    name = unicode(name).strip()
    name = re.sub(ur'[\/\\\:\;\*\?\"\<\>\|\x00-\x1F]', u"_", name)
    name = re.sub(ur'_+', u'_', name)
    return name


def ensure_worksharing(document, auto_enable):
    """Enable worksharing if needed. Returns True if it was just enabled."""
    if document.IsWorkshared:
        return False
    if not auto_enable:
        raise Exception(u"Worksharing is OFF in this file. Enable it manually "
                        u"or tick 'Auto-enable worksharing'.")
    document.EnableWorksharing(DEFAULT_WS_LEVELS_GRIDS, DEFAULT_WS_WORKSET1)
    return True


def collect_existing_user_worksets(document):
    return set(ws.Name for ws in
               FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset))


def create_worksets(document, names, auto_enable):
    """Create the given worksets. Returns a result dict."""
    if document.IsFamilyDocument:
        raise Exception(u"This is a family document. Worksets only exist in "
                        u"project (RVT) files.")

    enabled_now = ensure_worksharing(document, auto_enable)

    existing = collect_existing_user_worksets(document)
    created, skipped, errors = [], [], []

    t = Transaction(document, "Create Worksets from List")
    t.Start()
    try:
        for raw in names:
            base = sanitize_name(raw)
            if not base:
                continue
            if base in existing:
                skipped.append(base)
                continue
            try:
                Workset.Create(document, base)
                existing.add(base)
                created.append(base)
            except Exception as ex:
                errors.append((base, unicode(ex)))
        t.Commit()
    except Exception:
        t.RollBack()
        raise

    return {
        "enabled_now": enabled_now,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


# ============================================================
# UI
# ============================================================
def _split_lines(text):
    return [ln.strip() for ln in (text or u"").splitlines() if ln.strip()]


def _split_csv(text):
    return [p.strip() for p in (text or u"").replace(u";", u",").split(u",") if p.strip()]


def _norm(name):
    """Lower-case, whitespace-collapsed name for tolerant matching."""
    return u" ".join((name or u"").lower().split())


def collect_view_templates(document):
    """All view-template names in the document, sorted (defaults first)."""
    names = set(v.Name for v in FilteredElementCollector(document).OfClass(View)
                if v.IsTemplate)
    defaults_norm = [_norm(n) for n in DEFAULT_TEMPLATE_NAMES]
    return sorted(names, key=lambda n: (_norm(n) not in defaults_norm, n.lower()))


def _wall_type_names_in(document):
    """Distinct wall *type* names actually used by wall instances in a doc."""
    names = set()
    walls = (FilteredElementCollector(document)
             .OfCategory(BuiltInCategory.OST_Walls)
             .WhereElementIsNotElementType())
    for w in walls:
        try:
            names.add(w.Name)   # Wall.Name returns its type name
        except Exception:
            pass
    return names


def collect_wall_type_names(document):
    """Wall type names used by walls in the LINKED models only.

    Architectural walls live in links, so the host model is intentionally not
    scanned. Unloaded or unreadable links are skipped silently. Sorted list.
    """
    names = set()
    for link in FilteredElementCollector(document).OfClass(RevitLinkInstance):
        try:
            ldoc = link.GetLinkDocument()
        except Exception:
            ldoc = None
        if ldoc is None:
            continue
        names |= _wall_type_names_in(ldoc)
    return sorted(names, key=lambda n: n.lower())


class WorksetsWindow(forms.WPFWindow):
    """Single window collecting worksets + filter settings."""

    def __init__(self, xaml_path):
        forms.WPFWindow.__init__(self, xaml_path)
        self.tb_worksets.Text = u"\n".join(DEFAULT_WORKSETS)
        self.tb_concrete.Text = DEFAULT_CONCRETE_KEYWORDS
        self.cb_filters.IsChecked = True
        self.cb_worksharing.IsChecked = True

        # Read-only reference list (right side): the wall types found in the
        # links, just to look at while typing the substring into tb_concrete.
        wall_types = collect_wall_type_names(doc)
        self.tb_walltypes.Text = (u"\n".join(wall_types) if wall_types
                                  else u"(no walls found in loaded links)")

        # View-template checkboxes; the two defaults start ticked.
        defaults_norm = [_norm(n) for n in DEFAULT_TEMPLATE_NAMES]
        for tname in collect_view_templates(doc):
            chk = CheckBox()
            chk.Content = tname
            chk.Tag = tname
            chk.IsChecked = _norm(tname) in defaults_norm
            chk.Margin = Thickness(2, 3, 2, 3)
            self.templates_panel.Children.Add(chk)

    def selected_templates(self):
        return [chk.Tag for chk in self.templates_panel.Children
                if isinstance(chk, CheckBox) and chk.IsChecked]

    def concrete_keywords(self):
        """Concrete keywords typed into the box (comma-separated substrings).

        Each is matched as a type-name 'contains' substring; every wall that
        contains none of them is treated as a partition.
        """
        return _split_csv(self.tb_concrete.Text)

    def on_ok(self, sender, args):
        if not _split_lines(self.tb_worksets.Text):
            forms.alert(u"Enter at least one workset name.", title=__title__)
            return
        if self.cb_filters.IsChecked and not self.selected_templates():
            forms.alert(u"Tick at least one view template, or untick "
                        u"'Create / update coordination filters'.", title=__title__)
            return
        if self.cb_filters.IsChecked and not self.concrete_keywords():
            if not forms.alert(
                    u"No concrete substring is entered.\nEvery wall will be "
                    u"treated as a partition (recoloured). Continue anyway?",
                    title=__title__, yes=True, no=True):
                return
        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()


# ============================================================
# MAIN
# ============================================================
def main():
    window = WorksetsWindow(script.get_bundle_file('WorksetsForm.xaml'))
    window.ShowDialog()
    if not window.DialogResult:
        return

    worksets = _split_lines(window.tb_worksets.Text)
    concrete_keywords = window.concrete_keywords()
    templates = list(window.selected_templates())
    make_filters = bool(window.cb_filters.IsChecked)
    auto_enable = bool(window.cb_worksharing.IsChecked)

    # --- worksets ---
    try:
        result = create_worksets(doc, worksets, auto_enable)
    except Exception as ex:
        forms.alert(u"Worksets were not created:\n{}".format(unicode(ex)),
                    title=__title__, warn_icon=True)
        return

    lines = []
    if result["enabled_now"]:
        lines.append(u"Worksharing was OFF and has been enabled automatically.")
    if result["created"]:
        lines.append(u"Created: {}".format(u"; ".join(result["created"])))
    if result["skipped"]:
        lines.append(u"Already existed: {}".format(u"; ".join(result["skipped"])))
    if result["errors"]:
        lines.append(u"Errors:")
        for name, err in result["errors"]:
            lines.append(u"  - {} -> {}".format(name, err))
    output.print_md(u"### Worksets\n" + (u"\n\n".join(lines) if lines else u"Nothing to do."))

    # --- filters (only after worksets succeeded) ---
    if not make_filters:
        return
    try:
        CreateFilters.run(
            concrete_keywords=concrete_keywords,
            target_templates=templates,
        )
    except Exception as ex:
        forms.alert(u"Worksets are OK, but filters failed:\n{}".format(unicode(ex)),
                    title=__title__, warn_icon=True)


if __name__ == "__main__":
    main()
