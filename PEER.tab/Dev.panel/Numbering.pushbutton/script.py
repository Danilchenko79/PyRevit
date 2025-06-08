# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script

# ==============================
# Функции для скрипта
# ==============================

def is_schedule_view(view):
    """
    Проверка: активный вид — спецификация.
    """
    return isinstance(view, DB.ViewSchedule) and not view.IsTitleblockRevisionSchedule


def get_ordered_elements_from_schedule(schedule):
    """
    Возвращает элементы в порядке отображения в спецификации (с учётом сортировки и группировки).
    """
    table_data = schedule.GetTableData()
    body_data = table_data.GetSectionData(DB.SectionType.Body)
    elements = []
    for row in range(body_data.FirstRowNumber, body_data.LastRowNumber + 1):
        ids = body_data.GetRowElementIds(row)
        # Обычно строка спецификации отображает один элемент
        if ids.Count == 1:
            el = schedule.Document.GetElement(ids[0])
            if el is not None:
                elements.append(el)
        # Если несколько (группировка) — пропускаем или можно доработать логику под задачу
    return elements


def get_common_string_numeric_params(elements):
    """
    Находит общие строковые и числовые параметры для всех элементов.
    """
    if not elements:
        return []
    first_elem = elements[0]
    param_defs = []
    for p in first_elem.Parameters:
        if p.StorageType in [DB.StorageType.String, DB.StorageType.Integer, DB.StorageType.Double]:
            param_defs.append((p.Definition.Name, p.StorageType))
    # Проверяем, что параметр есть у всех
    common_params = []
    for name, stype in param_defs:
        if all(e.LookupParameter(name) is not None for e in elements):
            common_params.append(name)
    return common_params


def set_param_value(elem, param_name, value):
    param = elem.LookupParameter(param_name)
    if param:
        if param.StorageType == DB.StorageType.String:
            param.Set(str(value))
        elif param.StorageType == DB.StorageType.Integer:
            param.Set(int(value))
        elif param.StorageType == DB.StorageType.Double:
            param.Set(float(value))
        else:
            return False
        return True
    return False

# ==============================
# Основная логика
# ==============================

doc = revit.doc
uidoc = revit.uidoc
active_view = doc.ActiveView

if not is_schedule_view(active_view):
    forms.alert("Скрипт должен запускаться только на виде спецификации!", exitscript=True)

schedule = active_view

# Получаем элементы спецификации строго в порядке отображения (сортировка и группировка)
elements = get_ordered_elements_from_schedule(schedule)
if not elements:
    forms.alert("В спецификации не найдено элементов для нумерации.", exitscript=True)

# Получаем доступные параметры
param_names = get_common_string_numeric_params(elements)
if not param_names:
    forms.alert("Нет общих строковых/числовых параметров для всех элементов.", exitscript=True)

# ======== ПРОСТОЙ UI БЕЗ XAML ========

param_name = forms.SelectFromList.show(param_names, name='Целевой параметр')
if not param_name:
    script.exit()

start_value_str = forms.ask_for_string(
    default='1', prompt='Начальное значение'
)
if start_value_str is None:
    script.exit()
try:
    start_value = int(start_value_str)
except ValueError:
    forms.alert("Некорректное начальное значение!", exitscript=True)

step_str = forms.ask_for_string(
    default='1', prompt='Шаг'
)
if step_str is None:
    script.exit()
try:
    step = int(step_str)
except ValueError:
    forms.alert("Некорректный шаг!", exitscript=True)


# Применяем нумерацию
with revit.Transaction("Нумерация элементов спецификации"):
    value = start_value
    for elem in elements:
        set_param_value(elem, param_name, value)
        value += step

forms.alert("Нумерация завершена!", exitscript=True)
