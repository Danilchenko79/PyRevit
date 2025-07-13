# -*- coding: utf-8 -*-
__title__ = "SectionLocalCoords"
__author__ = "Dim Petrov + ChatGPT"

from pyrevit import revit, script
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, XYZ

output = script.get_output()
view = revit.active_view
FT_TO_MM = 304.8

# Вспомогательная функция векторного произведения для XYZ
def cross_product(a, b):
    return XYZ(
        a.Y * b.Z - a.Z * b.Y,
        a.Z * b.X - a.X * b.Z,
        a.X * b.Y - a.Y * b.X
    )

# Универсальная функция перевода глобальных координат в локальные координаты вида
# origin — базовая точка (CropBox.Transform.Origin)
# dir_axis — направление вида (CropBox.Transform.BasisX)
# up_axis — вертикаль вида (CropBox.Transform.BasisY)
def to_local(point, origin, dir_axis, up_axis):
    e1 = dir_axis.Normalize()     # X локальной СК
    e2 = up_axis.Normalize()      # Y локальной СК
    e3 = cross_product(e1, e2).Normalize() # Z локальной СК
    rel = point - origin
    return rel.DotProduct(e1), rel.DotProduct(e2), rel.DotProduct(e3)

# Получаем балку и плиту на виде
beams = list(FilteredElementCollector(revit.doc, view.Id).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType())
floors = list(FilteredElementCollector(revit.doc, view.Id).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType())

if len(beams) != 1 or len(floors) != 1:
    output.print_md(u"❗ Должна быть одна балка и одна плита. Сейчас: Балок = {}, Плит = {}".format(len(beams), len(floors)))
else:
    beam = beams[0]
    floor = floors[0]

    beam_bbox = beam.get_BoundingBox(view)
    floor_bbox = floor.get_BoundingBox(view)
    if not beam_bbox or not floor_bbox:
        output.print_md(u"❗ Не удалось получить границы элементов.")
    else:
        transform = view.CropBox.Transform
        origin = transform.Origin
        right = transform.BasisX
        up = transform.BasisY

        # Пример перевода ключевых точек балки и плиты в локальные координаты
        points = {
            "Beam Min": beam_bbox.Min,
            "Beam Max": beam_bbox.Max,
            "Floor Min": floor_bbox.Min,
            "Floor Max": floor_bbox.Max
        }

        output.print_md(u"### 🔄 Перевод точек в локальную СК разреза:")
        for label, pt in points.items():
            x, y, z = to_local(pt, origin, right, up)
            output.print_md(u"{}: x={:.1f} мм, y={:.1f} мм, z={:.1f} мм".format(
                label,
                x * FT_TO_MM,
                y * FT_TO_MM,
                z * FT_TO_MM
            ))

        # Теперь ты можешь сравнивать x, y координаты этих точек в локальной системе
        # и определять тип сечения по более универсальной логике, независимо от угла разреза.
