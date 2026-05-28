# coding: utf-8
__title__ = "Numbering"
__author__ = "Dmitry D"


# coding: utf-8
from pyrevit import forms, output
from pyrevit import DB

doc = __revit__.ActiveUIDocument.Document
out = output.get_output()

# ==== НАСТРОЙКИ ====
group_params = ["Rebar_Shape", "Rebar_Diameter", "Rebar_Length", "Rebar_B"]
mark_param = "Mark"
exclude_param = "Pr_Rebar Tag"
exclude_on_values = ["1", "Yes", "Да", "True", "Вкл", "On", "ON"]
# ====================

active_view = doc.ActiveView

# Определяем номер листа для поиска элементов
sheet_number = None
sheet = None

if isinstance(active_view, DB.ViewSheet):
    sheet = active_view
    sheet_number = sheet.SheetNumber
    out.print_md("Вид — лист. SheetNumber: **{}**".format(sheet_number))
else:
    # Находим лист, на котором находится этот вид
    view_id = active_view.Id
    collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
    for s in collector:
        views_on_sheet = s.GetAllPlacedViews()
        if view_id in views_on_sheet:
            sheet = s
            sheet_number = sheet.SheetNumber
            out.print_md("Вид находится на листе с SheetNumber: **{}**".format(sheet_number))
            break

if not sheet_number:
    forms.alert("Не удалось определить номер листа для текущего вида!", exitscript=True)

# Получаем все Detail Items с Mark = sheet_number и исключаем с Pr_Rebar Tag = ВКЛ
detail_items = []
excluded_count = 0
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_DetailComponents).WhereElementIsNotElementType():
    p_mark = el.LookupParameter(mark_param)
    if p_mark:
        value = p_mark.AsString() or p_mark.AsValueString() or ""
        if value == sheet_number:
            p_exclude = el.LookupParameter(exclude_param)
            exclude = False
            if p_exclude:
                val_exclude = p_exclude.AsString() or p_exclude.AsValueString() or ""
                if val_exclude.strip() in exclude_on_values:
                    exclude = True
            if exclude:
                excluded_count += 1
                continue
            detail_items.append(el)

out.print_md("### Найдено Detail Items с Mark='{}': {}\nИз них исключено по Pr_Rebar Tag: {}\n".format(
    sheet_number, len(detail_items), excluded_count))

# --- Группируем по параметрам ---
groups = {}
for el in detail_items:
    key = []
    for pname in group_params:
        p = el.LookupParameter(pname)
        val = ""
        if p:
            val = p.AsString() or p.AsValueString() or ""
        key.append(val)
    key = tuple(key)
    if key not in groups:
        groups[key] = []
    groups[key].append(el)

out.print_md("### Найдено групп: **{}**\n".format(len(groups)))

# --- Сортируем группы по значениям параметров ---
def sort_key_for_group(group_key):
    result = []
    for idx, val in enumerate(group_key):
        if group_params[idx] in ["Rebar_Shape", "Rebar_Diameter", "Rebar_Length", "Rebar_B"]:
            try:
                result.append(float(val.replace(",", ".").replace(" ", "")))
            except Exception:
                result.append(val)
        else:
            result.append(val)
    return result

sorted_group_keys = sorted(groups.keys(), key=sort_key_for_group)

out.print_md("### Группы (отсортированы):")
for idx, gk in enumerate(sorted_group_keys, 1):
    gitems = groups[gk]
    out.print_md("**Группа {}:** параметры = {}\n Элементов в группе: {}\n".format(idx, gk, len(gitems)))
