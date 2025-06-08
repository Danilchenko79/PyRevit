# Рабочий скрипт, берет армирвоание по двум параметрам количество по короткой грани и по длинной. Делает армирование строит сечения и размеры по семейству
# В этом проекте не реализованы еще шпильки, выбор колонн по уровню автоматическое расположение и обозначения армирования, обновление разрезов а не создание новых
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

doc = revit.doc

# 🔹 Настройки (единое место для имен)
FAMILY_NAME = "Create Column"
PARAM_B = "B"
PARAM_H = "H"
PARAM_MARK = "Mark"
PARAM_COLUMN_QTY_LONG = "Column_Quantity_Long"
PARAM_COLUMN_QTY_SHORT = "Column_Quantity_Short"
PARAM_VIS_REBAR = "Vis_Rebar"

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

# 🔹 Собираем данные колонн
columns_data = []
for col in FilteredElementCollector(doc) \
        .OfCategory(BuiltInCategory.OST_StructuralColumns) \
        .WhereElementIsNotElementType():
    mark_param = col.LookupParameter(PARAM_MARK)
    col_mark = mark_param.AsString() if mark_param and mark_param.HasValue else "N/A"
    col_type = doc.GetElement(col.GetTypeId())

    width = col_type.LookupParameter(PARAM_B)
    height = col_type.LookupParameter(PARAM_H)
    width_value = width.AsDouble() if width else 0
    height_value = height.AsDouble() if height else 0

    qty_long_param = col.LookupParameter(PARAM_COLUMN_QTY_LONG)
    qty_long_value = qty_long_param.AsInteger() if qty_long_param else 0

    qty_short_param = col.LookupParameter(PARAM_COLUMN_QTY_SHORT)
    qty_short_value = qty_short_param.AsInteger() if qty_short_param else 0

    columns_data.append({
        "mark": col_mark,
        "width": width_value,
        "height": height_value,
        "qty_long": qty_long_value,
        "qty_short": qty_short_value
    })


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

            # Устанавливаем армирование (экземплярные параметры!)
            p_qty_long = instance.LookupParameter(PARAM_COLUMN_QTY_LONG)
            if p_qty_long:
                try:
                    p_qty_long.Set(int(col_data["qty_long"]))
                except Exception as e:
                    print("Ошибка установки {}: {}".format(PARAM_COLUMN_QTY_LONG, e))
            p_qty_short = instance.LookupParameter(PARAM_COLUMN_QTY_SHORT)
            if p_qty_short:
                try:
                    p_qty_short.Set(int(col_data["qty_short"]))
                except Exception as e:
                    print("Ошибка установки {}: {}".format(PARAM_COLUMN_QTY_SHORT, e))



            # Добавляем текст с маркой колонны
            text_type = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()
            text_note = TextNote.Create(doc, drafting_view.Id, location_point + XYZ(0, -1, 0),
                                        "Column {}".format(col_data["mark"]), text_type.Id)
            current_row_width += width + spacing_ft
    t.Commit()

forms.alert("Скрипт успешно завершён. Семейства размещены и параметры заданы.")
