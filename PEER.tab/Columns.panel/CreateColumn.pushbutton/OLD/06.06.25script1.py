# -*- coding: utf-8 -*-
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    Transaction,
    FilteredElementCollector,
    BuiltInCategory,
    FamilySymbol,
    ViewDrafting,
    XYZ,
    Line,
    ReferenceArray,
    Dimension,
    BuiltInParameter,
    TextNoteType,
    TextNote
)
# В этом коде уже армирование передается общим количество, но пока что без диаметра
doc = revit.doc

# 🔹 Настройки (единое место для имен)
FAMILY_NAME = "Create Column"
PARAM_B = "B"
PARAM_H = "H"
PARAM_MARK = "Mark"
PARAM_REBAR_QTY = "Rebar_Quantity"    # Новый параметр для количества арматуры
PARAM_LEVEL = "PR_Level"               # Имя параметра уровня

# 🔹 Запрос Drafting View
view_name = forms.ask_for_string(
    default="Column 150",
    prompt="Введите имя для Drafting View"
)
if not view_name:
    forms.alert("Имя Drafting View не указано. Скрипт прерван.", exitscript=True)

# 🔹 Проверяем существование Drafting View
drafting_view = None
for view in FilteredElementCollector(doc).OfClass(ViewDrafting):
    if view.Name == view_name:
        drafting_view = view
        break
if not drafting_view:
    forms.alert("Вид '{}' не найден.".format(view_name), exitscript=True)

# 🔹 Получаем Create Column
family_symbol = None
for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
    if symbol.FamilyName == FAMILY_NAME:
        family_symbol = symbol
        break
if family_symbol is None:
    forms.alert("Семейство '{}' не найдено.".format(FAMILY_NAME), exitscript=True)

# 🔹 Сбор уникальных уровней PR_Level
all_columns = list(FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_StructuralColumns)
    .WhereElementIsNotElementType())
levels = set()
for col in all_columns:
    level_param = col.LookupParameter(PARAM_LEVEL)
    if level_param and level_param.HasValue:
        levels.add(level_param.AsString())
levels = sorted([lvl for lvl in levels if lvl])

if not levels:
    forms.alert("Не найдено ни одного значения PR_Level у колонн.", exitscript=True)

# 🔹 Выбор уровня
selected_level = forms.SelectFromList.show(levels, title="Выберите уровень (PR_Level)")
if not selected_level:
    forms.alert("Уровень не выбран. Скрипт прерван.", exitscript=True)

# 🔹 Собираем и группируем данные колонн только для выбранного уровня
from collections import defaultdict

grouped_columns = defaultdict(lambda: {"marks": [], "width": 0, "height": 0, "rebar_qty": 0})

for col in all_columns:
    level_param = col.LookupParameter(PARAM_LEVEL)
    if not (level_param and level_param.HasValue and level_param.AsString() == selected_level):
        continue
    mark_param = col.LookupParameter(PARAM_MARK)
    col_mark = mark_param.AsString() if mark_param and mark_param.HasValue else "N/A"
    col_type = doc.GetElement(col.GetTypeId())

    width = col_type.LookupParameter(PARAM_B)
    height = col_type.LookupParameter(PARAM_H)
    width_value = width.AsDouble() if width else 0
    height_value = height.AsDouble() if height else 0

    rebar_qty_param = col.LookupParameter(PARAM_REBAR_QTY)
    rebar_qty_value = rebar_qty_param.AsInteger() if rebar_qty_param and rebar_qty_param.HasValue else 0

    key = (round(width_value, 6), round(height_value, 6), rebar_qty_value)
    grouped_columns[key]["marks"].append(col_mark)
    grouped_columns[key]["width"] = width_value
    grouped_columns[key]["height"] = height_value
    grouped_columns[key]["rebar_qty"] = rebar_qty_value

columns_data = []
for data in grouped_columns.values():
    columns_data.append({
        "marks": data["marks"],
        "width": data["width"],
        "height": data["height"],
        "rebar_qty": data["rebar_qty"]
    })

# Сортировка по размеру сечения и количеству арматуры (по убыванию)
columns_data.sort(key=lambda c: (-c["width"] * c["height"], -c["rebar_qty"]))

# 🔹 Размещаем экземпляры
spacing_ft = 200 * 0.0328084
max_row_width_ft = 2300 * 0.0328084
current_row_width = 0
current_row_y = 0

with Transaction(doc, "Place Columns") as t:
    t.Start()
    if not family_symbol.IsActive:
        family_symbol.Activate()
    for col_data in columns_data:
        width = col_data["width"]
        height = col_data["height"]
        if width > 0 and height > 0:
            if current_row_width + width > max_row_width_ft:
                current_row_width = 0
                current_row_y -= (height + spacing_ft)
            location_point = XYZ(current_row_width, current_row_y, 0)
            instance = doc.Create.NewFamilyInstance(location_point, family_symbol, drafting_view)

            # Устанавливаем B и H
            p_b = instance.LookupParameter(PARAM_B)
            if p_b: p_b.Set(width)
            p_h = instance.LookupParameter(PARAM_H)
            if p_h: p_h.Set(height)

            # Получаем Reference границ из семейства
            ref_left = instance.GetReferenceByName("Left")
            ref_right = instance.GetReferenceByName("Right")
            ref_top = instance.GetReferenceByName("Top")
            ref_bottom = instance.GetReferenceByName("Bottom")

            # Горизонтальный размер (ширина)
            if ref_left and ref_right:
                ref_array_h = ReferenceArray()
                ref_array_h.Append(ref_left)
                ref_array_h.Append(ref_right)
                offset_horizontal = XYZ(0, -0.5, 0)
                pt1 = location_point + offset_horizontal
                pt2 = XYZ(location_point.X + width, location_point.Y, 0) + offset_horizontal
                dim_line_h = Line.CreateBound(pt1, pt2)
                doc.Create.NewDimension(drafting_view, dim_line_h, ref_array_h)

            # Вертикальный размер (высота)
            if ref_top and ref_bottom:
                ref_array_v = ReferenceArray()
                ref_array_v.Append(ref_bottom)
                ref_array_v.Append(ref_top)
                offset_vertical = XYZ(-0.5, 0, 0)
                pt3 = location_point + offset_vertical
                pt4 = XYZ(location_point.X, location_point.Y + height, 0) + offset_vertical
                dim_line_v = Line.CreateBound(pt3, pt4)
                doc.Create.NewDimension(drafting_view, dim_line_v, ref_array_v)

            # Новый параметр армирования
            p_rebar_qty = instance.LookupParameter(PARAM_REBAR_QTY)
            if p_rebar_qty:
                try:
                    p_rebar_qty.Set(int(col_data["rebar_qty"]))
                except Exception as e:
                    print("Ошибка установки {}: {}".format(PARAM_REBAR_QTY, e))

            # Добавляем текст на иврите с размерами и марками колонн
            text_type = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()
            b_int = int(round(width * 30.48))   # футы -> см
            h_int = int(round(height * 30.48))  # футы -> см
            mark_text = ", ".join(sorted(col_data["marks"]))
            # Формат: עמוד 20/190, 5, 7, 9
            hebrew_text = u"עמוד {}/{}{}{}".format(b_int, h_int, (", " if mark_text else ""), mark_text)
            text_note = TextNote.Create(doc, drafting_view.Id, location_point + XYZ(0, -1, 0),
                                        hebrew_text, text_type.Id)
            current_row_width += width + spacing_ft
    t.Commit()

forms.alert("Скрипт успешно завершён. Семейства размещены и параметры заданы.")
