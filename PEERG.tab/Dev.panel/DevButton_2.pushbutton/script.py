# -*- coding: utf-8 -*-

__title__ = "Numbering"
__author__ = "Dima D"
__doc__ = "Нумерует элементы в активной спецификации, сортируя их как в таблице, и записывает в выбранный параметр из выпадающего списка, начиная с 1."

from pyrevit import script, forms
from Autodesk.Revit.DB import (
    ViewSchedule,
    TableData,
    SectionType,
    Transaction
)

doc = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

# Проверяем, что активный вид — это спецификация
if not isinstance(active_view, ViewSchedule):
    forms.alert("Активный вид должен быть спецификацией.", exitscript=True)


# Получаем список доступных параметров из спецификации
schedule_definition = active_view.Definition
field_count = schedule_definition.GetFieldCount()

param_names = []

for i in range(field_count):
    field = schedule_definition.GetField(i)
    param_name = field.GetName()
    if param_name not in param_names:
        param_names.append(param_name)

if not param_names:
    forms.alert("Не удалось найти параметры в спецификации.", exitscript=True)

# Спрашиваем у пользователя, какой параметр использовать
selected_param = forms.SelectFromList.show(
    param_names,
    title="Выберите параметр для нумерации",
    multiselect=False
)

if not selected_param:
    script.exit("Параметр не выбран.")

# Собираем все элементы из строки спецификации
table_data = active_view.GetTableData()
section_data = table_data.GetSectionData(SectionType.Body)
row_count = section_data.NumberOfRows

element_ids = []

for row in range(row_count):
    try:
        el_id = active_view.GetCellElementId(SectionType.Body, row, 0)
        if el_id and el_id.IntegerValue > 0:
            element_ids.append(el_id)
    except Exception:
        pass  # строка без элемента, например итоги

if not element_ids:
    forms.alert("Не найдено элементов в таблице.", exitscript=True)

# Нумерация элементов
with Transaction(doc, "Number Elements from Active Schedule") as t:
    t.Start()
    counter = 1
    for el_id in element_ids:
        element = doc.GetElement(el_id)
        param = element.LookupParameter(selected_param)
        if param and not param.IsReadOnly:
            param.Set(str(counter))
            counter += 1
    t.Commit()

forms.alert("Нумерация завершена!", exitscript=True)
