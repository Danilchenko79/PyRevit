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
    BuiltInParameter
)

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

# 🔹 Получаем все типы колонн (по типам арматуры в проекте)
used_type_ids = set()
collector_instances = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_StructuralColumns)\
    .WhereElementIsNotElementType()

for col in collector_instances:
    used_type_ids.add(col.GetTypeId())

column_types = [doc.GetElement(type_id) for type_id in used_type_ids]

if not column_types:
    forms.alert("В проекте не найдено используемых типов колонн.", exitscript=True)

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
spacing_ft = 200 * 0.0328084  # 200 см в футах
start_point_x = 0

with Transaction(doc, "Place Columns and Dimensions") as t:
    t.Start()
    if not family_symbol.IsActive:
        family_symbol.Activate()
    for col_type in column_types:
        width, height = get_column_dimensions_from_type(col_type)
        if width and height:
            location_point = XYZ(start_point_x, 0, 0)
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
                offset_horizontal = XYZ(0, -0.5, 0)  # смещение вниз
                pt1 = location_point + offset_horizontal
                pt2 = XYZ(location_point.X + width, location_point.Y, 0) + offset_horizontal
                dim_line_h = Line.CreateBound(pt1, pt2)
                doc.Create.NewDimension(drafting_view, dim_line_h, ref_array_h)

            # Вертикальный размер (высота)
            if ref_top and ref_bottom:
                ref_array_v = ReferenceArray()
                ref_array_v.Append(ref_bottom)
                ref_array_v.Append(ref_top)
                offset_vertical = XYZ(-0.5, 0, 0)  # смещение влево
                pt3 = location_point + offset_vertical
                pt4 = XYZ(location_point.X, location_point.Y + height, 0) + offset_vertical
                dim_line_v = Line.CreateBound(pt3, pt4)
                doc.Create.NewDimension(drafting_view, dim_line_v, ref_array_v)

            start_point_x += width + spacing_ft
    t.Commit()

forms.alert("Семейства и размеры успешно созданы на виде '{}'.".format(view_name))
