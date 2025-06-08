# -*- coding: utf-8 -*-
from pyrevit import revit, forms, script
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB import UnitUtils, UnitTypeId

doc = revit.doc

# Получаем активный вид
active_view = revit.active_view

# Имя семейства аннотации
ANNOTATION_FAMILY_NAME = "PEER_Rebar TAG"

# Собираем все аннотации на активном виде
annotation_instances = []
collector = FilteredElementCollector(doc, active_view.Id)\
    .OfCategory(BuiltInCategory.OST_DetailComponents)\
    .WhereElementIsNotElementType()

for fi in collector:
    if isinstance(fi, FamilyInstance):
        try:
            if fi.Symbol.Family.Name == ANNOTATION_FAMILY_NAME:
                annotation_instances.append(fi)
        except Exception:
            continue

if not annotation_instances:
    forms.alert("На активном виде не найдено аннотационных семейств '{}'.".format(ANNOTATION_FAMILY_NAME))
    script.exit()

# Функция для получения значения параметра
def get_param_value(elem, param_name):
    param = elem.LookupParameter(param_name)
    if param:
        try:
            if param.StorageType == StorageType.Integer:
                return str(param.AsInteger())
            elif param.StorageType == StorageType.Double:
                raw_value = param.AsValueString()
                cleaned = "".join(c for c in raw_value if c.isdigit() or c in ['.', ','])
                return cleaned
            else:
                return param.AsString() or "(пусто)"
        except Exception:
            return "(ошибка чтения)"
    return None

# Функция для установки значения параметра
def set_param_value(elem, param_name, value):
    param = elem.LookupParameter(param_name)
    if param and value:
        try:
            cleaned_value = "".join(c for c in str(value) if c.isdigit() or c in ['.', ','])
            if param.StorageType == StorageType.Integer:
                param.Set(int(float(cleaned_value)))
            elif param.StorageType == StorageType.Double:
                internal_value = UnitUtils.ConvertToInternalUnits(float(cleaned_value), UnitTypeId.Millimeters)
                param.Set(internal_value)
            else:
                param.Set(str(value))
        except Exception as e:
            forms.alert("Ошибка при установке параметра '{}': {}".format(param_name, e))

# Основная часть: обновляем параметры
updated_count = 0
missing_elements = []

with revit.Transaction("Обновление параметров аннотаций арматуры"):
    for tag in annotation_instances:
        source_id_param = tag.LookupParameter("PR_Rebar_ID")
        if source_id_param:
            try:
                raw_id = source_id_param.AsString() or source_id_param.AsValueString()
                if not raw_id:
                    continue
                source_id_str = "".join(c for c in raw_id if c.isdigit())
                if not source_id_str:
                    continue
                source_elem_id = int(source_id_str)
                source_elem = doc.GetElement(ElementId(source_elem_id))
                if not source_elem:
                    missing_elements.append(source_id_str)
                    continue

                # Читаем параметры из исходного элемента
                rebar_number = get_param_value(source_elem, "Rebar_Number")
                rebar_diameter = get_param_value(source_elem, "Rebar_Diameter")
                rebar_length = get_param_value(source_elem, "Rebar_Length")

                # Записываем параметры обратно в аннотацию
                set_param_value(tag, "Rebar_Number", rebar_number)
                set_param_value(tag, "Rebar_Diameter", rebar_diameter)
                set_param_value(tag, "Rebar_Length", rebar_length)

                updated_count += 1
            except Exception as e:
                forms.alert("Ошибка при обработке элемента ID {}: {}".format(raw_id, e))

# Выводим итог
result_message = "Обновлено {} обозначений арматуры.".format(updated_count)
if missing_elements:
    missing_str = ", ".join(missing_elements)
    result_message += "\n\n⚠️ Для следующих элементов не найдены исходные объекты (возможно, они были удалены): {}".format(missing_str)

forms.alert(result_message)
