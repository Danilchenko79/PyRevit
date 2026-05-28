# -*- coding: utf-8 -*-
# =============================================================================
# АРХИВ — старый скрипт (до переработки 2026-05-19)
# =============================================================================
# Что изменилось в новой версии (script.py в корне кнопки):
#
#   1. ЕДИНОЕ WPF-окно вместо последовательных диалогов
#      Было: CommandSwitchWindow (листы) → SelectFromList → CommandSwitchWindow (режим)
#      Стало: одно окно SetupWindow — выбор листов + режим + охват нумерации
#
#   2. Охват нумерации (Numbering scope)
#      Добавлен выбор: Continuous (сквозная по всем выбранным листам)
#                       Per-sheet (независимая на каждом листе, начинается с 1)
#
#   3. Исправлен баг StorageType в get_inst_param_raw / get_type_param_raw
#      Было: однострочный тернарный if — возвращал "" для String-параметров
#      Стало: явные if/elif на каждый StorageType
#
#   4. Добавлена функция parse_element_id
#      Безопасный разбор PR_Rebar_ID (числа, текст, пробелы) без NameError
#
#   5. Автоматическое разрешение конфликтов нумерации (режим Update)
#      Если две разные геометрии претендуют на один номер — победитель
#      определяется по сортировке ключа (как в Full), проигравшие уходят
#      в конец. Все случаи логируются в отчёт.
#
#   6. Дедупликация элементов (seen_elem_ids / seen_tag_ids)
#      Элемент, размещённый на нескольких видах, обрабатывается один раз.
#
#   7. val_dia_internal / val_len_internal по умолчанию None вместо 0.0
#      update_smart пропускает запись, если internal-значение None (Double).
#
#   8. Отчёт расширен: per-sheet статистика, conflict resolutions, linkify тегов.
#
#   9. Окно выбора листов стало resizable (CanResizeWithGrip).
#
# =============================================================================

__title__ = ("Rebar Renumber v.2")
__doc__ = "Renumbering + Smart Tag Update + QA Report"
__author__ = "BIM Specialist"

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *
import re
from collections import defaultdict
import System.Collections.Generic

doc = revit.doc
output = script.get_output()

# --- ⚙️ НАСТРОЙКИ ---
TAG_FAMILY_NAME = "PEER_Rebar TAG"
SKIP_NUMBERS = set([8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 32])


# --- 1️⃣ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def extract_number_from_string(value_string):
    """Извлекает число из строки (для сортировки)."""
    if not value_string: return 0
    match = re.search(r"[-+]?\d*\.\d+|\d+", str(value_string).replace(',', '.'))
    return float(match.group()) if match else 0


def get_inst_param_raw(e, n):
    """Получает сырое значение параметра экземпляра."""
    p = e.LookupParameter(n)
    if not p: return ""
    if p.StorageType == StorageType.Double: return p.AsValueString()
    return p.AsString() or str(p.AsInteger()) if p.StorageType == StorageType.Integer else ""


def get_type_param_raw(elem, param_name):
    """Получает сырое значение параметра типа."""
    symbol = elem.Symbol
    param = symbol.LookupParameter(param_name)
    if param:
        if param.StorageType == StorageType.Double: return param.AsValueString()
        return param.AsString() or str(param.AsInteger()) if param.StorageType == StorageType.Integer else ""
    return ""


def get_geometry_key(item):
    """Формирует уникальный ключ геометрии: (Форма, Диаметр, Длина, A)."""
    r_shape = get_type_param_raw(item, "Rebar_Shape")
    r_dia = extract_number_from_string(get_inst_param_raw(item, "Rebar_Diameter"))
    r_len = extract_number_from_string(get_inst_param_raw(item, "Rebar_Length"))
    r_a = extract_number_from_string(get_inst_param_raw(item, "Rebar_A"))
    return (r_shape, round(r_dia, 3), round(r_len, 3), round(r_a, 3))


def has_mark_value(item):
    """Проверяет, заполнена ли Марка (критерий 'Старой' арматуры)."""
    p = item.LookupParameter("Mark")
    if p and p.HasValue:
        val = p.AsString()
        if val and val.strip(): return True
    return False


def get_current_number(item):
    """Получает текущий номер Rebar_Number."""
    val = get_inst_param_raw(item, "Rebar_Number")
    return int(val) if val and val.isdigit() else 0


def get_sheet_from_view(view):
    """Находит лист, на котором размещен вид."""
    if isinstance(view, ViewSheet): return view
    view_id = view.Id
    collector = FilteredElementCollector(doc).OfClass(Viewport)
    for vp in collector:
        if vp.ViewId == view_id: return doc.GetElement(vp.SheetId)
    return None


def update_smart(tag, param_name, new_val_internal, new_val_str):
    """
    Сравнивает текущее значение Тэга с new_val_str (из арматуры).
    Если отличаются - пишет new_val_internal.
    Возвращает: (Changed:Bool, OldStr, NewStr)
    """
    p_tag = tag.LookupParameter(param_name)
    if not p_tag or p_tag.IsReadOnly:
        return False, None, None

    # 1. Читаем СТАРОЕ (из Тэга)
    old_val_str = ""
    if p_tag.StorageType == StorageType.Double:
        old_val_str = p_tag.AsValueString() or ""
    elif p_tag.StorageType == StorageType.String:
        old_val_str = p_tag.AsString() or ""
    elif p_tag.StorageType == StorageType.Integer:
        old_val_str = str(p_tag.AsInteger())

    if old_val_str is None: old_val_str = ""
    if new_val_str is None: new_val_str = ""

    # 2. Сравниваем СТРОКИ (То, что видит человек)
    if old_val_str != new_val_str:

        # 3. Пишем ВНУТРЕННЕЕ значение (Internal Units / Int)
        try:
            if p_tag.StorageType == StorageType.Double:
                if isinstance(new_val_internal, float):
                    p_tag.Set(new_val_internal)
            elif p_tag.StorageType == StorageType.Integer:
                p_tag.Set(int(float(new_val_internal)))
            elif p_tag.StorageType == StorageType.String:
                p_tag.Set(new_val_str)

            return True, old_val_str, new_val_str
        except:
            return False, old_val_str, new_val_str

    return False, old_val_str, new_val_str


# --- 2️⃣ ВЫБОР ЛИСТОВ (UI) ---

class SheetOption(forms.TemplateListItem):
    @property
    def name(self):
        return "{} - {}".format(self.item.SheetNumber, self.item.Name)


active_view = doc.ActiveView
detected_sheet = get_sheet_from_view(active_view)
sheet_list = []

switches = []
if detected_sheet:
    sheet_name_str = "{} - {}".format(detected_sheet.SheetNumber, detected_sheet.Name)
    switches.append("Current: [{}]".format(sheet_name_str))  # EN
switches.append("Select from list...")  # EN

res = forms.CommandSwitchWindow.show(switches, message="Select Sheets:")  # EN

if res and "Current" in res:
    sheet_list = [detected_sheet]
elif res == "Select from list...":
    all_sheets = FilteredElementCollector(doc).OfCategory(
        BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements()
    sheet_options = [SheetOption(s) for s in sorted(all_sheets, key=lambda x: x.SheetNumber)]
    selected = forms.SelectFromList.show(sheet_options, multiselect=True, title="Select Sheets")  # EN
    if selected: sheet_list = [x.item for x in selected]

if not sheet_list: script.exit()

# --- 3️⃣ ВЫБОР РЕЖИМА (UI) ---

# Ключи словаря переведены на английский для UI
ops = {
    'Full Renumbering': 'Full',
    'Only New (+ Unify Old)': 'Update'
}
selected_op = forms.CommandSwitchWindow.show(ops.keys(), message="Select Mode:")  # EN
mode = ops.get(selected_op)
if not mode: script.exit()

# --- 4️⃣ СБОР ДАННЫХ ---

all_items = []
views_to_scan = []
processed_view_ids = set()

for s in sheet_list:
    views_to_scan.append(s)
    processed_view_ids.add(s.Id)

with forms.ProgressBar(title="Analyzing...", cancellable=True) as pb:  # EN
    for i, sheet in enumerate(sheet_list):
        pb.update_progress(i + 1, len(sheet_list))
        if pb.cancelled: script.exit()

        sheet_number = sheet.SheetNumber
        view_ids = sheet.GetAllViewports()

        for vp_id in view_ids:
            vp = doc.GetElement(vp_id)
            if not vp: continue
            view = doc.GetElement(vp.ViewId)
            if not view: continue

            if view.Id not in processed_view_ids:
                views_to_scan.append(view)
                processed_view_ids.add(view.Id)

            collector = FilteredElementCollector(doc, view.Id) \
                .OfCategory(BuiltInCategory.OST_DetailComponents) \
                .WhereElementIsNotElementType()

            for item in collector:
                if isinstance(item, FamilyInstance):
                    if item.Symbol.Family.Name.startswith("PEER_Rebar_Shape"):
                        all_items.append({
                            "elem": item,
                            "key": get_geometry_key(item),
                            "current_num": get_current_number(item),
                            "is_old": has_mark_value(item),
                            "sheet_num": sheet_number
                        })

# --- 5️⃣ ЛОГИКА НУМЕРАЦИИ ---

items_to_update = []

if mode == 'Full':
    # Полный сброс
    grouped = defaultdict(list)
    for i in all_items: grouped[i["key"]].append(i)
    current_number = 1
    for key in sorted(grouped.keys()):
        while current_number in SKIP_NUMBERS: current_number += 1
        for item_dict in grouped[key]:
            item_dict["new_rebar_number"] = current_number
            items_to_update.append(item_dict)
        current_number += 1

elif mode == 'Update':
    # Обновление
    existing_db = {}
    max_num = 0
    new_items = []

    # 1. Группировка старых
    old_grouped = defaultdict(list)
    for i in all_items:
        if i["is_old"]:
            old_grouped[i["key"]].append(i)
        else:
            new_items.append(i)

    # 2. Унификация старых
    for key, group_items in old_grouped.items():
        used_numbers = set(x["current_num"] for x in group_items if x["current_num"] > 0)
        target_num = min(used_numbers) if used_numbers else 0
        if not target_num:
            new_items.extend(group_items)
            continue

        existing_db[key] = target_num
        if target_num > max_num: max_num = target_num
        for item in group_items:
            item["new_rebar_number"] = target_num
            items_to_update.append(item)

    # 3. Обработка новых
    new_items.sort(key=lambda x: x["key"])
    curr_new_num = max_num + 1

    for i in new_items:
        key = i["key"]
        if key in existing_db:
            i["new_rebar_number"] = existing_db[key]
        else:
            while curr_new_num in SKIP_NUMBERS: curr_new_num += 1
            i["new_rebar_number"] = curr_new_num
            existing_db[key] = curr_new_num
            curr_new_num += 1
        items_to_update.append(i)

# --- 6️⃣ ТРАНЗАКЦИЯ ---

changes_report = defaultdict(list)
updated_count = 0
missing_elements = []

with revit.Transaction("Renumber & Strict Sync"):
    # === A. АРМАТУРА ===
    rebar_new_values = {}
    count_rebar = 0
    if items_to_update:
        for item in items_to_update:
            elem = item["elem"]
            new_num = item["new_rebar_number"]
            sheet_n = item["sheet_num"]

            rebar_new_values[elem.Id.IntegerValue] = new_num

            p_num = elem.LookupParameter("Rebar_Number")
            if p_num:
                cur_val = get_inst_param_raw(elem, "Rebar_Number")
                if cur_val != str(new_num):
                    p_num.Set(int(new_num))

            p_mark = elem.LookupParameter("Mark")
            if p_mark: p_mark.Set(sheet_n)
            count_rebar += 1

    doc.Regenerate()  # Обновляем модель перед чтением параметров

    # === B. ТЭГИ ===
    cats = System.Collections.Generic.List[BuiltInCategory]()
    cats.Add(BuiltInCategory.OST_DetailComponents)
    cats.Add(BuiltInCategory.OST_GenericAnnotation)
    cats.Add(BuiltInCategory.OST_RebarTags)
    multi_filter = DB.ElementMulticategoryFilter(cats)

    annotation_instances = []
    for view in views_to_scan:
        found = FilteredElementCollector(doc, view.Id) \
            .WherePasses(multi_filter) \
            .WhereElementIsNotElementType() \
            .ToElements()

        for el in found:
            if isinstance(el, FamilyInstance):
                if TAG_FAMILY_NAME in el.Symbol.Family.Name:
                    annotation_instances.append((el, view))

    if annotation_instances:
        for tag, view_obj in annotation_instances:
            source_id_param = tag.LookupParameter("PR_Rebar_ID")
            if source_id_param:
                try:
                    raw_id = source_id_param.AsString() or source_id_param.AsValueString()
                    if not raw_id: continue
                    source_id_str = "".join(c for c in raw_id if c.isdigit())
                    if not source_id_str: continue

                    target_id_int = int(source_id_str)
                    source_elem = doc.GetElement(ElementId(target_id_int))
                    if not source_elem:
                        missing_elements.append(source_id_str)
                        continue

                    # --- ПОДГОТОВКА ИСТОЧНИКОВ ---

                    # 1. Номер
                    val_num_int = None
                    if target_id_int in rebar_new_values:
                        val_num_int = rebar_new_values[target_id_int]
                    else:
                        p_src = source_elem.LookupParameter("Rebar_Number")
                        if p_src: val_num_int = p_src.AsInteger()
                    val_num_str = str(val_num_int)

                    # 2. Диаметр
                    val_dia_internal = 0.0
                    val_dia_str = ""
                    p_d = source_elem.LookupParameter("Rebar_Diameter")
                    if p_d:
                        if p_d.StorageType == StorageType.Double: val_dia_internal = p_d.AsDouble()
                        val_dia_str = p_d.AsValueString()  # String from Rebar

                    # 3. Длина
                    val_len_internal = 0.0
                    val_len_str = ""
                    p_l = source_elem.LookupParameter("Rebar_Length")
                    if p_l:
                        if p_l.StorageType == StorageType.Double: val_len_internal = p_l.AsDouble()
                        val_len_str = p_l.AsValueString()  # String from Rebar

                    # 4. Форма
                    val_shape_str = get_type_param_raw(source_elem, "Rebar_Shape")

                    # --- СРАВНЕНИЕ И ЗАПИСЬ ---
                    tag_changed = False
                    msgs = []

                    # Номер
                    ch_n, _, _ = update_smart(tag, "Rebar_Number", val_num_int, val_num_str)
                    if ch_n: tag_changed = True

                    # Диаметр
                    ch_d, old_d, new_d = update_smart(tag, "Rebar_Diameter", val_dia_internal, val_dia_str)
                    if ch_d:
                        tag_changed = True
                        msgs.append("Dia: {} -> {}".format(old_d, new_d))  # EN

                    # Длина
                    ch_l, old_l, new_l = update_smart(tag, "Rebar_Length", val_len_internal, val_len_str)
                    if ch_l:
                        tag_changed = True
                        msgs.append("Len: {} -> {}".format(old_l, new_l))  # EN

                    # Форма
                    ch_s, old_s, new_s = update_smart(tag, "Rebar_Shape", val_shape_str, val_shape_str)
                    if ch_s:
                        tag_changed = True
                        msgs.append("Shape: {} -> {}".format(old_s, new_s))  # EN

                    if tag_changed:
                        updated_count += 1

                    if msgs:
                        changes_report[view_obj].append((tag, ", ".join(msgs)))

                except Exception as e:
                    print("Err tag {}: {}".format(raw_id, e))

# --- 7️⃣ ВЫВОД ОТЧЕТА (REPORT) ---

output.print_md("## ✅ Done!")  # EN
output.print_md("**Rebar:** {} pcs.".format(count_rebar))  # EN
output.print_md("**Tags:** {} pcs. (updated)".format(updated_count))  # EN

# --- ОБНОВЛЕННЫЙ БЛОК ОТЧЕТА ПО ПОТЕРЯННЫМ ОСНОВАМ ---
if missing_elements:
    output.print_md("---")
    output.print_md("### ❌ TAG HOSTS NOT FOUND (Check these tags):")

    # Собираем данные заново только для проблемных тэгов, чтобы дать ссылку на вид
    for tag_el, view_obj in annotation_instances:
        source_id_param = tag_el.LookupParameter("PR_Rebar_ID")
        if source_id_param:
            raw_id = source_id_param.AsString() or source_id_param.AsValueString()
            if raw_id:
                clean_id = "".join(c for c in raw_id if c.isdigit())
                if clean_id in missing_elements:
                    # Создаем строку: [Ссылка на тэг] -> Находится на виде: [Ссылка на вид]
                    tag_link = output.linkify(tag_el.Id, title="Tag ID: {}".format(tag_el.Id))
                    view_link = output.linkify(view_obj.Id, title=view_obj.Name)

                    output.print_md("* {} 📍 Location: **{}** (Host ID {} is missing)"
                                    .format(tag_link, view_link, clean_id))

if changes_report:
    output.print_md("---")
    output.print_md("## ⚠️ GEOMETRY CHANGED!")  # EN

    for view, updates in changes_report.items():
        output.print_md("### 👁️ View: {}".format(view.Name))  # EN
        output.linkify(view.Id, title="Go to View")  # EN

        for tag, msg in updates:
            tag_link = output.linkify(tag.Id, title="Show Tag")  # EN
            output.print_md("- {} : **{}**".format(tag_link, msg))
else:
    output.print_md("---")
    output.print_md("ℹ️ No geometry changes detected.")  # EN
