# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *

doc = revit.doc
uidoc = revit.uidoc

# 1️⃣ Запрашиваем у пользователя номер арматуры
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

# 2️⃣ Получаем активный вид
active_view = revit.active_view

# 3️⃣ Ищем лист, на который размещён активный вид
viewport_collector = FilteredElementCollector(doc).OfClass(Viewport)
sheet_id = None

for vp in viewport_collector:
    if vp.ViewId == active_view.Id:
        sheet_id = vp.SheetId
        break

if not sheet_id:
    forms.alert("Активный вид не размещён ни на одном листе.")
    script.exit()

# 4️⃣ Получаем сам лист
sheet = doc.GetElement(sheet_id)

# 5️⃣ Получаем все виды на этом листе
placed_views = []
viewport_ids = sheet.GetAllViewports()

for vp_id in viewport_ids:
    vp = doc.GetElement(vp_id)
    if hasattr(vp, 'ViewId'):
        view = doc.GetElement(vp.ViewId)
        placed_views.append(view)

# 6️⃣ Ищем Detail Items с этим номером
detail_items = []

for view in placed_views:
    collector = FilteredElementCollector(doc, view.Id)\
        .OfCategory(BuiltInCategory.OST_DetailComponents)\
        .WhereElementIsNotElementType()

    for item in collector:
        if isinstance(item, FamilyInstance):
            param = item.LookupParameter('Rebar_Number')
            if param:
                if param.StorageType == StorageType.Integer:
                    param_value = param.AsInteger()
                    if param_value == user_input_number:
                        detail_items.append(item)
                elif param.StorageType == StorageType.Double:
                    param_value = param.AsDouble()
                    if int(param_value) == user_input_number:
                        detail_items.append(item)
                else:
                    param_value = param.AsString()
                    if param_value and param_value.strip() == rebar_number_input.strip():
                        detail_items.append(item)

if not detail_items:
    forms.alert("На листе не найден Detail Item с номером: {}".format(user_input_number))
    script.exit()

# 7️⃣ Берём первый Detail Item
first_item = detail_items[0]
element_id = str(first_item.Id.IntegerValue)

# 8️⃣ Читаем параметры
def get_param_as_string(elem, param_name):
    param = elem.LookupParameter(param_name)
    if param:
        if param.StorageType == StorageType.Integer:
            return str(param.AsInteger())
        elif param.StorageType == StorageType.Double:
            return param.AsValueString()
        else:
            return param.AsString() or "(пусто)"
    else:
        return "(не найдено)"

rebar_number = get_param_as_string(first_item, 'Rebar_Number')
rebar_diameter = get_param_as_string(first_item, 'Rebar_Diameter')
rebar_spacing = get_param_as_string(first_item, 'Rebar_Spacing')

result = (
    "Параметры первого Detail Item с номером '{}':\n".format(user_input_number) +
    "Element ID: {}\n".format(element_id) +
    "Rebar_Number: {}\n".format(rebar_number) +
    "Rebar_Diameter: {}\n".format(rebar_diameter) +
    "Rebar_Spacing: {}".format(rebar_spacing)
)

forms.alert(result)

# 🔟 Ищем семейство PEER_Rebar TAG
annotation_family_name = 'PEER_Rebar TAG'
annotation_symbol = None

for fs in FilteredElementCollector(doc).OfClass(FamilySymbol)\
        .OfCategory(BuiltInCategory.OST_DetailComponents):
    if fs.Family.Name == annotation_family_name:
        annotation_symbol = fs
        break

if not annotation_symbol:
    forms.alert("Семейство-аннотация '{}' не найдено в проекте.".format(annotation_family_name))
    script.exit()

# 🔟.1 Спрашиваем точку размещения и сразу создаём семейство
if not annotation_symbol.IsActive:
    with revit.Transaction("Activate Family Symbol"):
        annotation_symbol.Activate()

try:
    picked_point = uidoc.Selection.PickPoint("Укажите точку для размещения обозначения")
except Exception as e:
    if "aborted the pick operation" in str(e).lower():
        forms.alert("Операция размещения отменена пользователем.")
        script.exit()
    else:
        raise

with revit.Transaction("Размещение и установка параметров"):
    annotation_instance = doc.Create.NewFamilyInstance(picked_point, annotation_symbol, active_view)

    def set_param(elem, param_name, value):
        param = elem.LookupParameter(param_name)
        if param and not param.IsReadOnly:
            param.Set(value)

    set_param(annotation_instance, 'Rebar_Number', rebar_number)
    set_param(annotation_instance, 'Rebar_Diameter', rebar_diameter)
    set_param(annotation_instance, 'Rebar_Spacing', rebar_spacing)
    set_param(annotation_instance, 'PR_Rebar_ID', element_id)

forms.alert("Обозначение арматуры успешно размещено и параметры обновлены!")
