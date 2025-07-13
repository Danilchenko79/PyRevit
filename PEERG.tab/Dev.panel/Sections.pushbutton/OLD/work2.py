# Определяет тип сечения из 9 вариантов. То есть когда есть 1 плита и одна балка


# -*- coding: utf-8 -*-
__title__ = "TypeSections"
__author__ = "Your Name"

from pyrevit import revit, script
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory

output = script.get_output()
view = revit.active_view

# Перевод футов в мм
FT_TO_MM = 304.8

def world_to_view_coords_mm(point, view):
    transform = view.CropBox.Transform
    origin = transform.Origin
    right = transform.BasisX
    up = transform.BasisY
    rel = point - origin
    x = rel.DotProduct(right) * FT_TO_MM
    y = rel.DotProduct(up) * FT_TO_MM
    return x, y

def to_mm(xyz):
    return xyz.X * FT_TO_MM, xyz.Y * FT_TO_MM, xyz.Z * FT_TO_MM

# Поиск балок и плит на виде
beams = list(FilteredElementCollector(revit.doc, view.Id)
    .OfCategory(BuiltInCategory.OST_StructuralFraming)
    .WhereElementIsNotElementType())
floors = list(FilteredElementCollector(revit.doc, view.Id)
    .OfCategory(BuiltInCategory.OST_Floors)
    .WhereElementIsNotElementType())

if len(beams) != 1 or len(floors) != 1:
    output.print_md(u"❗ На активном виде должно быть ровно одна балка и одно перекрытие! Сейчас: Балок = {}, Плит = {}".format(len(beams), len(floors)))
else:
    beam = beams[0]
    floor = floors[0]
    beam_bbox = beam.get_BoundingBox(view)
    floor_bbox = floor.get_BoundingBox(view)
    if not beam_bbox or not floor_bbox:
        output.print_md(u"❗ Не удалось получить bounding box балки или плиты.")
    else:
        # Преобразуем все нужные точки в координаты вида (мм)
        bx_min, by_min = world_to_view_coords_mm(beam_bbox.Min, view)
        bx_max, by_max = world_to_view_coords_mm(beam_bbox.Max, view)
        fx_min, fy_min = world_to_view_coords_mm(floor_bbox.Min, view)
        fx_max, fy_max = world_to_view_coords_mm(floor_bbox.Max, view)

        # Размеры балки
        beam_width = abs(bx_max - bx_min)
        beam_height = abs(by_max - by_min)
        # Размеры плиты
        floor_thickness = abs(fy_max - fy_min)
        floor_width = abs(fx_max - fx_min)

        # --- Глобальные координаты балки и плиты (для будущих нужд, сейчас закомментировано) ---
        # beam_global_min = to_mm(beam_bbox.Min)
        # beam_global_max = to_mm(beam_bbox.Max)
        # output.print_md(u"Глобальные координаты (Revit XYZ):")
        # output.print_md(u"Min: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*beam_global_min))
        # output.print_md(u"Max: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*beam_global_max))
        output.print_md(u"**Балка**:")
        output.print_md(u"Xmin = {:.0f} мм, Xmax = {:.0f} мм".format(bx_min, bx_max))
        output.print_md(u"Ymin = {:.0f} мм, Ymax = {:.0f} мм".format(by_min, by_max))
        output.print_md(u"Ширина = {:.0f} мм, Высота = {:.0f} мм".format(beam_width, beam_height))

        output.print_md(u"**Плита**:")
        # floor_global_min = to_mm(floor_bbox.Min)
        # floor_global_max = to_mm(floor_bbox.Max)
        # output.print_md(u"Глобальные координаты (Revit XYZ):")
        # output.print_md(u"Min: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*floor_global_min))
        # output.print_md(u"Max: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*floor_global_max))
        output.print_md(u"Xmin = {:.0f} мм, Xmax = {:.0f} мм".format(fx_min, fx_max))
        output.print_md(u"Ymin = {:.0f} мм, Ymax = {:.0f} мм".format(fy_min, fy_max))
        output.print_md(u"Толщина = {:.0f} мм, Ширина = {:.0f} мм".format(floor_thickness, floor_width))

        # --- Логика определения типа сечения с учетом допуска 3 см ---
        tolerance = 70  # мм
        def eq(a, b, tol=tolerance):
            return abs(a - b) < tol

        section_type = None
        if eq(fx_min, bx_min):
            if eq(fy_min, by_min):
                section_type = "Сечение А"
            elif eq(fy_max, by_max):
                section_type = "Сечение B"
            elif by_max > fy_max and by_min < fy_min:
                section_type = "Сечение H"
        elif eq(fx_max, bx_max):
            if eq(fy_min, by_min):
                section_type = "Сечение D"
            elif eq(fy_max, by_max):
                section_type = "Сечение C"
            elif by_max > fy_max and by_min < fy_min:
                section_type = "Сечение G"
        elif bx_max < fx_max and bx_min > fx_min:
            if eq(by_min, fy_min):
                section_type = "Сечение E"
            elif eq(by_max, fy_max):
                section_type = "Сечение F"
            elif by_max > fy_max and by_min < fy_min:
                section_type = "Сечение I"
        if section_type:
            output.print_md(u"### 🟩 Тип сечения: **{}**".format(section_type))
        else:
            output.print_md(u"❓ Не удалось определить тип сечения по текущим координатам.")
