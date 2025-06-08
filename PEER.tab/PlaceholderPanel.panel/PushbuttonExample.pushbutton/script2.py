# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *

doc = revit.doc
uidoc = revit.uidoc

from Autodesk.Revit.DB import UnitUtils, UnitTypeId

# 1️⃣ Получаем активный вид
active_view = revit.active_view

# 2️⃣ Собираем все аннотации PEER_Rebar TAG на активном виде
annotation_family_name = 'PEER_Rebar TAG'
annotation_instances = []

collector = FilteredElementCollector(doc, active_view.Id)\
    .OfCategory(BuiltInCategory.OST_DetailComponents)\
    .WhereElementIsNotElementType()

for item in collector:
    if isinstance(item, FamilyInstance):
        try:
            if item.Symbol.Family.Name == annotation_family_name:
                annotation_instances.append(item)
        except:
            continue

if not annotation_instances:
    forms.alert("На активном виде не найдено аннотационных семейств '{}'.".format(annotation_family_name))
    script.exit()

# 3️⃣ Функции
def get_param_value(elem, param_name):
    param = elem.LookupParameter(param_name)
    if param:
        if param.StorageType == StorageType.Integer:
            raw_value = str(param.AsInteger())
            return raw_value
        elif param.StorageType == StorageType.Double:
            raw_value = param.AsValueString()
            cleaned_value = ''.join(c for c in raw_value if c.isdigit() or c in ['.', ','])
            return cleaned_value
        else:
            raw_value = param.AsString() or "(пусто)"
            return raw_value
    else:
        return None

def set_param(elem, param_name, value):
    for param in elem.Parameters:
        if param.Definition.Name == param_name:
            try:
                cleaned_value = ''.join(c for c in str(value) if c.isdigit() or c in ['.', ','])
                if param.StorageType == StorageType.Integer:
                    param.Set(int(float(cleaned_value)))
                elif param.StorageType == StorageType.Double:
                    converted_value = UnitUtils.ConvertToInternalUnits(float(cleaned_value), UnitTypeId.Millimeters)
                    param.Set(converted_value)
                else:
                    param.Set(str(value))
            except Exception as e:
                forms.alert("Ошибка при установке параметра '{}': {}".format(param_name, str(e)))
            return

# 4️⃣ Обновляем параметры для каждого PEER TAG
updated_count = 0

with revit.Transaction("Обновление параметров аннотаций арматуры"):
    for anno in annotation_instances:
        source_id_param = anno.LookupParameter('PR_Rebar_ID')
        if source_id_param:
            try:
                source_id_raw = source_id_param.AsString() or source_id_param.AsValueString()
                if not source_id_raw:
                    continue
                source_id_cleaned = ''.join(c for c in source_id_raw if c.isdigit())
                if not source_id_cleaned:
                    continue
                source_id = int(source_id_cleaned)
                source_elem = doc.GetElement(ElementId(source_id))
                if source_elem:
                    # Читаем параметры ИСКЛЮЧИТЕЛЬНО из исходного элемента
                    rebar_number = get_param_value(source_elem, 'Rebar_Number')
                    rebar_diameter = get_param_value(source_elem, 'Rebar_Diameter')
                    rebar_length = get_param_value(source_elem, 'Rebar_Length')

                    # Обновляем PEER TAG значениями из исходного элемента
                    set_param(anno, 'Rebar_Number', rebar_number)
                    set_param(anno, 'Rebar_Diameter', rebar_diameter)
                    set_param(anno, 'Rebar_Length', rebar_length)

                    updated_count += 1
            except Exception as e:
                forms.alert("Ошибка при обработке элемента ID {}: {}".format(source_id_param.AsString(), str(e)))

forms.alert("Обновлено {} обозначений арматуры.".format(updated_count))
