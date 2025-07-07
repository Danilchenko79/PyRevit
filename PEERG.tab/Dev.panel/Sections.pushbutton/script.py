# -*- coding: utf-8 -*-
__title__ = "TypeSections"
__author__ = "Your Name"

from pyrevit import revit, script
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory

output = script.get_output()
view = revit.active_view

def get_center(element, view):
    bbox = element.get_BoundingBox(view)
    if bbox:
        center = bbox.Min + 0.5 * (bbox.Max - bbox.Min)
        return center
    return None

def world_to_view_coords(point, view):
    transform = view.CropBox.Transform
    origin = transform.Origin
    right = transform.BasisX
    up = transform.BasisY
    rel = point - origin
    x = rel.DotProduct(right)
    y = rel.DotProduct(up)
    return x, y

# --- Поиск первой балки на активном виде ---
beam = FilteredElementCollector(revit.doc, view.Id) \
    .OfCategory(BuiltInCategory.OST_StructuralFraming) \
    .WhereElementIsNotElementType() \
    .FirstElement()

# --- Поиск первой плиты на активном виде ---
floor = FilteredElementCollector(revit.doc, view.Id) \
    .OfCategory(BuiltInCategory.OST_Floors) \
    .WhereElementIsNotElementType() \
    .FirstElement()

if not beam or not floor:
    output.print_md(u"❗ На активном виде не найдены и балка, и плита.")
else:
    beam_bbox = beam.get_BoundingBox(view)
    floor_bbox = floor.get_BoundingBox(view)
    if not beam_bbox or not floor_bbox:
        output.print_md(u"❗ Не удалось получить bounding box балки или плиты.")
    else:
        bx_min, by_min = world_to_view_coords(beam_bbox.Min, view)
        bx_max, by_max = world_to_view_coords(beam_bbox.Max, view)
        fx_min, fy_min = world_to_view_coords(floor_bbox.Min, view)
        fx_max, fy_max = world_to_view_coords(floor_bbox.Max, view)

        # Новый блок: анализ пересечений и выступающих частей
        result = []
        # Проверка: есть ли пересечение по X и Y
        intersect_x = not (bx_max < fx_min or bx_min > fx_max)
        intersect_y = not (by_max < fy_min or by_min > fy_max)
        # Балка полностью внутри плиты по X и по Y
        beam_inside_plate_x = bx_min >= fx_min and bx_max <= fx_max
        beam_inside_plate_y = by_min >= fy_min and by_max <= fy_max
        # Выступающие части балки за плиту
        beam_outside_plate_left = bx_min < fx_min
        beam_outside_plate_right = bx_max > fx_max
        beam_outside_plate_top = by_max > fy_max
        beam_outside_plate_bottom = by_min < fy_min

        if intersect_x and intersect_y:
            if beam_inside_plate_x and beam_inside_plate_y:
                result.append(u"🟪 Балка полностью внутри перекрытия")
            else:
                edge_notes = []
                if beam_outside_plate_left:
                    edge_notes.append(u"слева")
                if beam_outside_plate_right:
                    edge_notes.append(u"справа")
                if beam_outside_plate_top:
                    edge_notes.append(u"выше")
                if beam_outside_plate_bottom:
                    edge_notes.append(u"ниже")
                if edge_notes:
                    result.append(u"⬛ Балка в перекрытии, выступает: " + ", ".join(edge_notes))
                else:
                    result.append(u"🟫 Балка частично вложена в перекрытие (пересечение)")
        else:
            result.append(u"⬜ Балка вне перекрытия (нет пересечения)")

        output.print_md(u"---\n".join(result))
        output.print_md(u"**Координаты балки:** X=({:.2f}, {:.2f}), Y=({:.2f}, {:.2f})".format(bx_min, bx_max, by_min, by_max))
        output.print_md(u"**Координаты плиты:** X=({:.2f}, {:.2f}), Y=({:.2f}, {:.2f})".format(fx_min, fx_max, fy_min, fy_max))
output.print_md(u"**Минимальные значения плиты:** Xmin={:.2f}, Ymin={:.2f}".format(fx_min, fy_min))
output.print_md(u"**Максимальные значения плиты:** Xmax={:.2f}, Ymax={:.2f}".format(fx_max, fy_max))
