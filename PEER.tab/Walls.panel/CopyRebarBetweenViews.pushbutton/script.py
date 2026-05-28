# -*- coding: utf-8 -*-
__title__  = 'Copy Rebar\nBetween Views'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-05-19
Description: Copies all view-specific elements (rebar shapes, tags,
             lines, hatches, annotations) from one view to another.
             PEER_Rebar TAG elements are re-linked to new rebar IDs.
How-To:
    1. Select source view (left list)
    2. Select target view (right list)
    3. Click Copy
'''

from Autodesk.Revit.DB import (
    FilteredElementCollector, Viewport, ElementTransformUtils,
    CopyPasteOptions, Transform, ElementId, Transaction, View, XYZ
)
import Autodesk.Revit.DB as DB
from Autodesk.Revit.UI import *
from pyrevit import forms, script
from System.Collections.Generic import List
import System

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

TAG_FAMILY_PREFIX   = "PEER_Rebar TAG"
REBAR_FAMILY_PREFIX = "PEER_Rebar_Shape"
TAG_ID_PARAM        = "PR_Rebar_ID"

XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Copy Reinforcement Between Views"
        Width="640" Height="540"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize">
  <Grid Margin="14">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <TextBlock Grid.Row="0"
               Text="Copy Reinforcement Between Views"
               FontSize="14" FontWeight="Bold" Margin="0,0,0,12"/>

    <Grid Grid.Row="1">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="40"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <StackPanel Grid.Column="0">
        <TextBlock Text="Source View" FontWeight="SemiBold" Margin="0,0,0,4"/>
        <ListBox x:Name="source_list" Height="350" SelectionMode="Single"
                 ScrollViewer.VerticalScrollBarVisibility="Auto"/>
      </StackPanel>

      <TextBlock Grid.Column="1" Text="&#x2192;" FontSize="28"
                 VerticalAlignment="Center" HorizontalAlignment="Center"
                 Foreground="#555"/>

      <StackPanel Grid.Column="2">
        <TextBlock Text="Target View" FontWeight="SemiBold" Margin="0,0,0,4"/>
        <ListBox x:Name="target_list" Height="350" SelectionMode="Single"
                 ScrollViewer.VerticalScrollBarVisibility="Auto"/>
      </StackPanel>
    </Grid>

    <TextBlock x:Name="status_label" Grid.Row="2"
               Margin="0,10,0,10" TextWrapping="Wrap" Foreground="#555"/>

    <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btn_cancel" Content="Cancel" Width="80" Margin="0,0,10,0"/>
      <Button x:Name="btn_copy"   Content="Copy"   Width="80" IsEnabled="False"
              Background="#0078D7" Foreground="White"/>
    </StackPanel>
  </Grid>
</Window>
"""


def get_views_on_sheets():
    viewports = FilteredElementCollector(doc).OfClass(Viewport).ToElements()
    view_ids = set(vp.ViewId for vp in viewports)
    views = []
    for vid in view_ids:
        v = doc.GetElement(vid)
        if v and not v.IsTemplate:
            views.append(v)
    views.sort(key=lambda v: v.Name)
    return views


def count_view_elements(view):
    collector = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
    return sum(1 for e in collector if e.ViewSpecific and e.OwnerViewId == view.Id)


def _parse_id(raw):
    if not raw:
        return None
    s = raw.strip()
    if s.isdigit():
        return int(s)
    digits = ''.join(c for c in s if c.isdigit())
    return int(digits) if digits else None


def _cat_name(e):
    try:
        c = e.Category
        return c.Name if c is not None else '<no category>'
    except Exception:
        return '<error>'


def _fam_name(e):
    try:
        sym = getattr(e, 'Symbol', None)
        if sym is not None:
            fn = getattr(sym, 'FamilyName', None)
            if fn:
                return fn
            fam = getattr(sym, 'Family', None)
            if fam is not None:
                return fam.Name
    except Exception:
        pass
    try:
        et = doc.GetElement(e.GetTypeId())
        if et is not None:
            fn = getattr(et, 'FamilyName', None)
            if fn:
                return fn
    except Exception:
        pass
    return ''


# Number parameter can have several names in PEER families
# (matches the production RebarForTag script, incl. the 'Nimber' typo).
NUMBER_PARAM_NAMES = ["Rebar Number", "Rebar_Number", "Rebar_Nimber"]


def _get_universal_value(elem, pname):
    """Read a param from the instance, falling back to its type."""
    if not elem:
        return None
    p = elem.LookupParameter(pname)
    if not p:
        try:
            et = doc.GetElement(elem.GetTypeId())
        except Exception:
            et = None
        if et:
            p = et.LookupParameter(pname)
    if not p:
        return None
    try:
        if p.StorageType == DB.StorageType.String:
            v = p.AsString()
            if v:
                return v
        vs = p.AsValueString()
        if vs:
            return vs
        if p.StorageType == DB.StorageType.Integer:
            return str(p.AsInteger())
    except Exception:
        pass
    return None


def _norm_num(val):
    """Normalize a rebar number to a stable string key ('5.0' -> '5')."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        f = float(s.replace(',', '.'))
        if f == int(f):
            return str(int(f))
        return str(f)
    except Exception:
        return s


def _get_rebar_number(e):
    for pn in NUMBER_PARAM_NAMES:
        v = _get_universal_value(e, pn)
        if v:
            return _norm_num(v)
    return None


def _loc_point(e):
    try:
        loc = e.Location
        if loc is not None:
            if hasattr(loc, 'Point') and loc.Point is not None:
                return loc.Point
            if hasattr(loc, 'Curve') and loc.Curve is not None:
                c = loc.Curve
                return c.Evaluate(0.5, True)
    except Exception:
        pass
    try:
        bb = e.get_BoundingBox(None)
        if bb is not None:
            return XYZ((bb.Min.X + bb.Max.X) / 2.0,
                      (bb.Min.Y + bb.Max.Y) / 2.0,
                      (bb.Min.Z + bb.Max.Z) / 2.0)
    except Exception:
        pass
    return None


def _xy_dist(a, b):
    if a is None or b is None:
        return None
    dx = a.X - b.X
    dy = a.Y - b.Y
    return (dx * dx + dy * dy) ** 0.5


def _param_value_str(p):
    """Current value of a PR_Rebar_ID-like param as a digit string."""
    try:
        if p.StorageType == DB.StorageType.String:
            return (p.AsString() or '').strip()
        if p.StorageType == DB.StorageType.Integer:
            return str(p.AsInteger())
        vs = p.AsValueString()
        if vs:
            return vs.strip()
    except Exception:
        pass
    return ''


def _read_pr_id(tag):
    """Return the writable PR_Rebar_ID param and its current int value."""
    p = tag.LookupParameter(TAG_ID_PARAM)
    if p is None or p.IsReadOnly:
        return None, None
    return p, _parse_id(_param_value_str(p))


def _write_pr_id(p, new_id_int):
    """Write new id respecting storage type; verify by reading back.
    Returns True only if the value actually changed and stuck.
    """
    st = p.StorageType
    try:
        if st == DB.StorageType.Integer:
            p.Set(int(new_id_int))
        elif st == DB.StorageType.String:
            p.Set(str(new_id_int))
        else:
            # unknown: try int then string
            try:
                p.Set(int(new_id_int))
            except Exception:
                p.Set(str(new_id_int))
    except Exception:
        return False
    return _parse_id(_param_value_str(p)) == int(new_id_int)


def _relink_tags(new_ids_list, id_mapping, out=None):
    """Re-link copied PEER_Rebar TAG instances to the copied rebar.

    The copied tag still holds the OLD rebar id (from the source view).
    The OLD rebar still exists -> read its TYPE + XY position. Among the
    copied elements find the one of the SAME type at the SAME XY
    (Transform.Identity / z-offset keep XY) -> that is the new rebar.
    Write its id into the tag's PR_Rebar_ID. No dependence on parameter
    names or on CopyElements return order.
    """
    new_elems = [doc.GetElement(i) for i in new_ids_list]
    new_elems = [e for e in new_elems if e is not None]

    tags = []
    copies_by_type = {}   # old typeId int -> list of (elem, xy point)
    for e in new_elems:
        fn = _fam_name(e)
        if fn and TAG_FAMILY_PREFIX in fn:
            tags.append(e)
            continue
        try:
            tid = e.GetTypeId().IntegerValue
        except Exception:
            continue
        copies_by_type.setdefault(tid, []).append((e, _loc_point(e)))

    n_ok = 0
    n_write_fail = 0
    storage_seen = set()
    mapping_rows = []
    unresolved = []

    for tag in tags:
        id_param, old_id = _read_pr_id(tag)
        if id_param is None:
            unresolved.append([tag.Id.IntegerValue, '-',
                               'PR_Rebar_ID missing / read-only'])
            continue
        if old_id is None:
            unresolved.append([tag.Id.IntegerValue, '-',
                               'PR_Rebar_ID empty / not a number'])
            continue

        old_rebar = doc.GetElement(ElementId(old_id))
        if old_rebar is None:
            unresolved.append([tag.Id.IntegerValue, old_id,
                               'old rebar element not found'])
            continue

        try:
            old_type = old_rebar.GetTypeId().IntegerValue
        except Exception:
            old_type = None
        old_xy = _loc_point(old_rebar)

        candidates = copies_by_type.get(old_type) or []
        best, best_d = None, None
        for rb, rp in candidates:
            d = _xy_dist(old_xy, rp)
            if d is None:
                continue
            if best_d is None or d < best_d:
                best_d, best = d, rb

        # Last-resort fallback: copy id-mapping by order
        if best is None and old_id in id_mapping:
            best = doc.GetElement(id_mapping[old_id])

        if best is not None:
            try:
                storage_seen.add(str(id_param.StorageType))
            except Exception:
                pass
            if _write_pr_id(id_param, best.Id.IntegerValue):
                n_ok += 1
                if len(mapping_rows) < 60:
                    mapping_rows.append([
                        tag.Id.IntegerValue, old_id, best.Id.IntegerValue,
                        '{:.4f}'.format(best_d) if best_d is not None
                        else 'fallback'])
            else:
                n_write_fail += 1
                unresolved.append([tag.Id.IntegerValue, old_id,
                                   'Set() did not stick (storage={})'.format(
                                       id_param.StorageType)])
        else:
            unresolved.append([tag.Id.IntegerValue, old_id,
                               'no copied element of same type at XY'])

    if out is not None:
        out.print_md('## Tag re-link: old rebar id -> new rebar id')
        out.print_md('Tags found: **{}**, copied element types: **{}**, '
                      'PR_Rebar_ID storage: {}'.format(
                          len(tags), len(copies_by_type),
                          ', '.join(sorted(storage_seen)) or '?'))
        if mapping_rows:
            out.print_table(mapping_rows,
                            columns=['Tag id', 'OLD rebar id',
                                     'NEW rebar id', 'XY dist (ft)'])
        out.print_md('**Tags re-linked (verified): {} ok, '
                      '{} write-failed, {} unresolved**'.format(
                          n_ok, n_write_fail,
                          len(unresolved) - n_write_fail))
        if unresolved:
            out.print_table(unresolved[:50],
                            columns=['Tag id', 'OLD rebar id', 'Reason'])
    return n_ok


def copy_elements(source_view, target_view):
    out = script.get_output()
    out.print_md('# Copy Rebar Between Views')
    out.print_md('**Source:** {} (id {})  ->  **Target:** {} (id {})'.format(
        source_view.Name, source_view.Id.IntegerValue,
        target_view.Name, target_view.Id.IntegerValue))

    collector = FilteredElementCollector(doc, source_view.Id).WhereElementIsNotElementType()
    all_view_specific = [e for e in collector
                         if e.ViewSpecific and e.OwnerViewId == source_view.Id]

    # Drop elements that are NOT real annotations and that make Revit
    # spawn a phantom source-view copy (no-category element, the view
    # itself, sketch/datum helpers). The user only wants annotations +
    # reinforcement detail items.
    elements_to_copy = []
    skipped = []
    for e in all_view_specific:
        cat = None
        try:
            cat = e.Category
        except Exception:
            cat = None
        if cat is None:
            skipped.append([e.Id.IntegerValue, type(e).__name__, '<no category>'])
            continue
        if isinstance(e, DB.View):
            skipped.append([e.Id.IntegerValue, type(e).__name__, cat.Name])
            continue
        elements_to_copy.append(e)

    if skipped:
        out.print_md('## Skipped (not annotations — would force phantom view)')
        out.print_table(skipped, columns=['Id', 'Class', 'Category'])

    if not elements_to_copy:
        forms.alert('No annotation / reinforcement elements found in source view.',
                    title='Nothing to Copy')
        return

    old_ids_list = [e.Id for e in elements_to_copy]
    elem_ids = List[ElementId](old_ids_list)
    out.print_md('Elements to copy: **{}** (skipped {})'.format(
        len(elem_ids), len(skipped)))

    target_int = target_view.Id.IntegerValue
    source_int = source_view.Id.IntegerValue

    # Z offset between the two views' levels (different levels = different
    # work plane elevation; without this Revit cannot host the pasted
    # annotations in the target and duplicates the source view instead).
    def _view_elev(v):
        try:
            lv = v.GenLevel
            if lv is not None:
                return lv.ProjectElevation
        except Exception:
            pass
        return None

    s_elev = _view_elev(source_view)
    t_elev = _view_elev(target_view)
    dz = 0.0
    if s_elev is not None and t_elev is not None:
        dz = t_elev - s_elev
    out.print_md('Source level elev: {} | Target level elev: {} | dZ: {}'.format(
        s_elev, t_elev, dz))

    # Make target the active view (mirrors UI "Paste Aligned to Current View").
    try:
        if uidoc.ActiveView.Id.IntegerValue != target_int:
            uidoc.ActiveView = target_view
    except Exception as ex:
        out.print_md('Could not activate target view: {}'.format(ex))

    def _attempt(transform, label):
        """One copy attempt in its own transaction.
        Commits only if elements land in the target view; otherwise
        rolls back (no junk views left). Returns result dict."""
        res = {'ok': False, 'landed': {}, 'in_target': 0,
               'survived': 0, 'tags': 0, 'err': None, 'label': label}
        t = Transaction(doc, 'Copy Rebar View ({}): {} -> {}'.format(
            label, source_view.Name, target_view.Name))
        t.Start()
        try:
            opts = CopyPasteOptions()
            new_ids = ElementTransformUtils.CopyElements(
                source_view, elem_ids, target_view, transform, opts)
            new_ids_list = list(new_ids)

            landed = {}
            for nid in new_ids_list:
                ne = doc.GetElement(nid)
                ov = ne.OwnerViewId.IntegerValue if (ne and ne.OwnerViewId) else -1
                landed[ov] = landed.get(ov, 0) + 1
            res['landed'] = landed
            res['in_target'] = landed.get(target_int, 0)

            if res['in_target'] == 0:
                t.RollBack()
                return res

            id_mapping = {}
            for old_id, new_id in zip(old_ids_list, new_ids_list):
                id_mapping[old_id.IntegerValue] = new_id
            res['tags'] = _relink_tags(new_ids_list, id_mapping, out)

            doc.Regenerate()
            t.Commit()
            res['ok'] = True
            res['survived'] = sum(1 for nid in new_ids_list
                                  if doc.GetElement(nid) is not None)
            return res
        except Exception:
            import traceback
            res['err'] = traceback.format_exc()
            try:
                t.RollBack()
            except Exception:
                pass
            return res

    # Try identity first (same place); if Revit spawns a phantom view,
    # retry with the level Z-offset.
    attempts = [(Transform.Identity, 'identity')]
    if abs(dz) > 1e-9:
        attempts.append((Transform.CreateTranslation(XYZ(0, 0, dz)), 'z-offset'))

    result = None
    for tf, label in attempts:
        out.print_md('### Attempt: {}'.format(label))
        result = _attempt(tf, label)
        if result['err']:
            out.print_md('Exception:\n```\n{}\n```'.format(result['err']))
            continue
        obr = []
        for k, v in sorted(result['landed'].items(), key=lambda kv: -kv[1]):
            mark = ' (copy of SOURCE view)' if k == source_int else (
                ' <-- TARGET' if k == target_int else '')
            obr.append([str(k) + mark, v])
        out.print_table(obr, columns=['Landed in view id', 'Count'])
        if result['ok']:
            break

    if result is None or not result['ok']:
        forms.alert(
            'Copy failed: Revit kept pasting into a phantom view.\n'
            'Rolled back — no junk views created.\n\n'
            'See pyRevit output for details.',
            title='Copy Failed')
        return

    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass

    out.print_md('## RESULT: OK ({})'.format(result['label']))
    out.print_table(
        [['Collected', len(elem_ids)],
         ['Pasted into TARGET view', result['in_target']],
         ['Verified in model', result['survived']],
         ['Tags re-linked', result['tags']]],
        columns=['Metric', 'Value'])

    forms.alert(
        'Done!\n\nCopied into target view: {}\nVerified in model: {}\n'
        'Tags re-linked: {}'.format(
            result['in_target'], result['survived'], result['tags']),
        title='Copy Complete')


class CopyRebarWindow(forms.WPFWindow):
    def __init__(self, views):
        forms.WPFWindow.__init__(self, XAML, literal_string=True)
        self._views = views
        self._populate_lists()
        self.btn_cancel.Click += self._on_cancel
        self.btn_copy.Click   += self._on_copy
        self.source_list.SelectionChanged += self._on_selection_changed
        self.target_list.SelectionChanged  += self._on_selection_changed

    def _populate_lists(self):
        from System.Windows.Controls import ListBoxItem
        for v in self._views:
            for lb in (self.source_list, self.target_list):
                item = ListBoxItem()
                item.Content = v.Name
                item.Tag = v
                lb.Items.Add(item)

    def _get_selected_view(self, listbox):
        item = listbox.SelectedItem
        if item is None:
            return None
        return item.Tag

    def _on_selection_changed(self, sender, args):
        self._update_status()

    def _update_status(self):
        src = self._get_selected_view(self.source_list)
        tgt = self._get_selected_view(self.target_list)

        same = (src is not None and tgt is not None and
                src.Id == tgt.Id)

        ready = src is not None and tgt is not None and not same
        self.btn_copy.IsEnabled = ready

        if same:
            self.status_label.Text = 'Source and target must be different views.'
            self.status_label.Foreground = \
                System.Windows.Media.Brushes.OrangeRed
            return

        parts = []
        if src:
            n = count_view_elements(src)
            parts.append('Source: {} view-specific elements'.format(n))
        if tgt:
            n = count_view_elements(tgt)
            if n > 0:
                parts.append('WARNING: Target already has {} elements — they will NOT be deleted before copy.'.format(n))
            else:
                parts.append('Target: empty')

        self.status_label.Text = '   '.join(parts)
        self.status_label.Foreground = \
            System.Windows.Media.Brushes.DimGray

    def _on_cancel(self, sender, args):
        self.Close()

    def _on_copy(self, sender, args):
        src = self._get_selected_view(self.source_list)
        tgt = self._get_selected_view(self.target_list)
        if src is None or tgt is None:
            return
        if src.Id == tgt.Id:
            forms.alert('Source and target views must be different!', title='Error')
            return
        self.Close()
        copy_elements(src, tgt)


if __name__ == '__main__':
    views = get_views_on_sheets()
    if not views:
        forms.alert('No views found on sheets.', title='Error')
    else:
        win = CopyRebarWindow(views)
        win.ShowDialog()
