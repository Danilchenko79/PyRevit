# -*- coding: utf-8 -*-
__title__ = "Rebar Tag Select"
__doc__ = """Version = 5.1
Date = 02.06.2025
Author: Erik Frits
"""

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType

doc = revit.doc
uidoc = revit.uidoc

# 1️⃣ Выбираем семейство на активном виде
try:
    ref = uidoc.Selection.PickObject(ObjectType.Element, "Select a family to update")
    selected_elem = doc.GetElement(ref.ElementId)
except Exception as e:
    if "cancelled" in str(e).lower():
        forms.alert("Selection operation cancelled.")
        script.exit()
    else:
        raise

# Проверяем, что выбрано именно Detail Item
if not isinstance(selected_elem, FamilyInstance):
    forms.alert("The selected element is not a Detail Item.")
    script.exit()

# 2️⃣ Запрашиваем у пользователя номер арматуры
rebar_number_input = forms.ask_for_string(
    default='',
    prompt="Enter the rebar number to search for:",
    title="Rebar Search"
)

if not rebar_number_input:
    forms.alert("Rebar number not entered. Script stopped.")
    script.exit()

try:
    user_input_number = int(rebar_number_input.strip())
except:
    forms.alert("Please enter a valid number for the rebar number.")
    script.exit()

# 3️⃣ Ищем лист, на который размещён активный вид
viewport_collector = FilteredElementCollector(doc).OfClass(Viewport)
sheet_id = None

for vp in viewport_collector:
    if vp.ViewId == revit.active_view.Id:
        sheet_id = vp.SheetId
        break

if not sheet_id:
    forms.alert("The active view is not placed on any sheet.")
    script.exit()

sheet = doc.GetElement(sheet_id)

# 4️⃣ Получаем все виды на этом листе
placed_views = []
viewport_ids = sheet.GetAllViewports()

for vp_id in viewport_ids:
    vp = doc.GetElement(vp_id)
    if hasattr(vp, 'ViewId'):
        view = doc.GetElement(vp.ViewId)
        placed_views.append(view)

# 5️⃣ Ищем Detail Item с этим номером и именем семейства PEER_Rebar_Shape*
detail_items = []

for view in placed_views:
    collector = FilteredElementCollector(doc, view.Id) \
        .OfCategory(BuiltInCategory.OST_DetailComponents) \
        .WhereElementIsNotElementType()
    for item in collector:
        if isinstance(item, FamilyInstance):
            # Проверяем имя семейства
            family_name = item.Symbol.Family.Name
            if not family_name.startswith("PEER_Rebar_Shape"):
                continue  # Пропускаем не те семейства

            param = item.LookupParameter('Rebar_Number')
            if param:
                val = None
                if param.StorageType == StorageType.Integer:
                    val = param.AsInteger()
                elif param.StorageType == StorageType.Double:
                    val = int(param.AsDouble())
                else:
                    val = param.AsString()
                if val and str(val).strip() == rebar_number_input.strip():
                    detail_items.append(item)


if not detail_items:
    forms.alert("Detail Item with number '{}' was not found on the sheet.".format(user_input_number))
    script.exit()

first_item = detail_items[0]

def get_param(elem, param_name):
    param = elem.LookupParameter(param_name)
    if param:
        if param.StorageType == StorageType.Integer:
            val = param.AsInteger()
            return str(val) if val is not None else None
        elif param.StorageType == StorageType.Double:
            val = param.AsValueString()
            return val if val not in [None, ""] else None
        else:
            val = param.AsString()
            return val if val not in [None, ""] else None
    return None


rebar_number = get_param(first_item, 'Rebar_Number')
rebar_diameter = get_param(first_item, 'Rebar_Diameter')
rebar_length = get_param(first_item, 'Rebar_Length')
rebar_quantity_text = get_param(first_item, 'Rebar_Quantity Text')
rebar_spacing = get_param(first_item, 'Rebar_Spacing')
element_id = str(first_item.Id.IntegerValue)

# 6️⃣ Записываем параметры в выбранное семейство
with revit.Transaction("Установка параметров"):
    def set_param(elem, param_name, value):
        for param in elem.Parameters:
            if param.Definition.Name == param_name:
                try:
                    if value in [None, "", "(empty)", "(not found)"]:
                        # Очищаем параметр
                        if param.StorageType == StorageType.Integer:
                            param.Set(0)
                        elif param.StorageType == StorageType.Double:
                            param.Set(0.0)
                        else:
                            param.Set("")
                    else:
                        # Записываем значение как обычно
                        if param.StorageType == StorageType.Integer:
                            cleaned_value = ''.join(c for c in str(value) if c.isdigit() or c in ['.', ','])
                            param.Set(int(float(cleaned_value)))
                        elif param.StorageType == StorageType.Double:
                            cleaned_value = ''.join(c for c in str(value) if c.isdigit() or c in ['.', ','])
                            converted_value = UnitUtils.ConvertToInternalUnits(float(cleaned_value),
                                                                               UnitTypeId.Millimeters)
                            param.Set(converted_value)
                        else:
                            param.Set(str(value))
                except Exception as e:
                    forms.alert("Error: Parameter '{}' requires a number. {}".format(param_name, str(e)))


    set_param(selected_elem, 'Rebar_Number', rebar_number)
    set_param(selected_elem, 'Rebar_Diameter', rebar_diameter)
    set_param(selected_elem, 'Rebar_Length', rebar_length)
    set_param(selected_elem, 'PR_Rebar_ID', element_id)
    set_param(selected_elem, 'Rebar_Quantity Text', rebar_quantity_text)
    set_param(selected_elem, 'Rebar_Spacing', rebar_spacing)

forms.alert("Values successfully transferred to the selected family!")
