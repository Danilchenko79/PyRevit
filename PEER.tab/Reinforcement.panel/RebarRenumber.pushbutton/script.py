# -*- coding: utf-8 -*-
__title__ = "Rebar Renumber v.3"
__doc__ = "Renumbering + Smart Tag Update + QA Report"
__author__ = "BIM Specialist"

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *
import re
from collections import defaultdict
import System.Collections.Generic
from System.Windows.Controls import CheckBox
from System.Windows import Thickness

doc = revit.doc
output = script.get_output()

TAG_FAMILY_NAME = "PEER_Rebar TAG"
SKIP_NUMBERS = {8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 32}


# ─────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────────────────────

def extract_number_from_string(value_string):
    if not value_string:
        return 0
    match = re.search(r"[-+]?\d*\.\d+|\d+", str(value_string).replace(',', '.'))
    return float(match.group()) if match else 0


def get_inst_param_raw(e, n):
    """Строковое представление параметра экземпляра для любого StorageType."""
    p = e.LookupParameter(n)
    if not p:
        return ""
    if p.StorageType == StorageType.Double:
        return p.AsValueString() or ""
    if p.StorageType == StorageType.String:
        return p.AsString() or ""
    if p.StorageType == StorageType.Integer:
        return str(p.AsInteger())
    return ""


def get_type_param_raw(elem, param_name):
    """Строковое представление параметра типа для любого StorageType."""
    param = elem.Symbol.LookupParameter(param_name)
    if not param:
        return ""
    if param.StorageType == StorageType.Double:
        return param.AsValueString() or ""
    if param.StorageType == StorageType.String:
        return param.AsString() or ""
    if param.StorageType == StorageType.Integer:
        return str(param.AsInteger())
    return ""


def get_geometry_key(item):
    r_shape = get_type_param_raw(item, "Rebar_Shape")
    r_dia   = extract_number_from_string(get_inst_param_raw(item, "Rebar_Diameter"))
    r_len   = extract_number_from_string(get_inst_param_raw(item, "Rebar_Length"))
    r_a     = extract_number_from_string(get_inst_param_raw(item, "Rebar_A"))
    return (r_shape, round(r_dia, 3), round(r_len, 3), round(r_a, 3))


def has_mark_value(item):
    p = item.LookupParameter("Mark")
    return bool(p and p.HasValue and p.AsString() and p.AsString().strip())


def get_current_number(item):
    val = get_inst_param_raw(item, "Rebar_Number")
    if not val:
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def get_sheet_from_view(view):
    if isinstance(view, ViewSheet):
        return view
    for vp in FilteredElementCollector(doc).OfClass(Viewport):
        if vp.ViewId == view.Id:
            return doc.GetElement(vp.SheetId)
    return None


def parse_element_id(raw_id):
    if not raw_id:
        return None
    s = raw_id.strip()
    if s.isdigit():
        return int(s)
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None


def format_key_label(key, item_count):
    """Человекочитаемое описание геометрии из ключа."""
    shape, dia, length, a = key
    def fv(v):
        return str(int(v)) if v == int(v) else str(round(v, 1))
    parts = []
    if shape:
        parts.append(u"Form:{}".format(shape))
    parts.append(u"O{}".format(fv(dia)))
    if length:
        parts.append(u"L={}".format(fv(length)))
    if a:
        parts.append(u"A={}".format(fv(a)))
    parts.append(u"{}pcs".format(item_count))
    return u" | ".join(parts)


def update_smart(tag, param_name, new_val_internal, new_val_str):
    p = tag.LookupParameter(param_name)
    if not p or p.IsReadOnly:
        return False, None, None
    if p.StorageType == StorageType.Double:
        old_str = p.AsValueString() or ""
    elif p.StorageType == StorageType.String:
        old_str = p.AsString() or ""
    elif p.StorageType == StorageType.Integer:
        old_str = str(p.AsInteger())
    else:
        old_str = ""
    if new_val_str is None:
        new_val_str = ""
    if old_str == new_val_str:
        return False, old_str, new_val_str
    try:
        if p.StorageType == StorageType.Double:
            if new_val_internal is None:
                return False, old_str, new_val_str
            p.Set(float(new_val_internal))
        elif p.StorageType == StorageType.Integer:
            try:
                p.Set(int(float(new_val_internal)))
            except (TypeError, ValueError):
                p.Set(int(float(new_val_str or 0)))
        elif p.StorageType == StorageType.String:
            p.Set(new_val_str)
        return True, old_str, new_val_str
    except Exception:
        return False, old_str, new_val_str


# ─────────────────────────────────────────────────────────────────────────────
# ЛОГИКА НУМЕРАЦИИ (вынесена в функцию для поддержки per-sheet режима)
# ─────────────────────────────────────────────────────────────────────────────

def compute_numbering(items_subset, mode):
    """
    Вычисляет новые Rebar_Number для списка элементов.
    Возвращает (items_with_new_rebar_number, conflict_log_lines).
    """
    result_items = []
    c_log = []

    if not items_subset:
        return result_items, c_log

    if mode == "Full":
        grouped = defaultdict(list)
        for i in items_subset:
            grouped[i["key"]].append(i)
        current_number = 1
        for key in sorted(grouped.keys()):
            while current_number in SKIP_NUMBERS:
                current_number += 1
            for item_dict in grouped[key]:
                item_dict["new_rebar_number"] = current_number
                result_items.append(item_dict)
            current_number += 1

    elif mode == "Update":
        new_items = []
        old_grouped = defaultdict(list)
        for i in items_subset:
            if i["is_old"]:
                old_grouped[i["key"]].append(i)
            else:
                new_items.append(i)

        key_target = {}
        for key, group_items in old_grouped.items():
            used_numbers = {x["current_num"] for x in group_items if x["current_num"] > 0}
            target_num = min(used_numbers) if used_numbers else 0
            key_target[key] = (target_num, group_items)

        num_to_candidates = defaultdict(list)
        for key, (tnum, gitems) in key_target.items():
            if tnum > 0:
                num_to_candidates[tnum].append((key, gitems))

        conflicts = {num: cands
                     for num, cands in num_to_candidates.items()
                     if len(cands) > 1}

        conflict_winner = {}
        for conflict_num in sorted(conflicts.keys()):
            cands = conflicts[conflict_num]
            sorted_cands = sorted(cands, key=lambda x: x[0])
            winner_key = sorted_cands[0][0]
            conflict_winner[conflict_num] = winner_key
            loser_descs = [format_key_label(k, len(it)) for k, it in sorted_cands[1:]]
            c_log.append(
                u"  **#{}** auto-resolved: keeps -> {}  |  renumbered -> {}".format(
                    conflict_num,
                    format_key_label(winner_key, len(sorted_cands[0][1])),
                    u", ".join(loser_descs)))

        existing_db = {}
        max_num = 0
        for key, (target_num, group_items) in key_target.items():
            if target_num == 0:
                new_items.extend(group_items)
                continue
            if target_num in conflicts:
                if conflict_winner.get(target_num) != key:
                    new_items.extend(group_items)
                    continue
            existing_db[key] = target_num
            if target_num > max_num:
                max_num = target_num
            for item in group_items:
                item["new_rebar_number"] = target_num
                result_items.append(item)

        new_items.sort(key=lambda x: x["key"])
        curr_new_num = max_num + 1
        for i in new_items:
            key = i["key"]
            if key in existing_db:
                i["new_rebar_number"] = existing_db[key]
            else:
                while curr_new_num in SKIP_NUMBERS:
                    curr_new_num += 1
                i["new_rebar_number"] = curr_new_num
                existing_db[key] = curr_new_num
                curr_new_num += 1
            result_items.append(i)

    return result_items, c_log


# ─────────────────────────────────────────────────────────────────────────────
# WPF: ОДНО ОКНО НАСТРОЙКИ (листы + режим + охват)
# ─────────────────────────────────────────────────────────────────────────────

SETUP_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Rebar Renumber"
        Width="600" Height="650" MinWidth="400" MinHeight="420"
        ResizeMode="CanResizeWithGrip"
        WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI" FontSize="13">
    <Grid Margin="16,14,16,14">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*" MinHeight="80"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Sheets -->
        <TextBlock Grid.Row="0" Text="Sheets:" FontWeight="Bold" Margin="0,0,0,5"/>
        <Border Grid.Row="1" BorderBrush="#BBBBBB" BorderThickness="1" Background="White">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="sheets_panel" Margin="6,4,6,4"/>
            </ScrollViewer>
        </Border>

        <Separator Grid.Row="2" Margin="0,12,0,10"/>

        <!-- Mode -->
        <StackPanel Grid.Row="3" Margin="0,0,0,12">
            <TextBlock Text="Mode:" FontWeight="Bold" Margin="0,0,0,6"/>
            <RadioButton x:Name="mode_full"
                         Content="Full Renumbering  -  reset all positions"
                         GroupName="mode" IsChecked="True" Margin="6,0,0,5"/>
            <RadioButton x:Name="mode_update"
                         Content="Only New + Unify Old  -  keep existing, add new"
                         GroupName="mode" Margin="6,0,0,0"/>
        </StackPanel>

        <Separator Grid.Row="4" Margin="0,0,0,10"/>

        <!-- Scope -->
        <StackPanel Grid.Row="5" Margin="0,0,0,16">
            <TextBlock Text="Numbering scope:" FontWeight="Bold" Margin="0,0,0,6"/>
            <RadioButton x:Name="scope_continuous"
                         Content="Continuous  -  single sequence across all sheets  (1, 2, 3 ...)"
                         GroupName="scope" IsChecked="True" Margin="6,0,0,5"/>
            <RadioButton x:Name="scope_per_sheet"
                         Content="Per-sheet  -  independent sequence on each sheet  (each starts at 1)"
                         GroupName="scope" Margin="6,0,0,0"/>
        </StackPanel>

        <!-- Buttons -->
        <StackPanel Grid.Row="6" Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="btn_cancel" Content="Cancel" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_cancel_click"/>
            <Button x:Name="btn_ok" Content="Run" Width="90" Height="30"
                    Click="btn_ok_click"/>
        </StackPanel>
    </Grid>
</Window>
"""


class SetupWindow(forms.WPFWindow):
    def __init__(self, all_sheets, detected_sheet=None):
        forms.WPFWindow.__init__(self, xaml_source=SETUP_XAML, literal_string=True)
        self.result = None
        for sheet in all_sheets:
            chk = CheckBox()
            chk.Content = u"{} - {}".format(sheet.SheetNumber, sheet.Name)
            chk.Tag = sheet
            chk.IsChecked = bool(detected_sheet and sheet.Id == detected_sheet.Id)
            chk.Margin = Thickness(2, 3, 2, 3)
            self.sheets_panel.Children.Add(chk)

    def btn_ok_click(self, sender, args):
        selected = [chk.Tag for chk in self.sheets_panel.Children
                    if isinstance(chk, CheckBox) and chk.IsChecked]
        if not selected:
            forms.alert("Please select at least one sheet.")
            return
        self.result = {
            "sheets": selected,
            "mode":   "Full"       if self.mode_full.IsChecked       else "Update",
            "scope":  "Continuous" if self.scope_continuous.IsChecked else "PerSheet",
        }
        self.Close()

    def btn_cancel_click(self, sender, args):
        self.result = None
        self.Close()


# ─────────────────────────────────────────────────────────────────────────────
# ПОКАЗАТЬ ОКНО НАСТРОЙКИ
# ─────────────────────────────────────────────────────────────────────────────

all_sheets = sorted(
    FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Sheets)
        .WhereElementIsNotElementType()
        .ToElements(),
    key=lambda x: x.SheetNumber
)
detected_sheet = get_sheet_from_view(doc.ActiveView)

win = SetupWindow(all_sheets, detected_sheet)
win.ShowDialog()

if not win.result:
    script.exit()

sheet_list = win.result["sheets"]
mode       = win.result["mode"]
scope      = win.result["scope"]

# ─────────────────────────────────────────────────────────────────────────────
# СБОР ДАННЫХ
# ─────────────────────────────────────────────────────────────────────────────

all_items = []
views_to_scan = []
processed_view_ids = set()
seen_elem_ids = set()

for s in sheet_list:
    views_to_scan.append(s)
    processed_view_ids.add(s.Id)

with forms.ProgressBar(title="Analyzing...", cancellable=True) as pb:
    for i, sheet in enumerate(sheet_list):
        pb.update_progress(i + 1, len(sheet_list))
        if pb.cancelled:
            script.exit()

        sheet_number = sheet.SheetNumber

        for vp_id in sheet.GetAllViewports():
            vp = doc.GetElement(vp_id)
            if not vp:
                continue
            view = doc.GetElement(vp.ViewId)
            if not view:
                continue

            if view.Id not in processed_view_ids:
                views_to_scan.append(view)
                processed_view_ids.add(view.Id)

            for item in (FilteredElementCollector(doc, view.Id)
                         .OfCategory(BuiltInCategory.OST_DetailComponents)
                         .WhereElementIsNotElementType()):

                if not isinstance(item, FamilyInstance):
                    continue
                if not item.Symbol.Family.Name.startswith("PEER_Rebar_Shape"):
                    continue
                if item.Id.IntegerValue in seen_elem_ids:
                    continue

                seen_elem_ids.add(item.Id.IntegerValue)
                all_items.append({
                    "elem":        item,
                    "key":         get_geometry_key(item),
                    "current_num": get_current_number(item),
                    "is_old":      has_mark_value(item),
                    "sheet_num":   sheet_number,
                })

# ─────────────────────────────────────────────────────────────────────────────
# НУМЕРАЦИЯ
# ─────────────────────────────────────────────────────────────────────────────

items_to_update = []
conflict_log = []

if scope == "Continuous":
    items_to_update, conflict_log = compute_numbering(all_items, mode)

else:  # PerSheet: каждый лист нумеруется независимо
    for sheet in sheet_list:
        sheet_items = [i for i in all_items if i["sheet_num"] == sheet.SheetNumber]
        if not sheet_items:
            continue
        sheet_result, sheet_log = compute_numbering(sheet_items, mode)
        items_to_update.extend(sheet_result)
        if sheet_log:
            conflict_log.append(u"**Sheet {}:**".format(sheet.SheetNumber))
            conflict_log.extend(sheet_log)

# ─────────────────────────────────────────────────────────────────────────────
# ТРАНЗАКЦИЯ
# ─────────────────────────────────────────────────────────────────────────────

changes_report = defaultdict(list)
updated_count = 0
missing_elements = []

with revit.Transaction("Renumber & Strict Sync"):

    # A. Запись номеров в арматуру
    rebar_new_values = {}
    count_rebar = 0

    for item in items_to_update:
        elem    = item["elem"]
        new_num = item["new_rebar_number"]
        sheet_n = item["sheet_num"]

        rebar_new_values[elem.Id.IntegerValue] = new_num

        p_num = elem.LookupParameter("Rebar_Number")
        if p_num and not p_num.IsReadOnly:
            if get_inst_param_raw(elem, "Rebar_Number") != str(new_num):
                p_num.Set(int(new_num))

        p_mark = elem.LookupParameter("Mark")
        if p_mark and not p_mark.IsReadOnly:
            p_mark.Set(sheet_n)

        count_rebar += 1

    doc.Regenerate()

    # B. Синхронизация тэгов
    cats = System.Collections.Generic.List[BuiltInCategory]()
    cats.Add(BuiltInCategory.OST_DetailComponents)
    cats.Add(BuiltInCategory.OST_GenericAnnotation)
    cats.Add(BuiltInCategory.OST_RebarTags)
    multi_filter = DB.ElementMulticategoryFilter(cats)

    annotation_instances = []
    seen_tag_ids = set()

    for view in views_to_scan:
        for el in (FilteredElementCollector(doc, view.Id)
                   .WherePasses(multi_filter)
                   .WhereElementIsNotElementType()
                   .ToElements()):
            if not isinstance(el, FamilyInstance):
                continue
            if TAG_FAMILY_NAME not in el.Symbol.Family.Name:
                continue
            if el.Id.IntegerValue in seen_tag_ids:
                continue
            seen_tag_ids.add(el.Id.IntegerValue)
            annotation_instances.append((el, view))

    for tag, view_obj in annotation_instances:
        source_id_param = tag.LookupParameter("PR_Rebar_ID")
        if not source_id_param:
            continue

        raw_id = None
        try:
            raw_id = source_id_param.AsString() or source_id_param.AsValueString()
            if not raw_id:
                continue

            target_id_int = parse_element_id(raw_id)
            if target_id_int is None:
                continue

            source_elem = doc.GetElement(ElementId(target_id_int))
            if not source_elem:
                missing_elements.append(str(target_id_int))
                continue

            val_num_int = rebar_new_values.get(target_id_int)
            if val_num_int is None:
                val_num_int = get_current_number(source_elem)
            if not val_num_int:
                continue
            val_num_str = str(val_num_int)

            val_dia_str      = get_inst_param_raw(source_elem, "Rebar_Diameter")
            val_dia_internal = None
            p_d = source_elem.LookupParameter("Rebar_Diameter")
            if p_d and p_d.StorageType == StorageType.Double:
                val_dia_internal = p_d.AsDouble()

            val_len_str      = get_inst_param_raw(source_elem, "Rebar_Length")
            val_len_internal = None
            p_l = source_elem.LookupParameter("Rebar_Length")
            if p_l and p_l.StorageType == StorageType.Double:
                val_len_internal = p_l.AsDouble()

            val_shape_str = get_type_param_raw(source_elem, "Rebar_Shape")

            tag_changed = False
            msgs = []

            ch_n, _, _ = update_smart(tag, "Rebar_Number", val_num_int, val_num_str)
            if ch_n:
                tag_changed = True

            ch_d, old_d, new_d = update_smart(tag, "Rebar_Diameter", val_dia_internal, val_dia_str)
            if ch_d:
                tag_changed = True
                msgs.append("Dia: {} -> {}".format(old_d, new_d))

            ch_l, old_l, new_l = update_smart(tag, "Rebar_Length", val_len_internal, val_len_str)
            if ch_l:
                tag_changed = True
                msgs.append("Len: {} -> {}".format(old_l, new_l))

            ch_s, old_s, new_s = update_smart(tag, "Rebar_Shape", val_shape_str, val_shape_str)
            if ch_s:
                tag_changed = True
                msgs.append("Shape: {} -> {}".format(old_s, new_s))

            if tag_changed:
                updated_count += 1
            if msgs:
                changes_report[view_obj].append((tag, ", ".join(msgs)))

        except Exception as ex:
            output.print_md("Warning tag `{}`: `{}`".format(raw_id, ex))

# ─────────────────────────────────────────────────────────────────────────────
# ОТЧЁТ
# ─────────────────────────────────────────────────────────────────────────────

scope_label = "Continuous" if scope == "Continuous" else "Per-sheet"
output.print_md("## Done!")
output.print_md(
    "**Sheets:** {n}  |  **Scope:** {sc}  |  **Mode:** {mo}  |  "
    "**Rebar:** {r}  |  **Tags updated:** {t}".format(
        n=len(sheet_list), sc=scope_label, mo=mode,
        r=count_rebar, t=updated_count))

# Per-sheet статистика
if scope == "PerSheet" and len(sheet_list) > 1:
    output.print_md("---")
    output.print_md("**Per-sheet breakdown:**")
    for sh in sheet_list:
        cnt = sum(1 for i in items_to_update if i["sheet_num"] == sh.SheetNumber)
        output.print_md("- Sheet **{}**: {} pcs.".format(sh.SheetNumber, cnt))

if conflict_log:
    output.print_md("---")
    output.print_md("### Conflict resolutions:")
    for line in conflict_log:
        output.print_md(line)

if missing_elements:
    output.print_md("---")
    output.print_md("### TAG HOSTS NOT FOUND:")
    for tag_el, view_obj in annotation_instances:
        src_p = tag_el.LookupParameter("PR_Rebar_ID")
        if not src_p:
            continue
        raw = src_p.AsString() or src_p.AsValueString()
        if not raw:
            continue
        tid = parse_element_id(raw)
        if tid and str(tid) in missing_elements:
            output.print_md("* {} on **{}** (host ID {} missing)".format(
                output.linkify(tag_el.Id, title="Tag {}".format(tag_el.Id)),
                output.linkify(view_obj.Id, title=view_obj.Name),
                tid))

if changes_report:
    output.print_md("---")
    output.print_md("## GEOMETRY CHANGED!")
    for view, updates in changes_report.items():
        output.print_md("### {}".format(view.Name))
        output.linkify(view.Id, title="Go to View")
        for tag, msg in updates:
            output.print_md("- {} : **{}**".format(
                output.linkify(tag.Id, title="Tag"), msg))
else:
    output.print_md("---")
    output.print_md("No geometry changes detected.")
