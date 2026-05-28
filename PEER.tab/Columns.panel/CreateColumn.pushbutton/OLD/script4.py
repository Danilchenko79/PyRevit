#"Рабочий скрипт, без арматуры. просто рисует сечения колонн с размерами"


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
from collections import defaultdict

doc = revit.doc

# 🔹 Запрашиваем имя Drafting View
view_name = forms.ask_for_string(
    default="Draft Columns",
    prompt="Введите имя для Drafting View"
)

if not view_name:
    forms.alert("Имя Drafting View не указано. Скрипт прерван.", exitscript=True)

# 🔹 Проверяем, существует ли такой Drafting View
drafting_view = None
collector = FilteredElementCollector(doc).OfClass(ViewDrafting)
for view in collector:
    if view.Name == view_name:
        drafting_view = view
        break

if not drafting_view:
    forms.alert("Вид '{}' не найден в проекте.".format(view_name), exitscript=True)

# 🔹 Получаем тип семейства Create Column
family_symbol = None
collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
for symbol in collector:
    if symbol.FamilyName == "Create Column":
        family_symbol = symbol
        break

if family_symbol is None:
    forms.alert("Семейство 'Create Column' не найдено в проекте. Скрипт прерван.", exitscript=True)

# 🔹 Собираем все марки колонн по типам
type_mark_dict = defaultdict(set)
collector_instances = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_StructuralColumns)\
    .WhereElementIsNotElementType()

for col in collector_instances:
    mark_param = col.LookupParameter("Mark")
    col_mark = mark_param.AsString() if mark_param else "N/A"
    col_type_id = col.GetTypeId()
    type_mark_dict[col_type_id].add(col_mark)

if not type_mark_dict:
    forms.alert("В проекте не найдено колонн с марками.", exitscript=True)

# 🔹 Функция для получения размеров колонны из типа
def get_column_dimensions_from_type(col_type):
    width = None
    height = None
    try:
        param_b = col_type.LookupParameter("B")
        param_h = col_type.LookupParameter("H")
        if param_b and param_h:
            width = param_b.AsDouble()
            height = param_h.AsDouble()
    except:
        pass
    return width, height

# 🔹 Рисуем все колонны
spacing_ft = 200 * 0.0328084  # 200 см интервал в футах
max_row_width_ft = 2300 * 0.0328084  # 2300 см в футах
current_row_width = 0
current_row_y = 0  # начальная строка

with Transaction(doc, "Place Columns, Text and Dimensions") as t:
    t.Start()
    if not family_symbol.IsActive:
        family_symbol.Activate()

    for type_id, marks in type_mark_dict.items():
        col_type = doc.GetElement(type_id)
        width, height = get_column_dimensions_from_type(col_type)
        if width and height:
            # Проверяем, не превышает ли текущая строка максимальную ширину
            if current_row_width + width > max_row_width_ft:
                current_row_width = 0
                current_row_y -= (height + spacing_ft)  # новая строка

            location_point = XYZ(current_row_width, current_row_y, 0)
            # Размещаем экземпляр Create Column
            instance = doc.Create.NewFamilyInstance(
                location_point,
                family_symbol,
                drafting_view
            )
            # Устанавливаем параметры B и H
            param_b = instance.LookupParameter("B")
            param_h = instance.LookupParameter("H")
            if param_b:
                param_b.Set(width)
            if param_h:
                param_h.Set(height)

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

            # Добавляем текст с марками колонн
            marks_string = ", ".join(sorted(marks))
            text_position = location_point + XYZ(0, -1, 0)
            text_note_type = FilteredElementCollector(doc)\
                .OfClass(TextNoteType)\
                .FirstElement()
            text_string = "Column {}".format(marks_string)
            TextNote.Create(doc, drafting_view.Id, text_position, text_string, text_note_type.Id)

            current_row_width += width + spacing_ft
    t.Commit()

forms.alert("Семейства, текст и размеры успешно созданы на виде '{}'.".format(view_name))
