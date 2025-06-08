# -*- coding: utf-8 -*-
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    Transaction,
    FilteredElementCollector,
    BuiltInCategory,
    ViewDrafting,
    ViewFamilyType,
    ViewFamily,
    XYZ,
    Line,
    SketchPlane,
    Plane,
    FilledRegion,
    FilledRegionType,
    ModelCurve,
    ReferenceArray,
    Dimension,
    BuiltInParameter
)
from System.Collections.Generic import List
from Autodesk.Revit.DB import CurveLoop

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

# 🔹 Получаем FilledRegionType по имени
filled_region_type = None
collector_frt = FilteredElementCollector(doc).OfClass(FilledRegionType)
for fr_type in collector_frt:
    fr_type_name = fr_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    if "Solid Beton" in fr_type_name:
        filled_region_type = fr_type
        break

if filled_region_type is None:
    forms.alert("Тип штриховки 'Solid Beton' не найден в проекте. Скрипт прерван.", exitscript=True)

# 🔹 Получаем все типы колонн, которые используются в проекте
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

# 🔹 Функция для создания ModelLine
def create_model_line(doc, view, pt1, pt2):
    plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0,0,0))
    sketch_plane = SketchPlane.Create(doc, plane)
    line = Line.CreateBound(pt1, pt2)
    model_line = doc.Create.NewModelCurve(line, sketch_plane)
    return model_line

# 🔹 Функция для создания FilledRegion
def create_filled_region(doc, view, width, height, location_point, filled_region_type):
    half_width = width / 2
    half_height = height / 2

    points = [
        location_point + XYZ(-half_width, -half_height, 0),
        location_point + XYZ(half_width, -half_height, 0),
        location_point + XYZ(half_width, half_height, 0),
        location_point + XYZ(-half_width, half_height, 0)
    ]

    curves = []
    for i in range(4):
        line = Line.CreateBound(points[i], points[(i+1)%4])
        curves.append(line)

    loop = CurveLoop.Create(curves)
    loops = List[CurveLoop]()
    loops.Add(loop)

    filled_region = FilledRegion.Create(doc, filled_region_type.Id, view.Id, loops)
    return filled_region, points

# 🔹 Функция для добавления размеров
def add_dimension_between_points(doc, view, pt1, pt2, offset, direction='horizontal'):
    try:
        plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0,0,0))
        sketch_plane = SketchPlane.Create(doc, plane)
        line = Line.CreateBound(pt1, pt2)
        model_line = doc.Create.NewModelCurve(line, sketch_plane)

        ref_array = ReferenceArray()
        ref_array.Append(model_line.GeometryCurve.Reference)
        ref_array.Append(model_line.GeometryCurve.Reference)

        # Смещаем линию размера
        if direction == 'horizontal':
            dim_line = Line.CreateBound(pt1 + offset, pt2 + offset)
        else:
            dim_line = Line.CreateBound(pt1 + offset, pt2 + offset)

        dim = doc.Create.NewDimension(view, dim_line, ref_array)
        return dim
    except Exception as e:
        print("Ошибка при создании размера:", e)
        return None

# 🔹 Рисуем все колонны
spacing_ft = 200 * 0.0328084  # 200 см в футах
start_point_x = 0

with Transaction(doc, "Draw Columns and Dimensions") as t:
    t.Start()
    for col_type in column_types:
        width, height = get_column_dimensions_from_type(col_type)
        if width and height:
            location_point = XYZ(start_point_x, 0, 0)
            filled_region, points = create_filled_region(doc, drafting_view, width, height, location_point, filled_region_type)

            # Размеры: ширина (горизонтальный внизу)
            pt1 = points[0]  # нижний левый
            pt2 = points[1]  # нижний правый
            offset_horizontal = XYZ(0, -0.5, 0)
            add_dimension_between_points(doc, drafting_view, pt1, pt2, offset_horizontal, direction='horizontal')

            # Размеры: высота (вертикальный слева)
            pt3 = points[0]  # нижний левый
            pt4 = points[3]  # верхний левый
            offset_vertical = XYZ(-0.5, 0, 0)
            add_dimension_between_points(doc, drafting_view, pt3, pt4, offset_vertical, direction='vertical')

            start_point_x += width + spacing_ft
    t.Commit()

forms.alert("Штриховки и размеры успешно созданы на виде '{}'.".format(view_name))
