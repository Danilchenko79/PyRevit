# -*- coding: utf-8 -*-
__title__ = "Auto Beam Sections from Windows Approach"
__author__ = "ChatGPT, 2025"

from pyrevit import revit, DB, script
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, ViewSection, BoundingBoxXYZ, Transaction, XYZ, Transform, ViewFamilyType, ViewFamily

output = script.get_output()
log = []

doc = revit.doc
view = doc.ActiveView

def get_symbol_param(beam, builtin_param):
    """Получает параметр семейства у Symbol по BuiltInParameter"""
    symbol = beam.Symbol
    if symbol:
        param = symbol.get_Parameter(builtin_param)
        if param:
            try:
                return param.AsDouble()  # В футах
            except:
                return None
    return None


def process_beam(beam):
    loc = beam.Location
    if not isinstance(loc, DB.LocationCurve):
        return
    curve = loc.Curve
    mid = curve.Evaluate(0.5, True)
    tangent = curve.Direction.Normalize()

    # Получаем параметры семейства "H" и "Width" (в футах)
    height = get_symbol_param(beam, DB.BuiltInParameter.H)
    width = get_symbol_param(beam, DB.BuiltInParameter.Width)
    print(height)
    print(width)

    if height is None or width is None:
        raise Exception("Параметры 'H' и/или 'Width' не найдены")

    mm = 1200 / 304.8  # запас по 1200 мм в футах

    # Ориентация: секущий разрез
    vector = tangent
    X = DB.XYZ(-vector.Y, vector.X, 0).Normalize()
    Y = DB.XYZ.BasisZ
    Z = X.CrossProduct(Y).Normalize()

    trans = DB.Transform.Identity
    trans.Origin = mid
    trans.BasisX = X
    trans.BasisY = Y
    trans.BasisZ = Z

    box = DB.BoundingBoxXYZ()
    box.Min = DB.XYZ(-width/2 - mm, -mm, -height/2 - mm)
    box.Max = DB.XYZ(width/2 + mm, mm, height/2 + mm)
    box.Transform = trans

    type_id = get_section_type_id()
    if not type_id:
        raise Exception("Section type not found")
    sec = DB.ViewSection.CreateSection(doc, type_id, box)
    if sec is None:
        raise Exception("CreateSection returned None")

    mark = beam.LookupParameter("Mark").AsString() if beam.LookupParameter("Mark") else "noMark"
    sec.Name = "Section_{}_{}".format(mark, beam.Id.IntegerValue)


def main():
    beams = FilteredElementCollector(doc, view.Id)\
        .OfCategory(BuiltInCategory.OST_StructuralFraming)\
        .WhereElementIsNotElementType().ToElements()

    with Transaction(doc, "Beam Sections") as t:
        t.Start()
        for b in beams:
            try:

                process_beam(b)
                log.append("Создан разрез для балки {}".format(b.Id))
            except Exception as e:
                log.append("Ошибка {}: {}".format(b.Id, e))
        t.Commit()

    for line in log:
        output.print_md(line)

if __name__ == "__main__":
    main()
