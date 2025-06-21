# -*- coding: utf-8 -*-
__title__ = "Auto Beam Sections from Windows Approach"
__author__ = "ChatGPT, 2025"

from pyrevit import revit, DB, script
from Autodesk.Revit.DB import *

output = script.get_output()
doc = revit.doc
view = doc.ActiveView

# --- Получаем номер разреза из имени активного вида ---
def get_section_prefix(view):
    """
    Извлекает первые три символа из имени вида, например '170' из '170RE'
    """
    return view.Name[:3]

# --- Счётчик разрезов с данным префиксом ---
section_counters = {}

# --- Получаем балки на активном виде ---
beams = FilteredElementCollector(doc, view.Id) \
        .OfCategory(BuiltInCategory.OST_StructuralFraming) \
        .WhereElementIsNotElementType().ToElements()

from pyrevit import forms


created_sections_list = []





dict_beams = {}
for b in beams:
    family_name = b.Symbol.Family.Name
    type_name = Element.Name.GetValue(b.Symbol)
    key_name = '{}_{}'.format(family_name, type_name)
    dict_beams[key_name] = b

for k, v in dict_beams.items():
    output.print_md("**{}** : {}".format(k, v.Id))

# --- Создание разрезов ---
t = Transaction(doc, 'Generate Section')
t.Start()
for beam_name, beam in dict_beams.items():

    # --- Геометрия балки ---
    curve = beam.Location.Curve
    pt_start = curve.GetEndPoint(0)
    pt_end = curve.GetEndPoint(1)
    vector = pt_end - pt_start
    mid = curve.Evaluate(0.5, True)
    tangent = curve.Direction.Normalize()

    # --- Параметры размера балки ---
    param_height = beam.Symbol.LookupParameter("H") or beam.Symbol.LookupParameter("Height")
    param_width = beam.Symbol.LookupParameter("B") or beam.Symbol.LookupParameter("Width")
    height = param_height.AsDouble() if param_height else None
    width = param_width.AsDouble() if param_width else None
    offset = UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Centimeters)
    b_depth = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters)

    # --- Ориентация разреза ---
    vector = tangent
    X = XYZ(-vector.Y, vector.X, 0).Normalize()
    Y = XYZ.BasisZ
    Z = X.CrossProduct(Y).Normalize()
    trans = Transform.Identity
    trans.Origin = mid
    trans.BasisX = X
    trans.BasisY = Y
    trans.BasisZ = Z

    # --- Bounding Box для секции ---
    box = DB.BoundingBoxXYZ()
    box.Min = DB.XYZ(-width / 2 - offset, -offset, -b_depth)
    box.Max = DB.XYZ(width / 2 + offset, offset + height, b_depth)
    box.Transform = trans

    # --- Новый формат имени разреза ---
    prefix = get_section_prefix(view)  # Например, '170'
    # Счётчик для текущего префикса
    if prefix not in section_counters:
        section_counters[prefix] = 1
    else:
        section_counters[prefix] += 1
    new_name = '{}_{}'.format(prefix, section_counters[prefix])

    section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
    sec = DB.ViewSection.CreateSection(doc, section_type_id, box)
    for i in range(10):
        try:
            sec.Name = new_name
            print('Created Section {}'.format(new_name))
            break
        except:
            new_name += '*'
    created_sections_list.append(sec)
t.Commit()

# Список всех листов
sheets = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements()

# Диалог выбора
sheet = forms.SelectFromList.show(
    sheets,
    name_attr='SheetNumber',
    value_attr='SheetNumber',
    multiselect=False,
    title='Выберите лист для разрезов'
)

if not sheet:
    forms.alert('Лист не выбран! Скрипт остановлен.')
    script.exit()



x0, y0 = 100, 150  # стартовая позиция
dx, dy = 200, 150  # шаг по X и Y
views_per_row = 3  # сколько разрезов в строке

t3 = Transaction(doc, 'Place Sections on Sheet')
t3.Start()
for idx, sec in enumerate(created_sections_list):
    row = idx // views_per_row
    col = idx % views_per_row
    point_mm = XYZ(x0 + dx * col, y0 + dy * row, 0)  # в миллиметрах

    # Перевести из миллиметров в футы (Revit использует футы)
    def mm_to_ft(mm):
        return mm / 304.8

    point_ft = XYZ(mm_to_ft(point_mm.X), mm_to_ft(point_mm.Y), 0)

    # Размещаем вид на листе
    try:
        viewport = Viewport.Create(doc, sheet.Id, sec.Id, point_ft)
        print('Section {} placed on sheet.'.format(sec.Name))
    except Exception as e:
        print('Could not place section {}: {}'.format(sec.Name, e))
t3.Commit()