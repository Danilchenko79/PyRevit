# -*- coding: utf-8 -*-
__title__ = "Auto Beam Sections from Windows Approach"
__author__ = "ChatGPT, 2025"

from pyrevit import revit, DB, script
from Autodesk.Revit.DB import *

output = script.get_output()
log = []

doc = revit.doc
view = doc.ActiveView

# Получаем все балки на активном виде
beams = FilteredElementCollector(doc, view.Id) \
        .OfCategory(BuiltInCategory.OST_StructuralFraming) \
        .WhereElementIsNotElementType().ToElements()

dict_beams = {}  # Создаём пустой словарь

for b in beams:
    family_name = b.Symbol.Family.Name
    type_name = Element.Name.GetValue(b.Symbol) # Исправлено!
    key_name = '{}_{}'.format(family_name, type_name)
    dict_beams[key_name] = b  # Добавляем в словарь

# Выводим результат (лучше для pyRevit через output)
for k, v in dict_beams.items():
    output.print_md("**{}** : {}".format(k, v.Id))

t=Transaction(doc,'Generate Section')
t.Start()
for beam_name, beam in dict_beams.items():

    curve = beam.Location.Curve
    pt_start = curve.GetEndPoint(0)
    pt_end = curve.GetEndPoint(1)
    vector = pt_end - pt_start
    mid = curve.Evaluate(0.5, True)
    tangent = curve.Direction.Normalize()
    # height = beam.Symbol.get_Parameter(BuiltInParameter.GeneralHeight).AsDouble()
    # width = beam.Symbol.get_Parameter(BuiltInParameter.GeneralWidth).AsDouble()
    # print(height)
    param_height = beam.Symbol.LookupParameter("H") or beam.Symbol.LookupParameter("Height")
    param_width = beam.Symbol.LookupParameter("B") or beam.Symbol.LookupParameter("Width")
    height = param_height.AsDouble() if param_height else None
    width = param_width.AsDouble() if param_width else None
    offset = UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Centimeters)
    b_depth = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters)

    #     # Ориентация: секущий разрез
    vector = tangent
    X = XYZ(-vector.Y, vector.X, 0).Normalize()
    Y = XYZ.BasisZ
    Z = X.CrossProduct(Y).Normalize()
    trans = Transform.Identity
    trans.Origin = mid
    trans.BasisX = X
    trans.BasisY = Y
    trans.BasisZ = Z
    #
    box = DB.BoundingBoxXYZ()
    box.Min = DB.XYZ(-width / 2 - offset, -offset, -b_depth)
    box.Max = DB.XYZ(width / 2 + offset, offset + height, b_depth)
    box.Transform = trans

    section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
    sec = DB.ViewSection.CreateSection(doc, section_type_id, box)
    new_name = 'py_{} (Elevation)'.format(beam_name)

    sec.Name = new_name

    for i in range(10):
        try:
            sec.Name = new_name
            print('Creadted Section {}'.format(new_name))
            break
        except:
            new_name += '*'

t.Commit()


#     if sec is None:
#         raise Exception("CreateSection returned None")
#
#     mark = beam.LookupParameter("Mark").AsString() if beam.LookupParameter("Mark") else "noMark"
#     sec.Name = "Section_{}_{}".format(mark, beam.Id.IntegerValue)
#
#
# def main():
#     beams = FilteredElementCollector(doc, view.Id)\
#         .OfCategory(BuiltInCategory.OST_StructuralFraming)\
#         .WhereElementIsNotElementType().ToElements()
#
#     with Transaction(doc, "Beam Sections") as t:
#         t.Start()
#         for b in beams:
#             try:
#
#                 process_beam(b)
#                 log.append("Создан разрез для балки {}".format(b.Id))
#             except Exception as e:
#                 log.append("Ошибка {}: {}".format(b.Id, e))
#         t.Commit()
#
#     for line in log:
#         output.print_md(line)
#
# if __name__ == "__main__":
#     main()
