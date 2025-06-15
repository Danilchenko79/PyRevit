# -*- coding: utf-8 -*-
__title__   = "Beams Cross Sections (Active View)"
__version__ = 'Version = 0.3 (Beta)'
__doc__ = """Date    = 31.03.2024"""
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType

doc = revit.doc
uidoc = revit.uidoc
def get_section_box_perpendicular_to_beam(beam):
    lc = beam.Location
    if not isinstance(lc, DB.LocationCurve):
        forms.alert("Выбранный элемент не содержит LocationCurve (не балка)", exitscript=True)
    curve = lc.Curve

    curve_transform = curve.ComputeDerivatives(0.5, True)
    origin = curve_transform.Origin
    viewdir = curve_transform.BasisX.Normalize()
    up = DB.XYZ.BasisZ
    right = up.CrossProduct(viewdir)

    transform = DB.Transform.Identity
    transform.Origin = origin
    transform.BasisX = right
    transform.BasisY = up
    transform.BasisZ = viewdir

    beam_type = beam.Symbol
    width_param = beam_type.LookupParameter("b") or beam_type.LookupParameter("Width")
    height_param = beam_type.LookupParameter("h") or beam_type.LookupParameter("Height")
    if width_param and height_param:
        width = width_param.AsDouble()
        height = height_param.AsDouble()
    else:
        bb = beam.get_BoundingBox(None)
        width = bb.Max.Y - bb.Min.Y
        height = bb.Max.Z - bb.Min.Z

    section_box = DB.BoundingBoxXYZ()
    section_box.Transform = transform
    section_box.Min = DB.XYZ(-2 * width, -height * 0.2, 0)
    section_box.Max = DB.XYZ(2 * width, height * 1.2, 5)
    return section_box
# --- Выбор балки через стандартный диалог Revit ---


try:
    ref = uidoc.Selection.PickObject(ObjectType.Element, "Select a family to update")
    beam = doc.GetElement(ref.ElementId)
except Exception as e:
    forms.alert("Балка не выбрана. Скрипт завершён.", exitscript=True)


section_box = get_section_box_perpendicular_to_beam(beam)

# Находим тип разреза (Section Type) — используем первый попавшийся или нужный по имени
collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
section_type = None
for vft in collector:
    if vft.ViewFamily == DB.ViewFamily.Section:
        section_type = vft
        break

if not section_type:
    forms.alert("Не найден тип разреза (Section ViewFamilyType)", exitscript=True)

# Создаём разрез
t = DB.Transaction(doc, "Создать разрез поперёк балки")
t.Start()
section_view = DB.ViewSection.CreateSection(doc, section_type.Id, section_box)
t.Commit()

if section_view:
    forms.alert("Разрез успешно создан: {}".format(section_view.Name))
    # Можно сразу переключиться на созданный разрез
    uidoc.ActiveView = section_view
else:
    forms.alert("Не удалось создать разрез.", exitscript=True)

