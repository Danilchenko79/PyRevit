# -*- coding: utf-8 -*-
__title__ = "Rebar Tag - Выбор"
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
    ref = uidoc.Selection.PickObject(ObjectType.Element, "Выберите семейство для обновления")
    selected_elem = doc.GetElement(ref.ElementId)
except Exception as e:
    if "cancelled" in str(e).lower():
        forms.alert("Операция выбора отменена.")
        script.exit()
    else:
        raise

# Проверяем, что выбрано именно Detail Item
if not isinstance(selected_elem, FamilyInstance):
    forms.alert("Выбранный элемент не является Detail Item.")
    script.exit()

# 2️⃣ Запрашиваем у пользователя номер арматуры
rebar_number_input = forms.ask_for_string(
    default='',
    prompt='Введите номер арматуры для поиска:',
    title='Поиск арматуры'
)

if not rebar_number_input:
    forms.alert("Номер арматуры не введен. Скрипт остановлен.")
    script.exit()

try:
    user_input_number = int(rebar_number_input.strip())
except:
    forms.alert("Введите корректное число для номера арматуры.")
    script.exit()

# 3️⃣ Ищем лист, на который размещён активный вид
viewport_collector = FilteredElementCollector(doc).OfClass(Viewport)
sheet_id = None

for vp in viewport_collector:
    if vp.ViewId == revit.active_view.Id:
        sheet_id = vp.SheetId
        break

if not sheet_id:
    forms.alert("Активный вид не размещён ни на одном листе.")
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

# 5️⃣ Ищем Detail Item с этим номером
detail_items = []

for view in placed_views:
    collector = FilteredElementCollector(doc, view.Id) \
        .OfCategory(BuiltInCategory.OST_DetailComponents) \
        .WhereElementIsNotElementType()
    for item in collector:
        if isinstance(item, FamilyInstance):
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
    forms.alert("Detail Item с номером '{}' не найден на листе.".format(user_input_number))
    script.exit()

first_item = detail_items[0]

def get_param(elem, param_name):
    param = elem.LookupParameter(param_name)
    if param:
        if param.StorageType == StorageType.Integer:
            return str(param.AsInteger())
        elif param.StorageType == StorageType.Double:
            return param.AsValueString()
        else:
            return param.AsString() or "(пусто)"
    return "(не найдено)"

rebar_number = get_param(first_item, 'Rebar_Number')
rebar_diameter = get_param(first_item, 'Rebar_Diameter')
rebar_length = get_param(first_item, 'Rebar_Length')
element_id = str(first_item.Id.IntegerValue)

# 6️⃣ Записываем параметры в выбранное семейство
with revit.Transaction("Установка параметров"):
    def set_param(elem, param_name, value):
        for param in elem.Parameters:
            if param.Definition.Name == param_name:
                try:
                    if param.StorageType == StorageType.Integer:
                        cleaned_value = ''.join(c for c in str(value) if c.isdigit() or c in ['.', ','])
                        param.Set(int(float(cleaned_value)))
                    elif param.StorageType == StorageType.Double:
                        cleaned_value = ''.join(c for c in str(value) if c.isdigit() or c in ['.', ','])
                        converted_value = UnitUtils.ConvertToInternalUnits(float(cleaned_value), UnitTypeId.Millimeters)
                        param.Set(converted_value)
                    else:
                        param.Set(str(value))
                except Exception as e:
                    forms.alert("Ошибка: параметр '{}' требует число. {}".format(param_name, str(e)))


    set_param(selected_elem, 'Rebar_Number', rebar_number)
    set_param(selected_elem, 'Rebar_Diameter', rebar_diameter)
    set_param(selected_elem, 'Rebar_Length', rebar_length)
    set_param(selected_elem, 'PR_Rebar_ID', element_id)

forms.alert("Значения успешно перенесены в выбранное семейство!")
